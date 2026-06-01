# -*- coding: utf-8 -*-
"""从用户对象推导前端/NEO 所需能力集。"""
from typing import Any, Dict, Optional

from server.auth.permissions import is_super_admin, user_has_role, has_any_role


def user_capabilities(user: Optional[Dict[str, Any]]) -> Dict[str, bool]:
    if not user:
        return {
            'isSuperAdmin': False,
            'canManageAccounts': False,
            'canApproveRegistrations': False,
            'canManageModelConfig': False,
        }
    super_ = is_super_admin(user)
    mgmt = super_ or has_any_role(user, ('management', 'admin'))
    return {
        'isSuperAdmin': super_,
        'canManageAccounts': super_,
        'canApproveRegistrations': super_ or user_has_role(user, 'management') or user_has_role(user, 'admin'),
        'canManageModelConfig': mgmt,
    }
