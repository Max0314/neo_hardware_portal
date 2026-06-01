#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
快捷链接管理器
用于管理主页上的快捷链接
"""
import glob
import hashlib
import json
import os
import re
import threading
import time
from server.config import DATA_DIR, STATIC_DIR
from server.logger import logger

# 启动批量抓取时，每条链接之间的间隔（秒），减轻内网/目标站压力
QUICK_LINK_ICON_FETCH_INTERVAL_SEC = max(
    0.5,
    float(os.getenv('QUICK_LINK_ICON_FETCH_INTERVAL_SEC', '1.5')),
)

# 启动时抓取的站点图标目录（挂载 data 卷持久化）
QUICK_LINK_ICONS_DIR = os.path.join(DATA_DIR, 'quick_link_icons')
# 对外 URL 前缀（由 main._resolve_static_file_path 映射到 QUICK_LINK_ICONS_DIR）
QUICK_LINK_ICON_URL_PREFIX = '/static/quick_link_icons'
DEFAULT_QUICK_LINK_ICON_URL = '/static/neo-logo.svg'


def _needs_icon_fetch(link: dict) -> bool:
    """是否仍需抓取站点图标：无 icon_url、或仍为默认 logo。"""
    if not isinstance(link, dict):
        return False
    icon_url = str(link.get('icon_url') or '').strip()
    if not icon_url:
        return True
    normalized = icon_url.split('?', 1)[0].rstrip('/')
    if normalized == DEFAULT_QUICK_LINK_ICON_URL.rstrip('/'):
        return True
    if normalized.endswith('neo-logo.svg'):
        return True
    if normalized.startswith(QUICK_LINK_ICON_URL_PREFIX.rstrip('/') + '/'):
        return False
    return False


class QuickLinkManager:
    """快捷链接管理器"""
    
    def __init__(self):
        self.data_file = os.path.join(DATA_DIR, 'quick_links.json')
        self.icons_dir = QUICK_LINK_ICONS_DIR
        self.lock = threading.Lock()
        self._ensure_data_file()
        os.makedirs(self.icons_dir, exist_ok=True)
    
    def _ensure_data_file(self):
        """确保数据文件存在"""
        if not os.path.exists(self.data_file):
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump([], f, ensure_ascii=False, indent=2)
            logger.info(f"创建快捷链接数据文件: {self.data_file}")
    
    def get_links(self):
        """获取所有快捷链接"""
        with self.lock:
            try:
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    links = json.load(f)
                return links
            except Exception as e:
                logger.error(f"读取快捷链接失败: {e}", exc_info=True)
                return []
    
    def add_link(self, name, url, icon='🔗', description=''):
        """添加快捷链接；保存后立即尝试抓取站点 favicon，返回 (success, message, icon_url)。"""
        try:
            with self.lock:
                if os.path.exists(self.data_file):
                    with open(self.data_file, 'r', encoding='utf-8') as f:
                        links = json.load(f)
                else:
                    links = []

                for link in links:
                    if link.get('url') == url:
                        return False, "该链接已存在", None

                link_id = self._next_link_id(links)
                new_link = {
                    'id': link_id,
                    'name': name,
                    'url': url,
                    'icon': icon,
                    'description': description,
                }
                links.append(new_link)

                with open(self.data_file, 'w', encoding='utf-8') as f:
                    json.dump(links, f, ensure_ascii=False, indent=2)

                logger.info(f"添加快捷链接: {name} -> {url}")
                saved_url = new_link['url']

            # 后台抓取图标，避免阻塞 HTTP worker（否则 2 worker 占满后整站无法增删）
            threading.Thread(
                target=self._fetch_icon_after_add,
                args=(link_id, saved_url, name),
                daemon=True,
                name=f"quick-link-icon-{link_id}",
            ).start()
            return True, "添加成功", None
        except Exception as e:
            logger.error(f"添加快捷链接失败: {e}", exc_info=True)
            return False, f"添加失败: {str(e)}", None
    
    def delete_link(self, link_id):
        """删除快捷链接"""
        with self.lock:
            try:
                # 直接读取文件，避免调用get_links()导致死锁
                if os.path.exists(self.data_file):
                    with open(self.data_file, 'r', encoding='utf-8') as f:
                        links = json.load(f)
                else:
                    links = []
                
                removed = next((x for x in links if x.get("id") == link_id), None)
                if not removed:
                    return False, "链接不存在"

                self._remove_icon_files(link_id, str(removed.get("url") or ""))
                links = [link for link in links if link.get("id") != link_id]

                with open(self.data_file, "w", encoding="utf-8") as f:
                    json.dump(links, f, ensure_ascii=False, indent=2)

                logger.info(f"删除快捷链接: {link_id}")
                return True, "删除成功"
            except Exception as e:
                logger.error(f"删除快捷链接失败: {e}", exc_info=True)
                return False, f"删除失败: {str(e)}"
    
    def update_link(self, link_id, name=None, url=None, icon=None, description=None):
        """更新快捷链接；URL 变更时在后台重新抓取图标。"""
        old_url = None
        new_url = None
        label = name or link_id
        try:
            with self.lock:
                if os.path.exists(self.data_file):
                    with open(self.data_file, 'r', encoding='utf-8') as f:
                        links = json.load(f)
                else:
                    links = []

                found = False
                for link in links:
                    if link.get('id') != link_id:
                        continue
                    old_url = str(link.get('url') or '')
                    if name is not None:
                        link['name'] = name
                        label = name
                    if url is not None:
                        link['url'] = url
                    if icon is not None:
                        link['icon'] = icon
                    if description is not None:
                        link['description'] = description
                    new_url = str(link.get('url') or '')
                    found = True
                    break

                if not found:
                    return False, "链接不存在"

                with open(self.data_file, 'w', encoding='utf-8') as f:
                    json.dump(links, f, ensure_ascii=False, indent=2)

                logger.info(f"更新快捷链接: {link_id}")

            if url is not None and new_url and new_url != old_url:
                threading.Thread(
                    target=self._fetch_icon_after_add,
                    args=(link_id, new_url, label),
                    daemon=True,
                    name=f"quick-link-icon-{link_id}",
                ).start()
            return True, "更新成功"
        except Exception as e:
            logger.error(f"更新快捷链接失败: {e}", exc_info=True)
            return False, f"更新失败: {str(e)}"

    def _next_link_id(self, links: list) -> str:
        """生成不重复的 link_id（避免删除条目后 id 复用）。"""
        max_n = 0
        for item in links:
            lid = str(item.get("id") or "")
            m = re.match(r"^link_(\d+)$", lid)
            if m:
                max_n = max(max_n, int(m.group(1)))
        return f"link_{max_n + 1}"

    def _icon_file_base(self, link_id: str, url: str = "") -> str:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in (link_id or ""))
        safe = safe or "link"
        if url:
            digest = hashlib.md5(url.encode("utf-8")).hexdigest()[:8]
            return f"{safe}_{digest}"
        return safe

    def _remove_icon_files(self, link_id: str, url: str = "") -> None:
        base = self._icon_file_base(link_id, url)
        pattern = os.path.join(self.icons_dir, f"{base}.*")
        for path in glob.glob(pattern):
            try:
                os.remove(path)
            except OSError as e:
                logger.debug("删除快捷链接图标文件失败 %s: %s", path, e)

    def _save_icon_file(self, link_id: str, data: bytes, ext: str, url: str = "") -> str:
        self._remove_icon_files(link_id, url)
        base = self._icon_file_base(link_id, url)
        filename = f"{base}{ext}"
        path = os.path.join(self.icons_dir, filename)
        with open(path, "wb") as f:
            f.write(data)
        return f"{QUICK_LINK_ICON_URL_PREFIX}/{filename}"

    def _fetch_icon_after_add(self, link_id: str, url: str, name: str = "") -> None:
        """新链接添加后的后台图标抓取。"""
        try:
            icon_url = self._fetch_and_attach_icon(link_id, url, preserve_existing=False)
            if icon_url:
                logger.info("添加快捷链接后台图标已就绪: %s -> %s", name or link_id, icon_url)
            else:
                logger.info("添加快捷链接后台图标未获取到，使用默认图: %s", name or link_id)
        except Exception as e:
            logger.warning("添加快捷链接后台图标抓取异常: %s (%s)", name or link_id, e)

    def _fetch_and_attach_icon(self, link_id: str, url: str, *, preserve_existing: bool = False):
        """
        抓取单个链接的站点图标并写入 quick_links.json。
        成功返回 icon_url；失败时若 preserve_existing=True 则不改动已有 icon_url。
        """
        from server.quick_link_icon_fetcher import fetch_site_icon

        link_id = str(link_id or "").strip()
        url = str(url or "").strip()
        if not link_id or not url:
            return None

        icon_url = None
        result = fetch_site_icon(url)
        if result:
            data, ext = result
            try:
                icon_url = self._save_icon_file(link_id, data, ext, url)
            except Exception as e:
                logger.warning("快捷链接图标保存失败: %s (%s)", link_id, e)

        if not icon_url and preserve_existing:
            return None

        with self.lock:
            try:
                if not os.path.exists(self.data_file):
                    return icon_url
                with open(self.data_file, "r", encoding="utf-8") as f:
                    links = json.load(f)
                if not isinstance(links, list):
                    return icon_url
                for link in links:
                    if not isinstance(link, dict):
                        continue
                    if str(link.get("id") or "").strip() != link_id:
                        continue
                    if icon_url:
                        link["icon_url"] = icon_url
                    elif not preserve_existing:
                        link.pop("icon_url", None)
                    break
                with open(self.data_file, "w", encoding="utf-8") as f:
                    json.dump(links, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.error("更新快捷链接 icon_url 失败: %s", e, exc_info=True)

        return icon_url

    def refresh_all_icons_on_startup(self) -> None:
        """启动后仅对无站点图标或使用默认图的链接批量抓取；失败保留原有 icon_url。"""
        with self.lock:
            try:
                with open(self.data_file, "r", encoding="utf-8") as f:
                    links = json.load(f)
            except Exception as e:
                logger.error("启动抓取快捷链接图标: 读取数据失败 %s", e, exc_info=True)
                return

        if not isinstance(links, list):
            return

        tasks = []
        skipped = 0
        for link in links:
            if not isinstance(link, dict):
                continue
            link_id = str(link.get("id") or "").strip()
            url = str(link.get("url") or "").strip()
            if not link_id or not url:
                continue
            if not _needs_icon_fetch(link):
                skipped += 1
                continue
            tasks.append((link_id, url, link.get("name") or link_id))

        if not tasks:
            logger.info(
                "快捷链接图标启动刷新: 无需抓取（共 %s 条，均已缓存站点图标 %s 条）",
                len(links) if isinstance(links, list) else 0,
                skipped,
            )
            return

        interval = QUICK_LINK_ICON_FETCH_INTERVAL_SEC
        logger.info(
            "快捷链接图标启动刷新开始: 需抓取 %s 条，跳过已有站点图标 %s 条，间隔 %.1fs",
            len(tasks),
            skipped,
            interval,
        )

        ok_count = 0
        for index, (link_id, url, label) in enumerate(tasks):
            if index > 0:
                time.sleep(interval)
            if self._fetch_and_attach_icon(link_id, url, preserve_existing=True):
                ok_count += 1
                logger.info("快捷链接图标已更新: %s", label)
            else:
                logger.info("快捷链接图标抓取失败，保留原图标: %s", label)

        logger.info(
            "快捷链接图标启动刷新完成: 成功 %s / 本次需抓取 %s（跳过 %s 条已有图标）",
            ok_count,
            len(tasks),
            skipped,
        )

    @staticmethod
    def ensure_default_icon_in_static() -> None:
        """保证默认图标文件存在于 static（neo-logo.svg 已存在则跳过）。"""
        default_path = os.path.join(STATIC_DIR, "neo-logo.svg")
        if os.path.isfile(default_path):
            return
        os.makedirs(STATIC_DIR, exist_ok=True)

