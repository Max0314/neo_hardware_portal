# -*- coding: utf-8 -*-
"""HMAC 签名会话 Cookie（无 sessions 大表依赖）。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any, Dict, Optional

AUTH_TOKEN_COOKIE = 'auth_token'
TOKEN_TTL_SEC = 7 * 24 * 60 * 60  # 7 天，与旧 Max-Age 一致


def _secret() -> bytes:
    raw = (os.getenv('AUTH_SESSION_SECRET') or '').strip()
    if not raw:
        raw = (os.getenv('NEO_INTERNAL_SECRET') or '').strip()
    if not raw:
        raw = 'dev-insecure-change-me'
    return raw.encode('utf-8')


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode('ascii').rstrip('=')


def _b64url_decode(data: str) -> bytes:
    pad = '=' * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def issue_token(user: Dict[str, Any], jti: str, session_rev: int) -> str:
    now = int(time.time())
    payload = {
        'uid': int(user.get('id') or 0),
        'jti': jti,
        'rev': int(session_rev or 0),
        'username': user.get('username') or '',
        'name': user.get('name') or '',
        'roles': user.get('roles') or [],
        'role': user.get('role'),
        'department': user.get('department') or '',
        'job_position': user.get('job_position') or '',
        'status': user.get('status') or 'active',
        'userid': user.get('userid') or user.get('username') or '',
        'unionid': user.get('unionid') or '',
        'iat': now,
        'exp': now + TOKEN_TTL_SEC,
    }
    body = _b64url_encode(
        json.dumps(payload, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    )
    sig = hmac.new(_secret(), body.encode('ascii'), hashlib.sha256).hexdigest()
    return body + '.' + sig


def verify_token(token: str) -> Optional[Dict[str, Any]]:
    if not token or '.' not in token:
        return None
    body, sig = token.rsplit('.', 1)
    expected = hmac.new(_secret(), body.encode('ascii'), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return None
    try:
        payload = json.loads(_b64url_decode(body).decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return None
    exp = int(payload.get('exp') or 0)
    if exp and int(time.time()) > exp:
        return None
    if not payload.get('jti') or not payload.get('uid'):
        return None
    return payload


def cookie_header(token: str, *, secure: bool) -> str:
    flags = (
        f'{AUTH_TOKEN_COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; '
        f'Max-Age={TOKEN_TTL_SEC}'
    )
    if secure:
        flags += '; Secure'
    return flags


def clear_cookie_header(*, secure: bool) -> str:
    flags = f'{AUTH_TOKEN_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0'
    if secure:
        flags += '; Secure'
    return flags


def payload_to_user(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        'id': payload.get('uid'),
        'username': payload.get('username'),
        'name': payload.get('name'),
        'roles': payload.get('roles') or [],
        'role': payload.get('role'),
        'department': payload.get('department'),
        'job_position': payload.get('job_position'),
        'status': payload.get('status'),
        'userid': payload.get('userid'),
        'unionid': payload.get('unionid'),
        '_session_jti': payload.get('jti'),
        '_session_rev': payload.get('rev'),
    }
