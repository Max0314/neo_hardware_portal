# -*- coding: utf-8 -*-
"""
Auth HTTP 路由注册表（文档 + 别名常量）。
实际分发仍由 main.py / wsgi_app.py 委托 auth 模块处理。
"""

AUTH_SESSION_PATHS = frozenset({
    '/api/auth/session',
    '/api/auth/check',
})

AUTH_PASSWORD_PATHS = frozenset({
    '/api/auth/password',
    '/api/auth/change-password',
})

AUTH_LOGIN_ALIASES = frozenset({
    '/api/auth/login-by-userid',
})

def is_auth_password_path(path: str) -> bool:
    return (path or '').rstrip('/') in AUTH_PASSWORD_PATHS

def is_auth_session_path(path: str) -> bool:
    return (path or '').rstrip('/') in AUTH_SESSION_PATHS
