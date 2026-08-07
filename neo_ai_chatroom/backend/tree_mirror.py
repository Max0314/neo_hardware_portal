# -*- coding: utf-8 -*-
"""目录树 → 对象存储 的写通镜像。

用途：知识库等目录树的持久化（htmlsystm/server/tree_mirror.py 的副本）。该模块的业务逻辑深度依赖文件系统语义（原子替换、
copytree 版本快照、跨目录 move、fcntl 文件锁），逐点改写成对象 API 的风险
远大于收益。因此持久化模型改为：

    本地目录 = 工作缓存（速度、锁语义、目录扫描都保持原样）
    OSS      = 持久层（卷丢失后可整树恢复）

写路径：业务方法完成本地写入后，调用 sync_subtree() 把该公告的子树差量
上传；删除调用 delete_subtree()。启动时 reconcile() 全树对账，自愈任何
因进程崩溃错过的同步；本地为空而远端有数据时 restore_all() 整树拉回。

一致性取舍（刻意为之）：同步失败只记日志不抛出——公告保存的可用性优先，
差量由下次同步或启动对账补齐。锁文件、临时文件不参与镜像。
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from typing import Dict, List, Optional, Tuple

import logging

logger = logging.getLogger(__name__)

STATE_FILE = '.mirror_state.json'

import contextlib
try:
    import fcntl
    _HAS_FCNTL = True
except ImportError:  # Windows 开发机
    _HAS_FCNTL = False


@contextlib.contextmanager
def _flock(path: str):
    """跨进程互斥：gunicorn 多 worker 各持一个 TreeMirror 实例，线程锁只护得住
    进程内。状态清单的读-改-写若无进程级互斥，两个 worker 并发同步时后写者会
    覆盖前写者的删除记录，在远端留下永远无人认领的孤儿对象（2026-08-07 实测）。
    """
    if not _HAS_FCNTL:
        yield
        return
    fh = open(path, 'a+')
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()

_EXCLUDE_SUFFIXES = ('.lock', '.tmp', '.swp', '.bak')
_EXCLUDE_PARTS = ('locks',)


def _excluded(rel: str, extra_suffixes: Tuple[str, ...] = (),
              extra_parts: Tuple[str, ...] = ()) -> bool:
    parts = rel.replace(os.sep, '/').split('/')
    if any(p in _EXCLUDE_PARTS or p in extra_parts for p in parts[:-1]):
        return True
    name = parts[-1]
    return (name == STATE_FILE
            or name.endswith(_EXCLUDE_SUFFIXES)
            or name.endswith(extra_suffixes))


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1024 * 512), b''):
            h.update(chunk)
    return h.hexdigest()


class TreeMirror:
    def __init__(self, local_root: str, store,
                 exclude_suffixes: Tuple[str, ...] = (),
                 exclude_parts: Tuple[str, ...] = ()) -> None:
        self.root = os.path.abspath(local_root)
        self.store = store
        self._exclude_suffixes = tuple(exclude_suffixes)
        self._exclude_parts = tuple(exclude_parts)
        self._lock = threading.Lock()
        os.makedirs(self.root, exist_ok=True)

    def _is_excluded(self, rel: str) -> bool:
        return _excluded(rel, self._exclude_suffixes, self._exclude_parts)

    # ---------- 状态清单 ----------

    def _state_path(self) -> str:
        return os.path.join(self.root, STATE_FILE)

    def _load_state(self) -> Dict[str, str]:
        try:
            with open(self._state_path(), 'r', encoding='utf-8') as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_state(self, state: Dict[str, str]) -> None:
        tmp = self._state_path() + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(state, fh, ensure_ascii=False, separators=(',', ':'))
        os.replace(tmp, self._state_path())

    # ---------- 本地扫描 ----------

    def _walk_local(self, rel_prefix: str = '') -> Dict[str, str]:
        """返回 {相对key: sha256}。rel_prefix 为空表示全树。"""
        base = os.path.join(self.root, rel_prefix) if rel_prefix else self.root
        found: Dict[str, str] = {}
        if not os.path.isdir(base):
            return found
        for dirpath, _dirs, files in os.walk(base):
            for name in files:
                full = os.path.join(dirpath, name)
                rel = os.path.relpath(full, self.root).replace(os.sep, '/')
                if self._is_excluded(rel):
                    continue
                try:
                    found[rel] = _sha256(full)
                except OSError:
                    continue  # 正被替换的文件下轮补
        return found

    # ---------- 同步原语 ----------

    def sync_subtree(self, rel_prefix: str) -> Tuple[int, int, List[str]]:
        """把某子树（如 hardware/<公告id>）差量同步到远端。

        Returns: (上传数, 远端删除数, 错误列表)。绝不抛出。
        """
        if self.store is None:
            return 0, 0, []
        rel_prefix = rel_prefix.strip('/').replace(os.sep, '/')
        uploaded = removed = 0
        errors: List[str] = []
        with self._lock, _flock(self._state_path() + '.flock'):
            state = self._load_state()
            local = self._walk_local(rel_prefix)

            for rel, sha in local.items():
                if state.get(rel) == sha:
                    continue
                path = os.path.join(self.root, rel)
                try:
                    with open(path, 'rb') as fh:
                        self.store.put_bytes(rel, fh.read())
                    state[rel] = sha
                    uploaded += 1
                except Exception as e:  # noqa: BLE001 — 可用性优先，见模块注释
                    errors.append(f'{rel}: {e}')

            scope = rel_prefix + '/'
            for rel in [k for k in state if k.startswith(scope) or k == rel_prefix]:
                if rel not in local:
                    try:
                        self.store.delete(rel)
                        state.pop(rel, None)
                        removed += 1
                    except Exception as e:  # noqa: BLE001
                        errors.append(f'delete {rel}: {e}')

            self._save_state(state)
        if errors:
            logger.warning('镜像同步 %s 有 %d 个错误（将由启动对账自愈）: %s',
                           rel_prefix, len(errors), '; '.join(errors[:3]))
        return uploaded, removed, errors

    def delete_subtree(self, rel_prefix: str) -> int:
        """删除远端子树并清理状态。绝不抛出，返回删除数。"""
        if self.store is None:
            return 0
        rel_prefix = rel_prefix.strip('/').replace(os.sep, '/')
        n = 0
        with self._lock, _flock(self._state_path() + '.flock'):
            state = self._load_state()
            try:
                n = self.store.delete_prefix(rel_prefix + '/')
                if self.store.exists(rel_prefix):
                    self.store.delete(rel_prefix)
            except Exception as e:  # noqa: BLE001
                logger.warning('镜像删除 %s 失败（启动对账会重试）: %s', rel_prefix, e)
            for k in [k for k in state if k == rel_prefix or k.startswith(rel_prefix + '/')]:
                state.pop(k, None)
            self._save_state(state)
        return n

    def move_subtree(self, src_prefix: str, dst_prefix: str) -> None:
        """本地已完成 move 后调用：同步新位置、删除旧位置。"""
        self.sync_subtree(dst_prefix)
        self.delete_subtree(src_prefix)

    # ---------- 启动期 ----------

    def prefixes_containing(self, segment: str) -> List[str]:
        """从状态清单里找出路径中含指定段（如公告 id）的子树前缀。

        用于删除/跨板块移动后清理远端旧位置：本地目录已不在，只能靠清单
        记忆它曾经在哪。返回截止到该段的前缀，如 hardware/<id>。
        """
        found = set()
        with self._lock, _flock(self._state_path() + '.flock'):
            for rel in self._load_state():
                parts = rel.split('/')
                if segment in parts:
                    found.add('/'.join(parts[:parts.index(segment) + 1]))
        return sorted(found)

    def _has_local_files(self) -> bool:
        for _dirpath, _dirs, files in os.walk(self.root):
            for name in files:
                if not self._is_excluded(name):
                    return True
        return False

    def restore_all(self) -> int:
        """本地为空而远端有数据时整树拉回（卷丢失恢复）。返回恢复文件数。"""
        if self.store is None:
            return 0
        if self._has_local_files():
            return 0
        n = 0
        state: Dict[str, str] = {}
        try:
            for key in self.store.iter_keys(''):
                data = self.store.get_bytes(key)
                if data is None:
                    continue
                path = os.path.join(self.root, key.replace('/', os.sep))
                os.makedirs(os.path.dirname(path), exist_ok=True)
                tmp = path + '.tmp'
                with open(tmp, 'wb') as fh:
                    fh.write(data)
                os.replace(tmp, path)
                state[key] = hashlib.sha256(data).hexdigest()
                n += 1
        except Exception as e:  # noqa: BLE001
            logger.error('镜像整树恢复中断（已恢复 %d 个）: %s', n, e)
        if n:
            with self._lock, _flock(self._state_path() + '.flock'):
                self._save_state(state)
            logger.info('已从对象存储恢复 %d 个文件到 %s', n, self.root)
        return n

    def reconcile(self) -> Tuple[int, int]:
        """全树对账：补传本地新增/变更，删除远端多余。启动后台线程用。"""
        if self.store is None:
            return 0, 0
        with self._lock, _flock(self._state_path() + '.flock'):
            state = self._load_state()
            local = self._walk_local()
            up = rm = 0
            for rel, sha in local.items():
                if state.get(rel) == sha:
                    continue
                try:
                    with open(os.path.join(self.root, rel), 'rb') as fh:
                        self.store.put_bytes(rel, fh.read())
                    state[rel] = sha
                    up += 1
                except Exception as e:  # noqa: BLE001
                    logger.warning('对账上传 %s 失败: %s', rel, e)
            for rel in [k for k in state if k not in local]:
                try:
                    self.store.delete(rel)
                    state.pop(rel, None)
                    rm += 1
                except Exception as e:  # noqa: BLE001
                    logger.warning('对账删除 %s 失败: %s', rel, e)
            self._save_state(state)
        if up or rm:
            logger.info('镜像对账完成：补传 %d，清理 %d', up, rm)
        return up, rm
