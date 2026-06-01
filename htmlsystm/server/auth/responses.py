# -*- coding: utf-8 -*-
"""Auth API 统一响应 envelope 与旧格式兼容包装。"""
from typing import Any, Dict, Optional


def auth_ok(data: Any = None, *, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {'ok': True, 'data': data, 'error': None}
    if meta:
        out['meta'] = meta
    return out


def auth_error(code: str, message: str, *, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        'ok': False,
        'data': None,
        'error': {'code': code, 'message': message},
    }
    if meta:
        out['meta'] = meta
    return out


def legacy_wrap(payload: Dict[str, Any]) -> Dict[str, Any]:
    """将 envelope 转为旧前端仍使用的 success/authenticated 字段。"""
    if not isinstance(payload, dict):
        return payload
    if 'ok' not in payload:
        return payload
    out = dict(payload.get('data') or {})
    if payload.get('ok'):
        out.setdefault('success', True)
    else:
        err = payload.get('error') or {}
        out['success'] = False
        out['error'] = err.get('message') or '操作失败'
    meta = payload.get('meta') or {}
    for k, v in meta.items():
        if k not in out:
            out[k] = v
    return out
