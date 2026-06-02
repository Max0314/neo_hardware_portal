# -*- coding: utf-8 -*-
"""CSRF 双提交 Cookie 校验。"""
import secrets
from typing import Set

CSRF_COOKIE_NAME = 'csrf_token'
CSRF_HEADER_NAME = 'X-CSRF-Token'

# 无需 CSRF 的写操作路径（登录前或只读探测）
CSRF_EXEMPT_EXACT: Set[str] = {
    '/api/auth/login',
    '/api/auth/register',
    '/api/auth/login-by-userid',
    '/api/auth/dingtalk/inapp-login',
    '/api/captcha',
}

CSRF_EXEMPT_PREFIXES = (
    '/api/neo/internal/',  # NEO 后端服务间调用走 X-Neo-Internal-Secret
)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def is_exempt(path: str, method: str) -> bool:
    method = (method or 'GET').upper()
    if method in ('GET', 'HEAD', 'OPTIONS'):
        return True
    if path in CSRF_EXEMPT_EXACT:
        return True
    for prefix in CSRF_EXEMPT_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


def _parse_cookies(cookie_header: str) -> dict:
    cookies = {}
    for part in (cookie_header or '').split(';'):
        part = part.strip()
        if '=' in part:
            k, v = part.split('=', 1)
            cookies[k.strip()] = v.strip()
    return cookies


def validate(handler) -> bool:
    """校验 POST/PUT/DELETE 的 CSRF；失败返回 False。"""
    path = getattr(handler, 'path', '') or ''
    method = getattr(handler, 'method', 'GET')
    if is_exempt(path, method):
        return True

    if not path.startswith('/api/'):
        return True

    # 未登录改密：无 session_id 时跳过 CSRF（仍须旧密码）
    norm = path.rstrip('/')
    if norm in ('/api/auth/change-password', '/api/auth/password') and method == 'POST':
        cookies = _parse_cookies(handler.headers.get('Cookie', ''))
        if not cookies.get('session_id') and not cookies.get('auth_token'):
            return True

    cookies = _parse_cookies(handler.headers.get('Cookie', ''))
    cookie_token = cookies.get(CSRF_COOKIE_NAME, '')
    header_token = (handler.headers.get(CSRF_HEADER_NAME) or '').strip()
    if not cookie_token or not header_token:
        return False
    return secrets.compare_digest(cookie_token, header_token)


def cookie_header_value(token: str, *, secure: bool) -> str:
    flags = f'{CSRF_COOKIE_NAME}={token}; Path=/; SameSite=Lax; Max-Age=604800'
    if secure:
        flags += '; Secure'
    return flags
