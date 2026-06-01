# -*- coding: utf-8 -*-
"""NEO 积分/排行榜统一用户标识：优先钉钉 userid，避免 username 与 userid 双轨。"""
from __future__ import annotations

from typing import Any, Dict, Optional


def resolve_neo_user_key(user: Optional[Dict[str, Any]], user_manager=None) -> str:
    """
    规范 user_key：userid（钉钉）> 从库补全的 userid > username > id。
    与 NEO backend _user_key_from_user、排行榜 active-users 保持一致。
    """
    if not user or not isinstance(user, dict):
        return ""
    uid = str(user.get("userid") or "").strip()
    if uid:
        return uid
    username = str(user.get("username") or "").strip()
    if user_manager and username:
        try:
            db_user = user_manager.get_user_by_username(username)
            if db_user:
                db_uid = str(db_user.get("userid") or "").strip()
                if db_uid:
                    return db_uid
        except Exception:
            pass
    if username:
        return username
    rid = user.get("id")
    if rid is not None and str(rid).strip() != "":
        return str(rid).strip()
    return ""


def enrich_session_user_inplace(
    user: Dict[str, Any],
    session_id: str,
    user_manager,
    sessions: dict,
    sessions_lock,
) -> Dict[str, Any]:
    """会话缺少 userid 时从用户库补全并写回 session（内存 + DB）。"""
    if not user or not session_id:
        return user
    if str(user.get("userid") or "").strip():
        return user
    username = str(user.get("username") or "").strip()
    if not username or not user_manager:
        return user
    try:
        db_user = user_manager.get_user_by_username(username)
    except Exception:
        return user
    if not db_user:
        return user
    db_uid = str(db_user.get("userid") or "").strip()
    if not db_uid:
        return user
    patch = {
        "userid": db_uid,
        "unionid": db_user.get("unionid") or user.get("unionid") or "",
    }
    try:
        from server.session_manager import sync_session_patch

        sync_session_patch(session_id, patch, sessions, sessions_lock)
    except Exception:
        pass
    user.update(patch)
    return user


def get_shared_user_manager():
    """与 HardwareRDBHandler 共用的 UserManager 单例。"""
    try:
        from server.main import HardwareRDBHandler
        from server.user_manager import UserManager

        if HardwareRDBHandler._user_manager is None:
            with HardwareRDBHandler._lock:
                if HardwareRDBHandler._user_manager is None:
                    HardwareRDBHandler._user_manager = UserManager()
        return HardwareRDBHandler._user_manager
    except Exception:
        return None
