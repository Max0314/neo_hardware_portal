# -*- coding: utf-8 -*-
"""向 NEO 后端上报用户积分事件（物料库等 htmlsystm 侧操作）。"""
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_RETRY_DELAYS = (0.5, 1.5, 3.0)
_retry_thread_started = False
_retry_thread_lock = threading.Lock()


def _user_key_from_user(user: Optional[Dict[str, Any]]) -> str:
    if not user:
        return ""
    uk = user.get("userKey") or user.get("user_key")
    if uk is not None and str(uk).strip():
        return str(uk).strip()
    from server.neo_user_key import get_shared_user_manager, resolve_neo_user_key

    return resolve_neo_user_key(user, get_shared_user_manager())


def _table_exists(cursor, table_name: str) -> bool:
    cursor.execute(
        '''
        SELECT COUNT(*) as count
        FROM information_schema.tables
        WHERE table_schema = DATABASE()
        AND table_name = %s
        ''',
        (table_name,),
    )
    row = cursor.fetchone()
    if isinstance(row, dict):
        return int(row.get("count", 0)) > 0
    return bool(row and int(row[0]) > 0)


def _enqueue_pending_points(user_key: str, event_type: str, error: str) -> None:
    try:
        from server.db_adapter import get_connection_pool

        pool = get_connection_pool()
        with pool.get_cursor() as cursor:
            if not _table_exists(cursor, "neo_points_pending"):
                return
            cursor.execute(
                '''
                INSERT INTO neo_points_pending (user_key, event_type, attempts, last_error)
                VALUES (%s, %s, 0, %s)
                ''',
                (user_key, event_type, error[:512]),
            )
    except Exception as e:
        logger.warning("写入 NEO 积分补偿队列失败: user=%s event=%s err=%s", user_key, event_type, e)


def _post_points_event(base: str, secret: str, user_key: str, event_type: str) -> None:
    url = f"{base}/api/internal/points-event"
    payload = json.dumps({"user_key": user_key, "event": event_type}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "X-Neo-Internal-Secret": secret,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=8) as resp:
        if resp.status >= 400:
            raise urllib.error.URLError(f"HTTP {resp.status}")


def _retry_pending_points_once() -> None:
    try:
        from server.db_adapter import get_connection_pool

        pool = get_connection_pool()
        with pool.get_cursor() as cursor:
            if not _table_exists(cursor, "neo_points_pending"):
                return
            cursor.execute(
                '''
                SELECT id, user_key, event_type, attempts
                FROM neo_points_pending
                WHERE attempts < 5
                ORDER BY created_at ASC
                LIMIT 20
                '''
            )
            rows = cursor.fetchall() or []

        base = (os.getenv("NEO_INTERNAL_URL") or os.getenv("HTMLSYSTM_INTERNAL_URL") or "").strip().rstrip("/")
        secret = os.getenv("NEO_INTERNAL_SECRET", "neo-hw-internal")
        if not base:
            return

        for row in rows:
            if isinstance(row, dict):
                row_id = row["id"]
                user_key = row["user_key"]
                event_type = row["event_type"]
                attempts = int(row.get("attempts", 0))
            else:
                row_id, user_key, event_type, attempts = row[0], row[1], row[2], row[3]

            try:
                _post_points_event(base, secret, user_key, event_type)
                with pool.get_cursor() as cursor:
                    cursor.execute("DELETE FROM neo_points_pending WHERE id = %s", (row_id,))
            except Exception as e:
                with pool.get_cursor() as cursor:
                    cursor.execute(
                        '''
                        UPDATE neo_points_pending
                        SET attempts = %s, last_error = %s
                        WHERE id = %s
                        ''',
                        (attempts + 1, str(e)[:512], row_id),
                    )
    except Exception as e:
        logger.debug("NEO 积分补偿重试线程异常: %s", e)


def _ensure_retry_thread() -> None:
    global _retry_thread_started
    with _retry_thread_lock:
        if _retry_thread_started:
            return
        _retry_thread_started = True

        def worker():
            while True:
                time.sleep(60)
                _retry_pending_points_once()

        threading.Thread(target=worker, daemon=True, name="neo-points-retry").start()


def award_neo_points(user: Optional[Dict[str, Any]], event_type: str) -> None:
    base = (os.getenv("NEO_INTERNAL_URL") or os.getenv("HTMLSYSTM_INTERNAL_URL") or "").strip().rstrip("/")
    if not base:
        return
    uk = _user_key_from_user(user)
    if not uk:
        return
    secret = os.getenv("NEO_INTERNAL_SECRET", "neo-hw-internal")

    last_error = ""
    for delay in _RETRY_DELAYS:
        try:
            _post_points_event(base, secret, uk, event_type)
            return
        except urllib.error.URLError as e:
            last_error = str(e)
            logger.warning("NEO 积分上报失败(将重试): event=%s user=%s err=%s", event_type, uk, e)
            time.sleep(delay)

    logger.warning("NEO 积分上报最终失败: event=%s user=%s err=%s", event_type, uk, last_error)
    _enqueue_pending_points(uk, event_type, last_error)
    _ensure_retry_thread()
