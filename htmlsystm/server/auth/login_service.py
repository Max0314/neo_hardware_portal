# -*- coding: utf-8 -*-
"""登录 / 校验 / 退出 — 签名 Cookie + 轻量 jti 索引。"""
from __future__ import annotations

import secrets
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote

from server import csrf as csrf_mod
from server.auth.session_index import (
    get_user_session_rev,
    is_jti_active,
    register_session,
    revoke_jti,
)
from server.auth.signed_session import (
    AUTH_TOKEN_COOKIE,
    clear_cookie_header,
    cookie_header,
    issue_token,
    payload_to_user,
    verify_token,
)
from server.logger import logger
from server.security import InputValidator
from server.security_manager import get_security_manager
from server.user_manager import STATUS_ACTIVE, STATUS_PENDING, STATUS_REJECTED


def parse_cookies(cookie_header: str) -> Dict[str, str]:
    cookies: Dict[str, str] = {}
    for part in (cookie_header or '').split(';'):
        part = part.strip()
        if '=' in part:
            key, val = part.split('=', 1)
            cookies[key.strip()] = unquote(val.strip())
    return cookies


def is_https_environ(environ: Dict[str, Any]) -> bool:
    return (
        environ.get('HTTP_X_FORWARDED_PROTO') == 'https'
        or environ.get('HTTP_X_FORWARDED_SSL') == 'on'
        or environ.get('HTTP_X_FORWARDED_PROTOCOL') == 'https'
    )


def client_ip_from_environ(environ: Dict[str, Any]) -> str:
    forwarded_for = environ.get('HTTP_X_FORWARDED_FOR', '')
    if forwarded_for:
        return forwarded_for.split(',')[0].strip()
    return environ.get('HTTP_X_REAL_IP') or environ.get('REMOTE_ADDR', '0.0.0.0')


def resolve_user_from_cookies(
    cookie_header: str,
    *,
    lite: bool = False,
    skip_session_enrich: bool = False,
) -> Optional[Dict[str, Any]]:
    cookies = parse_cookies(cookie_header)
    token = cookies.get(AUTH_TOKEN_COOKIE)
    if not token:
        return None

    payload = verify_token(token)
    if not payload:
        return None

    jti = payload.get('jti')
    if not is_jti_active(jti):
        return None

    uid = int(payload.get('uid') or 0)
    token_rev = int(payload.get('rev') or 0)

    if lite and skip_session_enrich:
        return payload_to_user(payload)

    db_rev = get_user_session_rev(uid)
    if db_rev != token_rev:
        return None

    user = payload_to_user(payload)
    status = user.get('status')
    if status != STATUS_ACTIVE:
        return None

    if skip_session_enrich:
        return user

    try:
        from server.neo_user_key import enrich_session_user_inplace
        from server.neo_user_key import get_shared_user_manager
        from server.main import sessions, sessions_lock

        user_manager = get_shared_user_manager()
        enrich_session_user_inplace(
            user, jti, user_manager, sessions, sessions_lock
        )
    except Exception as exc:
        logger.debug('session enrich 跳过: %s', exc)
    return user


def perform_login(
    *,
    username: str,
    password: str,
    captcha_token: str,
    captcha_code: str,
    client_ip: str,
    secure: bool,
) -> Tuple[bool, Dict[str, Any], List[str]]:
    """返回 (success, json_body, set_cookie_headers)。"""
    from server.user_manager import UserManager

    security_mgr = get_security_manager()
    set_cookies: List[str] = []

    is_blocked, block_reason = security_mgr.is_ip_blocked(client_ip)
    if is_blocked:
        return False, {'success': False, 'error': block_reason or 'IP已被封禁'}, set_cookies

    failed_count_before = security_mgr.get_failed_attempts_count(client_ip)
    requires_captcha = security_mgr.requires_captcha(client_ip)

    if requires_captcha:
        if not captcha_token or not captcha_code:
            logger.warning(
                '登录失败: 需要验证码但未提供 - IP=%s, 用户名=%s',
                client_ip,
                username,
            )
            return False, {
                'success': False,
                'error': '登录失败次数过多，请输入验证码',
                'requires_captcha': True,
            }, set_cookies
        from server.captcha import get_captcha_manager

        captcha_mgr = get_captcha_manager()
        if not captcha_mgr.verify_captcha(captcha_token, captcha_code):
            security_mgr.record_failed_login_async(client_ip, username)
            return False, {
                'success': False,
                'error': '验证码错误',
                'requires_captcha': True,
            }, set_cookies

    username_valid, username_error = InputValidator.validate_username(username)
    if not username_valid:
        security_mgr.record_failed_login_async(client_ip, username)
        return False, {'success': False, 'error': username_error}, set_cookies

    password_valid, password_error = InputValidator.validate_password(
        password, check_strength=False
    )
    if not password_valid:
        security_mgr.record_failed_login_async(client_ip, username)
        return False, {'success': False, 'error': password_error}, set_cookies

    if not username or not password:
        return False, {'success': False, 'error': '请输入用户名和密码'}, set_cookies

    logger.info(
        '登录尝试: 用户名=%s, IP=%s, 密码长度=%s',
        username,
        client_ip,
        len(password),
    )

    user_manager = UserManager()
    user = user_manager.authenticate_user_for_login(username, password)
    if not user:
        requires_captcha_bool = (
            failed_count_before >= 2 or security_mgr.requires_captcha(client_ip)
        )
        security_mgr.record_failed_login_async(client_ip, username)
        error_msg = '用户名或密码错误'
        if requires_captcha_bool:
            error_msg = '登录失败次数过多，请输入验证码'
        return False, {
            'success': False,
            'error': error_msg,
            'requires_captcha': requires_captcha_bool,
            'failed_attempts': failed_count_before + 1,
        }, set_cookies

    try:
        security_mgr.record_successful_login(client_ip)
    except Exception as exc:
        logger.warning('清除登录失败记录跳过: %s', exc)

    status = user.get('status')
    if status != STATUS_ACTIVE:
        if status == STATUS_PENDING:
            error = '账号正在审批，审批通过后即可登录'
        elif status == STATUS_REJECTED:
            error = '账号申请已被拒绝，请联系管理组'
        else:
            error = '账号不可用'
        return False, {'success': False, 'error': error}, set_cookies

    session_user = {
        'id': user['id'],
        'username': user['username'],
        'name': user['name'],
        'roles': user.get('roles', []),
        'role': user.get('role'),
        'department': user.get('department'),
        'job_position': user.get('job_position', ''),
        'status': user.get('status'),
        'userid': user.get('userid', ''),
        'unionid': user.get('unionid', ''),
    }

    uid = int(session_user['id'])

    try:
        body, set_cookies = issue_session_for_user(session_user, secure=secure)
    except Exception as exc:
        logger.error('注册会话索引失败: %s', exc, exc_info=True)
        return False, {
            'success': False,
            'error': '会话服务繁忙，请稍后重试',
        }, set_cookies

    logger.info(
        '登录成功: 用户名=%s, 用户ID=%s',
        username,
        uid,
    )

    return True, body, set_cookies


def issue_session_for_user(session_user: Dict[str, Any], *, secure: bool) -> Tuple[Dict[str, Any], List[str]]:
    """已验证用户直接签发签名 Cookie（钉钉免登等）。"""
    uid = int(session_user['id'])
    session_rev = get_user_session_rev(uid)
    jti = secrets.token_urlsafe(24)
    register_session(uid, jti)
    token = issue_token(session_user, jti, session_rev)
    csrf_tok = csrf_mod.new_token()
    set_cookies = [
        cookie_header(token, secure=secure),
        csrf_mod.cookie_header_value(csrf_tok, secure=secure),
        'session_id=; Path=/; HttpOnly; Max-Age=0',
    ]
    return {
        'success': True,
        'user': session_user,
        'csrf_token': csrf_tok,
    }, set_cookies


def clear_auth_cookie_headers(*, secure: bool) -> List[str]:
    return [
        clear_cookie_header(secure=secure),
        'session_id=; Path=/; HttpOnly; Max-Age=0',
    ]


def perform_logout(cookie_header: str, *, secure: bool) -> Tuple[Dict[str, Any], List[str]]:
    cookies = parse_cookies(cookie_header)
    token = cookies.get(AUTH_TOKEN_COOKIE)
    username_logged = 'unknown'
    if token:
        payload = verify_token(token)
        if payload:
            username_logged = payload.get('username') or 'unknown'
            revoke_jti(payload.get('jti') or '')

    logger.info('用户退出登录: 用户名=%s', username_logged)
    clear_cookies = [
        clear_cookie_header(secure=secure),
        'session_id=; Path=/; HttpOnly; Max-Age=0',
        f'{csrf_mod.CSRF_COOKIE_NAME}=; Path=/; Max-Age=0',
    ]
    return {'success': True, 'message': '已退出登录'}, clear_cookies
