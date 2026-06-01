# -*- coding: utf-8 -*-
"""统一权限判定（main.py 与 wsgi_app.py 共用）。"""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Union

from server.security import SUPER_ADMIN_USERNAME


def _parse_roles(user_or_roles: Union[Dict[str, Any], Sequence[str], str, None]) -> List[str]:
    if user_or_roles is None:
        return []
    if isinstance(user_or_roles, dict):
        raw = user_or_roles.get('roles', [])
    else:
        raw = user_or_roles
    if isinstance(raw, list):
        return [str(r).strip() for r in raw if r]
    if not raw:
        return []
    return [r.strip() for r in str(raw).split(',') if r.strip()]


def is_super_admin(user: Optional[Dict[str, Any]]) -> bool:
    if not user or not isinstance(user, dict):
        if isinstance(user, str) and SUPER_ADMIN_USERNAME:
            return user.lower() == SUPER_ADMIN_USERNAME.lower()
        return False
    username = (user.get('username') or '').strip()
    if username and SUPER_ADMIN_USERNAME:
        if username.lower() == SUPER_ADMIN_USERNAME.lower():
            return True
    return 'super_admin' in _parse_roles(user)


def user_has_role(user: Optional[Dict[str, Any]], role: str) -> bool:
    if not user or not role:
        return False
    return role in _parse_roles(user)


def has_any_role(user: Optional[Dict[str, Any]], roles: Sequence[str]) -> bool:
    if not user or not roles:
        return False
    user_roles = set(_parse_roles(user))
    return any(r in user_roles for r in roles)


@dataclass
class AuthResult:
    allowed: bool
    error: Optional[str] = None
    status: int = 403


def check_access(
    user: Optional[Dict[str, Any]],
    *,
    super_admin: bool = False,
    admin: bool = False,
    roles: Optional[Sequence[str]] = None,
) -> AuthResult:
    if not user:
        return AuthResult(False, '未登录，请先登录', 401)
    if super_admin and not is_super_admin(user):
        return AuthResult(False, '仅超级管理员可执行此操作', 403)
    if admin and not (is_super_admin(user) or user_has_role(user, 'admin')):
        return AuthResult(False, '需要管理员权限', 403)
    if roles and not has_any_role(user, roles):
        if not is_super_admin(user):
            return AuthResult(False, '无访问权限', 403)
    return AuthResult(True)
