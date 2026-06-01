# -*- coding: utf-8 -*-
"""跨 worker 会话失效：文件标记 + 内存 sessions 清理。"""
import os
import threading
import time
from typing import Any, Dict, Optional

from server.config import DATA_DIR
from server.logger import logger

SESSION_MARKER = os.path.join(DATA_DIR, '.session_invalidation_marker')
_listener_started = False
_listener_lock = threading.Lock()


def notify_sessions_invalidated(user_id: int) -> None:
    """通知所有 worker 清理该用户在内存中的 session。"""
    if not user_id:
        return
    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        with open(SESSION_MARKER, 'a', encoding='utf-8') as f:
            f.write(f'{int(user_id)}:{time.time():.6f}\n')
    except Exception as e:
        logger.warning(f'写入 session 失效标记失败: {e}')


def purge_memory_sessions_for_user(
    user_id: int,
    memory_sessions: Optional[Dict[str, Any]],
    memory_lock: Optional[threading.Lock],
) -> int:
    """从进程内 sessions 字典移除指定用户的所有会话。"""
    if not memory_sessions or memory_lock is None or not user_id:
        return 0
    removed = 0
    uid = int(user_id)
    with memory_lock:
        to_del = [
            sid for sid, u in memory_sessions.items()
            if u and int(u.get('id') or 0) == uid
        ]
        for sid in to_del:
            memory_sessions.pop(sid, None)
            removed += 1
    return removed


def _read_new_invalidations(last_pos: int) -> tuple:
    if not os.path.exists(SESSION_MARKER):
        return last_pos, []
    user_ids = []
    try:
        with open(SESSION_MARKER, 'r', encoding='utf-8') as f:
            f.seek(last_pos)
            chunk = f.read()
            new_pos = f.tell()
        for line in chunk.splitlines():
            part = line.strip().split(':', 1)[0]
            if part.isdigit():
                user_ids.append(int(part))
        return new_pos, user_ids
    except Exception:
        return last_pos, []


def start_session_invalidation_listener(
    memory_sessions: Dict[str, Any],
    memory_lock: threading.Lock,
    interval: float = 0.5,
) -> None:
    """后台监听 session 失效标记（每个 worker 启动一次）。"""
    global _listener_started
    with _listener_lock:
        if _listener_started:
            return
        _listener_started = True

    def _loop():
        pos = 0
        if os.path.exists(SESSION_MARKER):
            try:
                pos = os.path.getsize(SESSION_MARKER)
            except Exception:
                pos = 0
        while True:
            try:
                pos, uids = _read_new_invalidations(pos)
                for uid in uids:
                    n = purge_memory_sessions_for_user(uid, memory_sessions, memory_lock)
                    if n:
                        logger.debug(f'会话失效监听: 已清理 user_id={uid} 的 {n} 条内存 session')
            except Exception as e:
                logger.debug(f'session 失效监听异常: {e}')
            time.sleep(interval)

    t = threading.Thread(target=_loop, daemon=True, name='SessionInvalidationListener')
    t.start()
