# -*- coding: utf-8 -*-
"""HTTP 安全响应头、CORS 与统一错误响应。"""
import os
import traceback
from typing import Any, Dict, Optional

from server.logger import logger

def _normalize_public_base_url(raw: str) -> str:
    u = (raw or '').strip().rstrip('/')
    if u.upper().startswith('HTTPS://'):
        return 'https://' + u[8:]
    if u.upper().startswith('HTTP://'):
        return 'http://' + u[7:]
    return u


PUBLIC_BASE_URL = _normalize_public_base_url(os.getenv('PUBLIC_BASE_URL') or '')

# htmlsystm 页面（含钉钉、Font Awesome）
CSP_DEFAULT = (
    "default-src 'self'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'; "
    "object-src 'none'; "
    "script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdnjs.cloudflare.com; "
    "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com data:; "
    "img-src 'self' data: https: blob:; "
    "media-src 'self' data: blob:; "
    "connect-src 'self'; "
)

# NEO SPA：资源自托管于 /neo/vendor；WebSocket；bom_tool 同源 iframe
CSP_NEO = (
    "default-src 'self'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'self'; "
    "object-src 'none'; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
    "style-src 'self' 'unsafe-inline'; "
    "font-src 'self' data:; "
    "img-src 'self' data: https: blob:; "
    "connect-src 'self' ws: wss:; "
)

# bom_tool / systm_tool 静态页（可被 NEO iframe 嵌入，仅同源脚本）
CSP_BOM_TOOL = (
    "default-src 'self'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'self'; "
    "object-src 'none'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "font-src 'self' data:; "
    "img-src 'self' data: blob:; "
    "connect-src 'self'; "
)

PERMISSIONS_POLICY = (
    "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
    "magnetometer=(), microphone=(), payment=(), usb=()"
)


def _allowed_origins() -> set:
    origins = set()
    if PUBLIC_BASE_URL:
        origins.add(PUBLIC_BASE_URL)
        if PUBLIC_BASE_URL.startswith('https://'):
            origins.add('http://' + PUBLIC_BASE_URL[8:])
        elif PUBLIC_BASE_URL.startswith('http://'):
            origins.add('https://' + PUBLIC_BASE_URL[7:])
    return origins


def _is_neo_embeddable_path(path: str) -> bool:
    p = path or ''
    if p.startswith('/neo') or p.startswith('/ws'):
        return True
    if p.startswith('/bom_tool') or p.startswith('/systm_tool'):
        return True
    if p.startswith('/vendor/'):
        return True
    return False


def pick_csp_profile(path: str) -> str:
    p = path or ''
    if p.startswith('/bom_tool') or p.startswith('/systm_tool'):
        return CSP_BOM_TOOL
    if p.startswith('/neo') or p.startswith('/ws') or p.startswith('/vendor/'):
        return CSP_NEO
    return CSP_DEFAULT


def pick_frame_options(path: str) -> Optional[str]:
    """NEO / bom_tool 允许同源 iframe；其余页面禁止被嵌入。"""
    if _is_neo_embeddable_path(path):
        return 'SAMEORIGIN'
    return 'DENY'


def apply_security_headers(handler, *, csp_profile: Optional[str] = None) -> None:
    """向当前响应追加安全头（需在 end_headers 之前调用）。"""
    path = getattr(handler, 'path', '') or ''
    csp = csp_profile or pick_csp_profile(path)
    handler.send_header('X-Content-Type-Options', 'nosniff')
    handler.send_header('X-Frame-Options', pick_frame_options(path))
    handler.send_header('Referrer-Policy', 'strict-origin-when-cross-origin')
    handler.send_header('Permissions-Policy', PERMISSIONS_POLICY)
    handler.send_header('Content-Security-Policy', csp)
    proto = (
        handler.headers.get('X-Forwarded-Proto') == 'https'
        or handler.headers.get('X-Forwarded-Ssl') == 'on'
    )
    if proto:
        handler.send_header(
            'Strict-Transport-Security',
            'max-age=31536000; includeSubDomains',
        )


def apply_security_headers_wsgi(headers: list, environ: dict) -> list:
    """为 WSGI 响应头列表追加安全头。"""
    path = (environ.get('PATH_INFO') or '') or ''
    csp = pick_csp_profile(path)
    out = list(headers)
    out.append(('X-Content-Type-Options', 'nosniff'))
    out.append(('X-Frame-Options', pick_frame_options(path)))
    out.append(('Referrer-Policy', 'strict-origin-when-cross-origin'))
    out.append(('Permissions-Policy', PERMISSIONS_POLICY))
    out.append(('Content-Security-Policy', csp))
    proto = (environ.get('HTTP_X_FORWARDED_PROTO') or '').split(',')[0].strip()
    if proto == 'https' or environ.get('HTTP_X_FORWARDED_SSL') == 'on':
        out.append(('Strict-Transport-Security', 'max-age=31536000; includeSubDomains'))
    return out


def apply_cors_wsgi(headers: list, environ: dict) -> list:
    """WSGI 版 CORS 白名单。"""
    origin = (environ.get('HTTP_ORIGIN') or '').strip()
    if not origin:
        return headers
    allowed = _allowed_origins()
    host = (environ.get('HTTP_HOST') or '').strip()
    if host:
        scheme = (environ.get('HTTP_X_FORWARDED_PROTO') or 'http').split(',')[0].strip()
        allowed.add(f'{scheme}://{host}')
    if origin in allowed:
        out = list(headers)
        out.append(('Access-Control-Allow-Origin', origin))
        out.append(('Vary', 'Origin'))
        out.append(('Access-Control-Allow-Credentials', 'true'))
        out.append(('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS'))
        out.append(('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-CSRF-Token'))
        return out
    return headers


def apply_cors(handler) -> None:
    """同源或 PUBLIC_BASE_URL 白名单；不再使用 *。"""
    origin = (handler.headers.get('Origin') or '').strip()
    if not origin:
        return
    allowed = _allowed_origins()
    host = (handler.headers.get('Host') or '').strip()
    if host:
        scheme = (handler.headers.get('X-Forwarded-Proto') or 'http').split(',')[0].strip()
        allowed.add(f'{scheme}://{host}')
    if origin in allowed:
        handler.send_header('Access-Control-Allow-Origin', origin)
        handler.send_header('Vary', 'Origin')
        handler.send_header('Access-Control-Allow-Credentials', 'true')
        handler.send_header(
            'Access-Control-Allow-Methods',
            'GET, POST, PUT, DELETE, OPTIONS',
        )
        handler.send_header(
            'Access-Control-Allow-Headers',
            'Content-Type, Authorization, X-CSRF-Token',
        )


def client_error_message(exc: Exception, *, public_hint: Optional[str] = None) -> str:
    """返回可安全展示给客户端的错误文案。"""
    if public_hint:
        return public_hint
    return '服务器内部错误'


def log_server_error(context: str, exc: Exception) -> None:
    logger.error('%s: %s', context, exc, exc_info=True)


def safe_error_payload(public_hint: Optional[str] = None) -> Dict[str, Any]:
    return {'success': False, 'error': public_hint or '服务器内部错误'}


def send_safe_http_error(handler, code: int, public_hint: Optional[str] = None) -> None:
    """发送简短 HTML/文本错误，不含路径与堆栈。"""
    try:
        msg = public_hint or '请求处理失败'
        body = f'<!DOCTYPE html><html><head><meta charset="utf-8"><title>{code}</title></head>'
        body += f'<body><p>{msg}</p></body></html>'
        data = body.encode('utf-8')
        handler.send_response(code)
        handler.send_header('Content-Type', 'text/html; charset=utf-8')
        handler.send_header('Content-Length', str(len(data)))
        apply_security_headers(handler)
        handler.end_headers()
        handler.wfile.write(data)
    except Exception:
        pass
