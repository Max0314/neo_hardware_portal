# -*- coding: utf-8 -*-
"""钉钉鉴权登录：企业内部免登 + 网页 OAuth，复用 hardware 现有会话体系。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import os
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request as UrlRequest, urlopen

from server import csrf as csrf_mod
from server.auth.login_service import issue_session_for_user
from server.config import DINGTALK_CONFIG, PUBLIC_BASE_URL, check_dingtalk_config
from server.logger import logger
from server.user_manager import STATUS_ACTIVE, UserManager

_ACCESS_TOKEN_CACHE = {"token": "", "expire_at": 0.0}


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str)


def _http_json(
    url: str,
    method: str = "GET",
    params: Optional[Dict[str, Any]] = None,
    payload: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = 12,
) -> Dict[str, Any]:
    final_url = url
    if params:
        query = urlencode({k: "" if v is None else str(v) for k, v in params.items()})
        final_url = "%s%s%s" % (url, "&" if "?" in url else "?", query)

    body = None
    final_headers = {"Content-Type": "application/json"}
    if headers:
        final_headers.update(headers)
    if payload is not None:
        body = _json_dumps(payload).encode("utf-8")

    req = UrlRequest(final_url, data=body, headers=final_headers, method=method.upper())
    try:
        with urlopen(req, timeout=timeout) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            raw = resp.read().decode(charset, errors="replace")
    except HTTPError as exc:
        raw = ""
        try:
            raw = exc.read().decode("utf-8", errors="replace")
        except Exception:
            raw = str(exc)
        raise RuntimeError("DingTalk HTTP %s: %s" % (exc.code, raw[:300]))
    except URLError as exc:
        raise RuntimeError("DingTalk network error: %s" % exc)

    try:
        parsed = json.loads(raw or "{}")
    except ValueError:
        raise RuntimeError("DingTalk invalid JSON response: %s" % raw[:200])
    if not isinstance(parsed, dict):
        raise RuntimeError("DingTalk unexpected response type")
    return parsed


def _auth_secret() -> bytes:
    raw = (
        os.getenv("AUTH_SESSION_SECRET")
        or os.getenv("NEO_INTERNAL_SECRET")
        or DINGTALK_CONFIG.get("client_secret")
        or ""
    ).strip()
    if not raw:
        raw = "dev-insecure-change-me"
    return raw.encode("utf-8")


def _get_access_token() -> str:
    now = time.time()
    if _ACCESS_TOKEN_CACHE["token"] and now < float(_ACCESS_TOKEN_CACHE["expire_at"]):
        return str(_ACCESS_TOKEN_CACHE["token"])

    client_id = _normalize_text(DINGTALK_CONFIG.get("client_id"))
    client_secret = _normalize_text(DINGTALK_CONFIG.get("client_secret"))
    if not client_id or not client_secret:
        raise RuntimeError("DingTalk client_id/client_secret not configured")

    payload = _http_json(
        DINGTALK_CONFIG.get("gettoken_url") or "https://oapi.dingtalk.com/gettoken",
        params={"appkey": client_id, "appsecret": client_secret},
    )
    if int(payload.get("errcode", -1)) != 0:
        raise RuntimeError(str(payload.get("errmsg") or "get access token failed"))
    token = _normalize_text(payload.get("access_token"))
    if not token:
        raise RuntimeError("DingTalk access_token missing")

    _ACCESS_TOKEN_CACHE["token"] = token
    _ACCESS_TOKEN_CACHE["expire_at"] = now + max(300, int(payload.get("expires_in", 7200)) - 120)
    return token


def _exchange_inapp_auth_code(code: str) -> Dict[str, Any]:
    access_token = _get_access_token()
    payload = _http_json(
        "%s?access_token=%s"
        % (
            DINGTALK_CONFIG.get("userinfo_url") or "https://oapi.dingtalk.com/topapi/v2/user/getuserinfo",
            access_token,
        ),
        method="POST",
        payload={"code": code},
    )
    if int(payload.get("errcode", -1)) != 0:
        raise RuntimeError(str(payload.get("errmsg") or "exchange auth code failed"))
    result = payload.get("result")
    if not isinstance(result, dict):
        raise RuntimeError("DingTalk auth code result missing")
    return result


def _get_user_detail(userid: str) -> Dict[str, Any]:
    access_token = _get_access_token()
    payload = _http_json(
        "%s?access_token=%s"
        % (
            DINGTALK_CONFIG.get("user_detail_url") or "https://oapi.dingtalk.com/topapi/v2/user/get",
            access_token,
        ),
        method="POST",
        payload={"userid": userid},
    )
    if int(payload.get("errcode", -1)) != 0:
        raise RuntimeError(str(payload.get("errmsg") or "get user detail failed"))
    result = payload.get("result")
    if not isinstance(result, dict):
        raise RuntimeError("DingTalk user detail missing")
    return result


def _get_userid_by_unionid(unionid: str) -> str:
    access_token = _get_access_token()
    payload = _http_json(
        "https://oapi.dingtalk.com/topapi/user/getbyunionid?access_token=%s" % access_token,
        method="POST",
        payload={"unionid": unionid},
    )
    if int(payload.get("errcode", -1)) != 0:
        raise RuntimeError(str(payload.get("errmsg") or "get userid by unionid failed"))
    result = payload.get("result") or {}
    if not isinstance(result, dict):
        raise RuntimeError("DingTalk getbyunionid result missing")
    userid = _normalize_text(result.get("userid"))
    if not userid:
        raise RuntimeError("DingTalk userid missing in getbyunionid response")
    return userid


def _exchange_web_login_code(code: str) -> Dict[str, Any]:
    client_id = _normalize_text(DINGTALK_CONFIG.get("client_id"))
    client_secret = _normalize_text(DINGTALK_CONFIG.get("client_secret"))
    if not client_id or not client_secret:
        raise RuntimeError("DingTalk OAuth client_id/client_secret not configured")

    payload = _http_json(
        "https://api.dingtalk.com/v1.0/oauth2/userAccessToken",
        method="POST",
        payload={
            "clientId": client_id,
            "clientSecret": client_secret,
            "code": code,
            "grantType": "authorization_code",
        },
    )
    if payload.get("code") and payload.get("message"):
        raise RuntimeError(str(payload.get("message") or "exchange OAuth code failed"))
    return payload


def _get_oauth_user_detail(user_access_token: str) -> Dict[str, Any]:
    payload = _http_json(
        "https://api.dingtalk.com/v1.0/contact/users/me",
        method="GET",
        headers={"x-acs-dingtalk-access-token": user_access_token},
    )
    if payload.get("code") and payload.get("message"):
        raise RuntimeError(str(payload.get("message") or "get OAuth user detail failed"))
    return payload


def _profile_from_dingtalk(detail: Dict[str, Any], userid: str = "", unionid: str = "") -> Dict[str, Any]:
    dept_ids = detail.get("dept_id_list") or detail.get("deptIdList") or detail.get("deptIds") or []
    if not isinstance(dept_ids, list):
        dept_ids = []
    profile = dict(detail)
    profile["userid"] = _normalize_text(userid or detail.get("userid") or detail.get("userId") or detail.get("staffId"))
    profile["unionid"] = _normalize_text(unionid or detail.get("unionid") or detail.get("unionId"))
    profile["name"] = _normalize_text(detail.get("name") or detail.get("nick") or profile["userid"])
    profile["job_number"] = _normalize_text(detail.get("job_number") or detail.get("jobNumber") or detail.get("staffId"))
    profile["title"] = _normalize_text(detail.get("title") or detail.get("job_position"))
    profile["dept_id_list"] = [int(item) for item in dept_ids if str(item).isdigit()]
    return profile


def _public_origin(handler: Any) -> str:
    proto = (
        _normalize_text(handler.headers.get("X-Forwarded-Proto"))
        or ("https" if handler._is_https_request() else "http")
    )
    host = (
        _normalize_text(handler.headers.get("X-Forwarded-Host"))
        or _normalize_text(handler.headers.get("Host"))
        or "localhost"
    )
    return "%s://%s" % (proto, host)


def _configured_prefix() -> str:
    prefix = ""
    try:
        path = urlsplit(PUBLIC_BASE_URL or "").path.rstrip("/")
        if path and path != "/":
            prefix = path
    except Exception:
        prefix = ""
    return prefix


def _request_prefix(handler: Any, return_url: str = "") -> str:
    forwarded = _normalize_text(handler.headers.get("X-Forwarded-Prefix")).rstrip("/")
    if forwarded:
        return forwarded
    configured = _configured_prefix()
    if configured:
        return configured
    try:
        path = urlsplit(return_url or "").path.rstrip("/")
        for marker in ("/login", "/api/auth/dingtalk/callback", "/neo", "/register"):
            idx = path.find(marker)
            if idx > 0:
                return path[:idx].rstrip("/")
    except Exception:
        pass
    return ""


def _build_callback_url(handler: Any, return_url: str = "") -> str:
    prefix = _request_prefix(handler, return_url)
    return "%s%s/api/auth/dingtalk/callback" % (_public_origin(handler), prefix)


def _fallback_return_url(handler: Any) -> str:
    prefix = _request_prefix(handler)
    return "%s%s/" % (_public_origin(handler), prefix)


def _sanitize_return_url(handler: Any, raw_value: str) -> str:
    fallback = _fallback_return_url(handler)
    value = _normalize_text(raw_value)
    if not value:
        return fallback
    try:
        origin = _public_origin(handler)
        parts = urlsplit(value)
        if parts.scheme and parts.netloc:
            if "%s://%s" % (parts.scheme, parts.netloc) != origin:
                return fallback
            safe_path = parts.path or "/"
            return urlunsplit((parts.scheme, parts.netloc, safe_path, parts.query, parts.fragment))
        if value.startswith("//"):
            return fallback
        if value.startswith("/"):
            return origin + value
    except Exception:
        return fallback
    return fallback


def _encode_state(handler: Any, return_url: str) -> str:
    payload = {
        "ts": int(time.time()),
        "return_url": _sanitize_return_url(handler, return_url),
    }
    encoded = base64.urlsafe_b64encode(_json_dumps(payload).encode("utf-8")).decode("ascii").rstrip("=")
    sig = hmac.new(_auth_secret(), encoded.encode("ascii"), hashlib.sha256).hexdigest()
    return "%s.%s" % (encoded, sig)


def _decode_state(state: str, ttl_seconds: int = 600) -> Dict[str, Any]:
    encoded, dot, sig = _normalize_text(state).partition(".")
    if not encoded or not dot or not sig:
        raise RuntimeError("invalid login state")
    expected = hmac.new(_auth_secret(), encoded.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        raise RuntimeError("login state signature mismatch")
    padding = "=" * (-len(encoded) % 4)
    payload = json.loads(base64.urlsafe_b64decode((encoded + padding).encode("ascii")).decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("login state payload invalid")
    ts = int(payload.get("ts") or 0)
    if ts <= 0 or int(time.time()) - ts > ttl_seconds:
        raise RuntimeError("login state expired")
    return payload


def _session_user(user: Dict[str, Any]) -> Dict[str, Any]:
    roles = user.get("roles") or []
    if isinstance(roles, str):
        roles = [r.strip() for r in roles.split(",") if r.strip()]
    return {
        "id": user["id"],
        "username": user.get("username") or "",
        "name": user.get("name") or "",
        "roles": roles,
        "role": user.get("role"),
        "department": user.get("department") or "",
        "job_position": user.get("job_position") or "",
        "status": user.get("status") or STATUS_ACTIVE,
        "userid": user.get("userid") or "",
        "unionid": user.get("unionid") or "",
    }


def _login_profile(profile: Dict[str, Any], secure: bool) -> Tuple[int, Dict[str, Any], List[str]]:
    user_manager = UserManager()
    user = user_manager.upsert_dingtalk_login_user(profile)
    if not user:
        return 500, {"success": False, "code": 500, "error": "用户创建或绑定失败"}, []
    if str(user.get("status") or "").lower() != STATUS_ACTIVE:
        return 403, {"success": False, "code": 403, "error": "账号不可用"}, []

    body, cookies = issue_session_for_user(_session_user(user), secure=secure)
    body.update({"code": 0, "msg": "success"})
    return 200, body, cookies


def get_auth_config(handler: Any) -> Dict[str, Any]:
    config_ok, _ = check_dingtalk_config()
    return {
        "enabled": True,
        "inAppEnabled": bool(config_ok and DINGTALK_CONFIG.get("corp_id") and DINGTALK_CONFIG.get("client_id")),
        "webLoginEnabled": bool(config_ok and DINGTALK_CONFIG.get("client_id")),
        "passwordLoginEnabled": False,
        "corpId": _normalize_text(DINGTALK_CONFIG.get("corp_id")),
        "callbackUrl": _build_callback_url(handler),
    }


def build_auth_config_response(handler: Any) -> Tuple[int, Dict[str, Any]]:
    return 200, {"success": True, "code": 0, "data": get_auth_config(handler)}


def login_with_inapp_code(handler: Any, code: str) -> Tuple[int, Dict[str, Any], List[str]]:
    if not _normalize_text(code):
        return 400, {"success": False, "code": 400, "error": "缺少钉钉授权码"}, []
    config_ok, config_error = check_dingtalk_config()
    if not config_ok:
        logger.warning("钉钉免登配置不完整: %s", config_error)
        return 503, {"success": False, "code": 503, "error": "钉钉配置不完整，请联系管理员"}, []
    try:
        exchange = _exchange_inapp_auth_code(code)
        userid = _normalize_text(exchange.get("userid"))
        unionid = _normalize_text(exchange.get("unionid"))
        if not userid:
            raise RuntimeError("auth code missing userid")
        detail = _get_user_detail(userid)
        merged = dict(exchange)
        merged.update(detail)
        profile = _profile_from_dingtalk(merged, userid=userid, unionid=unionid)
        return _login_profile(profile, secure=handler._is_https_request())
    except Exception as exc:
        logger.warning("钉钉免登失败: %s", exc)
        return 400, {"success": False, "code": 400, "error": "钉钉授权无效或已过期，请重试"}, []


def build_web_login_start_response(handler: Any, return_url: str) -> Tuple[int, Dict[str, Any]]:
    config_ok, config_error = check_dingtalk_config()
    if not config_ok:
        return 503, {"success": False, "code": 503, "error": config_error or "钉钉配置不完整"}
    state = _encode_state(handler, return_url)
    login_url = "https://login.dingtalk.com/oauth2/auth?%s" % urlencode(
        {
            "client_id": _normalize_text(DINGTALK_CONFIG.get("client_id")),
            "response_type": "code",
            "scope": "openid corpid",
            "prompt": "consent",
            "state": state,
            "redirect_uri": _build_callback_url(handler, return_url),
        }
    )
    return 200, {"success": True, "code": 0, "data": {"loginUrl": login_url}}


def _callback_html(success: bool, message: str, return_url: str) -> str:
    title = "钉钉登录成功" if success else "钉钉登录失败"
    safe_message = html.escape(message or "")
    safe_return = json.dumps(return_url or "/", ensure_ascii=False)
    safe_success = "true" if success else "false"
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>%s</title>
  <style>
    body { margin:0; min-height:100vh; display:grid; place-items:center; font-family:"Microsoft YaHei",Arial,sans-serif; background:#f6f8fb; color:#1f2937; }
    .panel { width:min(420px,calc(100vw - 32px)); border-radius:12px; background:#fff; border:1px solid #e5e7eb; box-shadow:0 20px 60px rgba(15,23,42,.12); padding:32px 28px; text-align:center; }
    .badge { width:56px; height:56px; border-radius:16px; margin:0 auto 16px; display:grid; place-items:center; font-size:24px; color:#fff; background:%s; }
    .title { font-size:20px; font-weight:700; margin-bottom:8px; }
    .desc { font-size:14px; color:#64748b; line-height:1.7; }
  </style>
</head>
<body>
  <div class="panel">
    <div class="badge">%s</div>
    <div class="title">%s</div>
    <div class="desc">%s</div>
  </div>
  <script>
    setTimeout(function() {
      if (%s) window.location.replace(%s);
    }, 600);
  </script>
</body>
</html>""" % (
        html.escape(title),
        "linear-gradient(135deg,#0ea5e9,#2563eb)" if success else "linear-gradient(135deg,#f97316,#dc2626)",
        "✓" if success else "!",
        html.escape(title),
        safe_message,
        safe_success,
        safe_return,
    )


def handle_web_login_callback(handler: Any, params: Dict[str, List[str]]) -> Tuple[int, str, List[str]]:
    state = (params.get("state") or [""])[0]
    error = (params.get("error") or [""])[0]
    code = (params.get("code") or [""])[0]
    try:
        state_payload = _decode_state(state)
        return_url = _normalize_text(state_payload.get("return_url")) or _fallback_return_url(handler)
    except Exception as exc:
        logger.warning("钉钉网页登录 state 无效: %s", exc)
        return_url = _fallback_return_url(handler)
        return 400, _callback_html(False, "登录状态校验失败，请重新登录。", return_url), []

    if error:
        return 400, _callback_html(False, "登录失败：%s" % html.escape(error), return_url), []
    if not code:
        return 400, _callback_html(False, "登录失败：钉钉未返回授权码。", return_url), []

    try:
        token_payload = _exchange_web_login_code(code)
        selected_corp_id = _normalize_text(token_payload.get("corpId"))
        configured_corp_id = _normalize_text(DINGTALK_CONFIG.get("corp_id"))
        if selected_corp_id and configured_corp_id and selected_corp_id != configured_corp_id:
            raise RuntimeError("当前选择的组织与系统绑定组织不一致")
        user_access_token = _normalize_text(token_payload.get("accessToken") or token_payload.get("access_token"))
        if not user_access_token:
            raise RuntimeError("DingTalk user access token missing")

        oauth_user = _get_oauth_user_detail(user_access_token)
        unionid = _normalize_text(oauth_user.get("unionId") or oauth_user.get("unionid"))
        userid = _normalize_text(oauth_user.get("userid") or oauth_user.get("userId") or oauth_user.get("staffId"))
        if not userid and unionid:
            userid = _get_userid_by_unionid(unionid)
        if not userid:
            raise RuntimeError("DingTalk OAuth userid missing")

        detail = _get_user_detail(userid)
        merged = dict(oauth_user)
        merged.update(detail)
        profile = _profile_from_dingtalk(merged, userid=userid, unionid=unionid)
        status, body, cookies = _login_profile(profile, secure=handler._is_https_request())
        if status != 200:
            return status, _callback_html(False, body.get("error") or "登录失败", return_url), cookies
        return 200, _callback_html(True, "登录成功，正在返回系统。", return_url), cookies
    except Exception as exc:
        logger.warning("钉钉网页登录回调失败: %s", exc)
        return 400, _callback_html(False, "登录失败：%s" % html.escape(str(exc)), return_url), []
