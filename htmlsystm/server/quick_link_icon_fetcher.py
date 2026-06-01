# -*- coding: utf-8 -*-
"""快捷链接站点图标抓取（启动时批量执行，非实时）。"""
from __future__ import annotations

import os
import re
import ssl
from typing import Optional, Tuple
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from server.logger import logger

USER_AGENT = "Mozilla/5.0 (compatible; HardwareRDB-QuickLinkIcon/1.0)"
# 单次 HTTP 超时（秒）；内网不可达时过大会拖长启动批量刷新
FETCH_TIMEOUT = max(1.0, float(os.getenv("QUICK_LINK_ICON_FETCH_TIMEOUT", "3")))
MAX_BYTES = 256 * 1024

_EXT_BY_MIME = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
    "image/x-icon": ".ico",
    "image/vnd.microsoft.icon": ".ico",
}


def _guess_ext(content_type: str, url: str, data: bytes) -> str:
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct in _EXT_BY_MIME:
        return _EXT_BY_MIME[ct]
    path = urlparse(url).path.lower()
    for ext in (".ico", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"):
        if path.endswith(ext):
            return ext if ext != ".jpeg" else ".jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:2] == b"\xff\xd8":
        return ".jpg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    if data[:4] == b"<svg" or (data[:200].strip().startswith(b"<") and b"<svg" in data[:800]):
        return ".svg"
    return ".ico"


def _ssl_context():
    """内网/自签 HTTPS 站点：不校验证书，避免抓取失败。"""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _http_get(url: str) -> Tuple[bytes, str]:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        resp_ctx = _ssl_context()
    except Exception:
        resp_ctx = None
    with urlopen(req, timeout=FETCH_TIMEOUT, context=resp_ctx) as resp:
        data = resp.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError("icon too large")
        return data, (resp.headers.get("Content-Type") or "")


def _parse_html_icon_urls(page_url: str, html: str) -> list:
    found = []
    for tag in re.findall(
        r"<link[^>]+rel=[\"'](?:shortcut icon|icon|apple-touch-icon)[\"'][^>]*>",
        html,
        flags=re.I,
    ):
        m = re.search(r"href=[\"']([^\"']+)[\"']", tag, flags=re.I)
        if m:
            found.append(urljoin(page_url, m.group(1).strip()))
    return found


def fetch_site_icon(page_url: str) -> Optional[Tuple[bytes, str]]:
    """
    尝试获取站点 favicon，返回 (二进制内容, 建议扩展名)。
    失败返回 None。
    """
    parsed = urlparse((page_url or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None

    origin = f"{parsed.scheme}://{parsed.netloc}"
    candidates = [urljoin(origin, "/favicon.ico")]

    try:
        html_bytes, ct = _http_get(page_url)
        if "html" in ct.lower() or html_bytes.lstrip()[:1] in (b"<", b"\xef"):
            html = html_bytes.decode("utf-8", errors="ignore")
            for href in _parse_html_icon_urls(page_url, html):
                if href not in candidates:
                    candidates.insert(0, href)
    except Exception as e:
        logger.debug("快捷链接图标: 解析页面失败 %s: %s", page_url, e)
        # 页面不可达时仅再试 favicon.ico，避免多条候选各等一轮超时
        candidates = [urljoin(origin, "/favicon.ico")]

    seen = set()
    for cand in candidates[:4]:
        if not cand or cand in seen:
            continue
        seen.add(cand)
        try:
            data, ct = _http_get(cand)
            if len(data) < 8:
                continue
            ext = _guess_ext(ct, cand, data)
            return data, ext
        except Exception as e:
            logger.debug("快捷链接图标: 拉取失败 %s: %s", cand, e)
    return None
