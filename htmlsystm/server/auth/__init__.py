# -*- coding: utf-8 -*-
"""账号、权限、改密统一模块。"""

from server.auth.permissions import (
    is_super_admin,
    user_has_role,
    has_any_role,
    check_access,
    AuthResult,
)
from server.auth.capabilities import user_capabilities
from server.auth.password_service import PasswordService, get_password_service
from server.auth.responses import auth_ok, auth_error, legacy_wrap
from server.auth.signed_session import AUTH_TOKEN_COOKIE

__all__ = [
    'is_super_admin',
    'user_has_role',
    'has_any_role',
    'check_access',
    'AuthResult',
    'user_capabilities',
    'PasswordService',
    'get_password_service',
    'auth_ok',
    'auth_error',
    'legacy_wrap',
    'AUTH_TOKEN_COOKIE',
]
