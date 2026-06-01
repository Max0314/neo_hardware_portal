#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
钉钉工作通知（corpconversation asyncsend_v2）共享工具：
统一 token 获取、可重试错误判断、指数退避重试。
"""
from __future__ import annotations

import json
import ssl
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from server.config import (
    DINGTALK_CONFIG,
    DINGTALK_NOTIFY_MAX_RETRIES,
    DINGTALK_NOTIFY_RETRY_BASE_SEC,
    get_dingtalk_agent_id_numeric,
)
from server.logger import logger


def is_retryable_dingtalk_error(errcode: Any, errmsg: str = '') -> bool:
    """判断钉钉 API 错误是否适合重试（系统繁忙、限流等）。"""
    try:
        code = int(errcode)
    except (TypeError, ValueError):
        code = -1
    if code in (-1, 88, 90018, 90019):
        return True
    msg = (errmsg or '').lower()
    keywords = (
        '系统繁忙', 'busy', 'limit', '限流', 'timeout', '超时',
        'temporarily', '稍后', 'frequency', '频繁',
    )
    return any(k in msg or k in (errmsg or '') for k in keywords)


def get_notify_retry_config() -> Tuple[int, float]:
    """返回 (max_retries, base_delay_sec)。"""
    return DINGTALK_NOTIFY_MAX_RETRIES, DINGTALK_NOTIFY_RETRY_BASE_SEC


def compute_retry_delay(attempt: int, base_sec: float, max_sec: float = 60.0) -> float:
    """指数退避：base * 2^attempt，上限 max_sec。"""
    if attempt < 0:
        attempt = 0
    delay = base_sec * (2 ** attempt)
    return min(delay, max_sec)


def get_dingtalk_access_token_unified() -> Optional[str]:
    """
    统一获取钉钉 access_token（与 main._get_dingtalk_access_token 相同接口）。
    POST https://api.dingtalk.com/v1.0/oauth2/{corp_id}/token
    """
    client_id = DINGTALK_CONFIG.get('client_id', '')
    client_secret = DINGTALK_CONFIG.get('client_secret', '')
    corp_id = DINGTALK_CONFIG.get('corp_id', '')

    if not client_id or not client_secret:
        logger.error('钉钉配置不完整，无法获取 access_token')
        return None
    if not corp_id:
        logger.error('钉钉 corp_id 未配置，无法获取 access_token')
        return None

    url = f'https://api.dingtalk.com/v1.0/oauth2/{corp_id}/token'
    payload = {
        'client_id': client_id,
        'client_secret': client_secret,
        'grant_type': 'client_credentials',
    }
    headers = {
        'Content-Type': 'application/json',
        'Host': 'api.dingtalk.com',
    }

    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    try:
        request_data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(url, data=request_data, headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=30, context=ssl_context) as response:
            text = response.read().decode('utf-8')
            if response.status != 200:
                logger.error(f'获取 access_token 失败，HTTP {response.status}: {text[:200]}')
                return None
            result = json.loads(text)
            token = result.get('access_token')
            if token:
                return token
            err = result.get('error_description') or result.get('message') or result.get('error') or '未知错误'
            logger.error(f'获取 access_token 失败: {err}')
            return None
    except Exception as e:
        logger.error(f'获取 access_token 异常: {e}', exc_info=True)
        return None


def _post_asyncsend_v2(
    access_token: str,
    request_body: Dict[str, Any],
    timeout: int = 30,
) -> Tuple[bool, Optional[int], str, Optional[Dict[str, Any]]]:
    """
    单次调用 asyncsend_v2。
    Returns: (ok, errcode, errmsg, full_response)
    """
    api_url = (
        f'https://oapi.dingtalk.com/topapi/message/corpconversation/asyncsend_v2'
        f'?access_token={access_token}'
    )
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    try:
        request_data = json.dumps(request_body, ensure_ascii=False).encode('utf-8')
        req = urllib.request.Request(
            api_url,
            data=request_data,
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=timeout, context=ssl_context) as response:
            response_data = json.loads(response.read().decode('utf-8'))
            if response.status != 200:
                return False, -1, f'HTTP {response.status}', response_data
            errcode = response_data.get('errcode', -1)
            errmsg = response_data.get('errmsg', '未知错误')
            if errcode == 0:
                return True, 0, '', response_data
            return False, errcode, errmsg, response_data
    except urllib.error.HTTPError as e:
        error_body = ''
        try:
            if e.fp:
                error_body = e.read().decode('utf-8')
        except Exception:
            pass
        return False, -1, f'HTTP {e.code}: {error_body[:200] if error_body else str(e)}', None
    except urllib.error.URLError as e:
        return False, -1, f'网络错误: {e}', None
    except Exception as e:
        return False, -1, str(e), None


def send_corpconversation_batch_with_retry(
    access_token: str,
    userid_list: List[str],
    msg_content: Dict[str, Any],
    *,
    max_retries: Optional[int] = None,
    retry_base_sec: Optional[float] = None,
    log_context: str = '',
) -> Tuple[bool, Optional[str]]:
    """
    向一批 userid 发送工作通知（带重试）。
    Returns: (success, error_message)
    """
    if not userid_list:
        return False, 'userid_list 为空'

    cfg_retries, cfg_base = get_notify_retry_config()
    max_retries = max_retries if max_retries is not None else cfg_retries
    retry_base_sec = retry_base_sec if retry_base_sec is not None else cfg_base

    valid_userids = [str(u).strip() for u in userid_list if u and str(u).strip()]
    if not valid_userids:
        return False, '没有有效的 userid'

    request_body = {
        'agent_id': get_dingtalk_agent_id_numeric(),
        'userid_list': ','.join(valid_userids),
        'msg': msg_content,
    }

    last_error = None
    for attempt in range(max_retries):
        ok, errcode, errmsg, _ = _post_asyncsend_v2(access_token, request_body)
        if ok:
            logger.info(f'成功发送工作通知{log_context}: 本批={len(valid_userids)}人')
            return True, None

        last_error = f'errcode={errcode}, errmsg={errmsg}'
        retryable = is_retryable_dingtalk_error(errcode, errmsg)

        if attempt == 0 or retryable:
            logger.error(f'发送工作通知失败{log_context}: {last_error}')
        else:
            logger.error(f'发送工作通知失败（不可重试）{log_context}: {last_error}')
            return False, last_error

        if attempt < max_retries - 1:
            delay = compute_retry_delay(attempt, retry_base_sec)
            logger.warning(
                f'工作通知将重试{log_context}: 第 {attempt + 2}/{max_retries} 次, '
                f'等待 {delay:.0f}s ({last_error})'
            )
            time.sleep(delay)
        else:
            break

    return False, last_error or '发送工作通知失败'


def send_corpconversation_with_retry(
    access_token: str,
    userids: List[str],
    msg_content: Dict[str, Any],
    *,
    batch_size: int = 100,
    max_retries: Optional[int] = None,
    retry_base_sec: Optional[float] = None,
    log_context: str = '',
) -> Tuple[bool, Optional[str]]:
    """
    分批发送工作通知（每批最多 batch_size 人）。
    Returns: (overall_success, error_message)
    任一批次成功则 overall_success 为 True；全部失败返回首个错误。
    """
    if not userids:
        return False, '未指定接收用户'

    success_count = 0
    errors: List[str] = []

    for i in range(0, len(userids), batch_size):
        batch = userids[i:i + batch_size]
        batch_ctx = f'{log_context} 批次{i // batch_size + 1}' if log_context else f'批次{i // batch_size + 1}'
        ok, err = send_corpconversation_batch_with_retry(
            access_token,
            batch,
            msg_content,
            max_retries=max_retries,
            retry_base_sec=retry_base_sec,
            log_context=batch_ctx,
        )
        if ok:
            success_count += len(batch)
        elif err:
            errors.append(err)

    if success_count > 0:
        if errors:
            return True, f'部分批次失败（已成功 {success_count} 人）: {"; ".join(errors[:3])}'
        return True, None
    if errors:
        return False, errors[0]
    return False, '发送工作通知失败'
