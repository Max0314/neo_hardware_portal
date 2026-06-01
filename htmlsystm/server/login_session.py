# -*- coding: utf-8 -*-
"""登录后会话清理（异步、不阻塞响应）。"""
from __future__ import annotations

import threading
from typing import Optional

from server.logger import logger


def prune_other_sessions_async(user_id: int, keep_session_id: str) -> None:
    """后台分批删除该用户其它 sessions，避免登录响应被大表 DELETE 阻塞。"""
    if not user_id or not keep_session_id:
        return

    def _run() -> None:
        try:
            from server.session_manager import get_session_manager

            removed = get_session_manager().delete_other_sessions_for_user(
                int(user_id), keep_session_id
            )
            if removed:
                logger.info(
                    "登录后异步清理旧会话: user_id=%s, removed=%s, keep=%s...",
                    user_id,
                    removed,
                    keep_session_id[:8],
                )
        except Exception as exc:
            logger.warning(
                "登录后异步清理旧会话失败: user_id=%s, keep=%s..., %s",
                user_id,
                keep_session_id[:8],
                exc,
            )

    threading.Thread(
        target=_run,
        daemon=True,
        name=f"prune-sessions-{user_id}",
    ).start()
