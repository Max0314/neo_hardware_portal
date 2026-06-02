#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WSGI应用入口 - 完整版
将SimpleHTTPRequestHandler转换为WSGI应用，支持Gunicorn多进程
"""
import os
import sys
import json
import gzip
import hashlib
import time
import io
import threading
import concurrent.futures
from io import BytesIO
from urllib.parse import parse_qs, urlparse, unquote, quote
from typing import Dict, Any, Optional, Tuple, List

# 添加项目根目录到Python路径
_current_file_dir = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(_current_file_dir)
sys.path.insert(0, BASE_DIR)

from server.config import (
    STATIC_DIR, TEMPLATE_DIR, ENABLE_GZIP, ENABLE_CACHE, CACHE_MAX_AGE,
    GZIP_COMPRESSION_LEVEL, CACHE_SIZE, MAX_ATTACHMENT_SIZE, CHUNK_SIZE
)
from server.logger import logger
from server.session_manager import get_session_manager
from server.main import api_cache, LRUCache

# 导入Handler类（但我们需要创建适配器来使用它）
# 由于Handler继承自SimpleHTTPRequestHandler，我们需要创建一个包装器

_LOGIN_DB_TIMEOUT_SEC = float(os.getenv('LOGIN_DB_TIMEOUT_SEC', '8'))
_LOGIN_AUTH_TIMEOUT_SEC = float(os.getenv('LOGIN_AUTH_TIMEOUT_SEC', '12'))


def _public_path_prefix(environ: Optional[Dict[str, Any]] = None) -> str:
    """外部子路径前缀；内部容器路由仍保持 /。"""
    forwarded_prefix = ''
    if environ:
        forwarded_prefix = environ.get('HTTP_X_FORWARDED_PREFIX', '') or ''
    raw = (os.getenv('PUBLIC_PATH_PREFIX') or forwarded_prefix or '').strip()
    if not raw:
        return ''
    raw = raw.split(',')[0].strip().rstrip('/')
    if not raw or raw == '/':
        return ''
    if raw.startswith('//'):
        return ''
    return raw if raw.startswith('/') else f'/{raw}'


def _prefix_public_location(value: str, prefix: str) -> str:
    if not prefix or not value or not value.startswith('/') or value.startswith('//'):
        return value
    if value == prefix or value.startswith(prefix + '/'):
        return value
    return prefix + value


def _prefix_public_redirect_target(value: str, prefix: str) -> str:
    value = (value or '/').strip()
    if not value or not value.startswith('/') or value.startswith('//'):
        return prefix + '/' if prefix else '/'
    return _prefix_public_location(value, prefix) if prefix else value


def _rewrite_cookie_path(cookie: str, prefix: str) -> str:
    if not prefix:
        return cookie
    path = prefix + '/'
    segments = cookie.split(';')
    for idx, segment in enumerate(segments):
        if segment.strip().lower().startswith('path='):
            leading = segment[:len(segment) - len(segment.lstrip())]
            segments[idx] = f'{leading}Path={path}'
            return ';'.join(segments)
    return cookie + f'; Path={path}'


def _rewrite_public_headers(headers: List[Tuple[str, str]], prefix: str) -> List[Tuple[str, str]]:
    if not prefix:
        return headers
    rewritten = []
    for key, value in headers:
        lower = key.lower()
        if lower == 'location':
            value = _prefix_public_location(value, prefix)
        rewritten.append((key, value))
    return rewritten


def _with_public_prefix_headers(environ: Dict[str, Any], start_response):
    prefix = _public_path_prefix(environ)
    if not prefix:
        return start_response

    def prefixed_start_response(status, headers, exc_info=None):
        return start_response(status, _rewrite_public_headers(headers, prefix), exc_info)

    return prefixed_start_response


def _run_with_timeout(seconds: float, fn, *args, **kwargs):
    """避免 MySQL 锁等待导致登录 POST 一直挂起（网关 504）。"""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(fn, *args, **kwargs)
        return fut.result(timeout=seconds)


class WSGIRequestAdapter:
    """
    WSGI请求适配器
    将WSGI环境转换为类似SimpleHTTPRequestHandler的接口
    这样我们可以复用现有的Handler逻辑
    """
    
    def __init__(self, environ: Dict[str, Any], start_response):
        self.environ = environ
        self.start_response = start_response
        self.method = environ.get('REQUEST_METHOD', 'GET')
        self.path = environ.get('PATH_INFO', '/')
        self.query_string = environ.get('QUERY_STRING', '')
        self.headers = self._parse_headers(environ)
        self.rfile = self._create_rfile(environ)
        self.wfile = BytesIO()  # 用于捕获响应
        self.response_status = None
        self.response_headers = []
        self.response_sent = False
        self.response_body = None  # 存储响应体
        self.headers_ended = False  # 标记响应头是否已结束
        
        # 解析查询参数
        self.query_params = parse_qs(self.query_string)
        
        # 获取客户端地址（用于审计日志）
        self.client_address = self._get_client_address(environ)
        
        # 管理器实例（每个进程一个）
        self._init_managers()
    
    def _init_managers(self):
        """初始化管理器实例"""
        from server.user_manager import UserManager
        from server.announcement_manager import AnnouncementManager
        from server.quick_link_manager import QuickLinkManager
        from server.department_manager import DepartmentManager
        from server.todo_manager import TodoManager
        
        # 使用类级别的单例（每个进程一个实例）
        if not hasattr(WSGIRequestAdapter, '_managers'):
            WSGIRequestAdapter._managers = {
                'user_manager': UserManager(),
                'announcement_mgr': AnnouncementManager(base_dir=BASE_DIR),
                'quick_link_mgr': QuickLinkManager(),
                'department_mgr': DepartmentManager(),
                'todo_mgr': TodoManager()
            }
        
        self.user_manager = WSGIRequestAdapter._managers['user_manager']
        self.announcement_mgr = WSGIRequestAdapter._managers['announcement_mgr']
        self.quick_link_mgr = WSGIRequestAdapter._managers['quick_link_mgr']
        self.department_mgr = WSGIRequestAdapter._managers['department_mgr']
        self.todo_mgr = WSGIRequestAdapter._managers['todo_mgr']
    
    def _parse_headers(self, environ: Dict[str, Any]) -> Dict[str, str]:
        """解析HTTP头"""
        headers = {}
        for key, value in environ.items():
            if key.startswith('HTTP_'):
                # 转换 HTTP_X_FORWARDED_FOR -> X-Forwarded-For
                header_name = key[5:].replace('_', '-').title()
                headers[header_name] = value
            elif key in ('CONTENT_TYPE', 'CONTENT_LENGTH'):
                headers[key.replace('_', '-').title()] = value
        return headers
    
    def _create_rfile(self, environ: Dict[str, Any]) -> BytesIO:
        """创建请求体文件对象"""
        try:
            content_length = int(environ.get('CONTENT_LENGTH') or 0)
        except (TypeError, ValueError):
            content_length = 0
        wsgi_input = environ.get('wsgi.input')
        if not wsgi_input:
            return BytesIO()
        try:
            if content_length > 0:
                return BytesIO(wsgi_input.read(content_length))
            return BytesIO(wsgi_input.read())
        except Exception as e:
            logger.warning(f"读取请求体失败: {e}")
            return BytesIO()
    
    def _get_client_address(self, environ: Dict[str, Any]) -> tuple:
        """获取客户端地址（兼容SimpleHTTPRequestHandler的client_address格式）"""
        # 优先使用 X-Forwarded-For（如果存在代理）
        forwarded_for = environ.get('HTTP_X_FORWARDED_FOR', '')
        if forwarded_for:
            # X-Forwarded-For 可能包含多个IP，取第一个
            client_ip = forwarded_for.split(',')[0].strip()
        else:
            # 否则使用 REMOTE_ADDR
            client_ip = environ.get('REMOTE_ADDR', '0.0.0.0')
        
        # 返回元组格式 (ip, port)，兼容 SimpleHTTPRequestHandler.client_address
        # 在WSGI环境中，我们通常没有端口信息，所以使用0
        return (client_ip, 0)
    
    def get(self, key: str, default: str = '') -> str:
        """获取header值（兼容Handler的headers.get）"""
        return self.headers.get(key, default)
    
    def send_response(self, code: int, message: str = None):
        """发送响应状态（捕获）"""
        self.response_status = code
        if message:
            self.response_status_line = f"{code} {message}"
        else:
            self.response_status_line = f"{code} OK" if code == 200 else f"{code} Error"
    
    def send_header(self, key: str, value: str):
        """发送响应头（捕获）"""
        self.response_headers.append((key, value))
    
    def end_headers(self):
        """结束响应头（在WSGI中，当end_headers被调用时，准备发送响应）"""
        self.headers_ended = True
        
        # 如果已经发送了响应，直接返回
        if self.response_sent:
            return
        
        # 确保有响应状态
        if not self.response_status:
            self.response_status = 200
            self.response_status_line = "200 OK"
        
        # 如果是重定向（302/301），立即调用start_response（重定向不需要响应体）
        if self.response_status in (302, 301):
            status_line = self.response_status_line
            has_content_length = any(h[0].lower() == 'content-length' for h in self.response_headers)
            if not has_content_length:
                self.response_headers.append(('Content-Length', '0'))
            self.start_response(status_line, self.response_headers)
            self.response_sent = True
            self.response_body = [b'']
        # 注意：对于其他情况，start_response会在wfile.write()之后或send_json_response中调用
    
    def get_current_user(self, skip_session_enrich: bool = False):
        """获取当前用户（签名 Cookie + jti 索引）。"""
        cookie_header = self.headers.get('Cookie', '')
        from server.auth.login_service import resolve_user_from_cookies

        return resolve_user_from_cookies(
            cookie_header,
            lite=skip_session_enrich,
            skip_session_enrich=skip_session_enrich,
        )
    
    def _parse_cookies(self) -> Dict[str, str]:
        """解析Cookie"""
        cookies = {}
        cookie_header = self.headers.get('Cookie', '')
        if cookie_header:
            for cookie in cookie_header.split(';'):
                cookie = cookie.strip()
                if '=' in cookie:
                    key, value = cookie.split('=', 1)
                    cookies[key.strip()] = unquote(value.strip())
        return cookies
    
    def send_json_response(self, data: Any, status: int = 200, set_cookies=None):
        """发送JSON响应（转换为WSGI格式，兼容钉钉浏览器）"""
        try:
            from server.security_http import apply_cors_wsgi, apply_security_headers_wsgi
            # 序列化JSON（确保使用UTF-8编码）
            try:
                response_data = json.dumps(data, ensure_ascii=False).encode('utf-8')
            except (TypeError, ValueError) as e:
                logger.error(f"JSON序列化失败: {e}, data={data}")
                # 如果序列化失败，返回错误信息
                error_data = {'success': False, 'error': '数据序列化失败'}
                response_data = json.dumps(error_data, ensure_ascii=False).encode('utf-8')
                status = 500
            
            # 检查是否应该压缩
            # 钉钉浏览器可能对压缩有特殊要求，小数据不压缩以确保兼容性
            should_compress = self._should_compress('application/json')
            if should_compress and len(response_data) > 2048:  # 大于2KB才压缩
                try:
                    compressed_data = self._compress_response(response_data)
                    if len(compressed_data) < len(response_data):
                        response_data = compressed_data
                        content_encoding = 'gzip'
                    else:
                        content_encoding = None
                except Exception as e:
                    logger.warning(f"压缩失败，使用未压缩数据: {e}")
                    content_encoding = None
            else:
                content_encoding = None
            
            headers = [
                ('Content-Type', 'application/json; charset=utf-8'),
                ('Content-Length', str(len(response_data))),
                ('Cache-Control', 'no-cache, no-store, must-revalidate'),
                ('Pragma', 'no-cache'),
                ('Expires', '0'),
            ]
            if set_cookies:
                for cookie in set_cookies:
                    headers.append(('Set-Cookie', cookie))
            if content_encoding:
                headers.append(('Content-Encoding', content_encoding))
            headers = apply_security_headers_wsgi(headers, self.environ)
            headers = apply_cors_wsgi(headers, self.environ)
            
            # 发送响应
            # 构建正确的状态行（WSGI格式：状态码 状态文本）
            if status == 200:
                status_line = "200 OK"
            elif status == 201:
                status_line = "201 Created"
            elif status == 204:
                status_line = "204 No Content"
            elif status == 302:
                status_line = "302 Found"
            elif status == 400:
                status_line = "400 Bad Request"
            elif status == 401:
                status_line = "401 Unauthorized"
            elif status == 403:
                status_line = "403 Forbidden"
            elif status == 404:
                status_line = "404 Not Found"
            elif status == 500:
                status_line = "500 Internal Server Error"
            else:
                status_line = f"{status} OK" if status < 400 else f"{status} Error"
            
            # 设置响应状态和标记
            self.response_status = status
            self.response_status_line = status_line
            self.response_headers = headers
            self.response_sent = True
            
            # 调用start_response
            self.start_response(status_line, headers)
            
            # 存储响应体，供wsgi_application使用
            if len(response_data) > CHUNK_SIZE:
                # 分块返回
                chunks = []
                for i in range(0, len(response_data), CHUNK_SIZE):
                    chunks.append(response_data[i:i + CHUNK_SIZE])
                self.response_body = chunks
            else:
                self.response_body = [response_data]
            
            return self.response_body
                
        except Exception as e:
            logger.error(f"发送JSON响应错误: {e}", exc_info=True)
            error_body = json.dumps(
                {'success': False, 'error': str(e)},
                ensure_ascii=False
            ).encode('utf-8')
            headers = [
                ('Content-Type', 'application/json; charset=utf-8'),
                ('Content-Length', str(len(error_body)))
            ]
            # 设置响应状态
            self.response_status = 500
            self.response_status_line = "500 Internal Server Error"
            self.response_headers = headers
            self.response_sent = True
            
            self.start_response('500 Internal Server Error', headers)
            self.response_body = [error_body]
            return self.response_body
    
    def send_error(self, code: int, message: str = None):
        """发送错误响应"""
        error_body = json.dumps(
            {'success': False, 'error': message or f'Error {code}'},
            ensure_ascii=False
        ).encode('utf-8')
        headers = [
            ('Content-Type', 'application/json; charset=utf-8'),
            ('Content-Length', str(len(error_body)))
        ]
        self.start_response(f'{code} Error', headers)
        self.response_body = [error_body]
        return self.response_body
    
    def _should_compress(self, content_type: str) -> bool:
        """判断是否应该压缩"""
        if not ENABLE_GZIP:
            return False
        compressible_types = [
            'text/html', 'text/css', 'text/javascript', 'application/javascript',
            'application/json', 'text/xml', 'application/xml', 'text/plain'
        ]
        return any(content_type.startswith(ct) for ct in compressible_types)
    
    def _compress_response(self, data: bytes) -> bytes:
        """压缩响应数据"""
        if not data:
            return data
        buf = BytesIO()
        with gzip.GzipFile(fileobj=buf, mode='wb', compresslevel=GZIP_COMPRESSION_LEVEL) as gz:
            gz.write(data)
        return buf.getvalue()
    
    def _get_etag(self, data):
        """生成ETag"""
        return hashlib.md5(data if isinstance(data, bytes) else data.encode('utf-8')).hexdigest()
    
    def _check_cache(self, etag):
        """检查客户端缓存"""
        if not ENABLE_CACHE:
            return False
        if_none_match = self.environ.get('HTTP_IF_NONE_MATCH', '')
        return if_none_match == etag
    
    def redirect_to_login(self):
        """重定向到登录页，保留原始URL以便登录后跳转"""
        # 如果已经调用了start_response，不再重复调用
        if self.response_sent:
            return self.response_body if self.response_body else [b'']
        
        # 获取当前请求的完整路径（包括查询参数）
        current_path = self.environ.get('PATH_INFO', '/')
        query_string = self.environ.get('QUERY_STRING', '')
        
        # 如果当前路径已经是登录页面，直接重定向到登录页面，不添加redirect参数（避免循环）
        if current_path == '/login' or (current_path == '/login' and query_string):
            headers = [('Location', '/login'), ('Content-Length', '0')]
            self.start_response('302 Found', headers)
            self.response_sent = True
            self.response_body = [b'']
            return self.response_body
        
        # 如果是API请求，尝试从Referer获取原始页面
        if current_path.startswith('/api/'):
            referer = self.environ.get('HTTP_REFERER', '')
            if referer:
                try:
                    # urlparse 已在文件顶部导入，无需重复导入
                    parsed = urlparse(referer)
                    current_path = parsed.path
                    if parsed.query:
                        query_string = parsed.query
                    # 如果Referer也是登录页面，不添加redirect参数
                    if current_path == '/login' or (current_path == '/login' and query_string):
                        headers = [('Location', '/login'), ('Content-Length', '0')]
                        self.start_response('302 Found', headers)
                        self.response_sent = True
                        self.response_body = [b'']
                        return self.response_body
                except:
                    pass
        
        # 构建登录URL，带上redirect参数
        login_url = '/login'
        if current_path and current_path != '/login' and not current_path.startswith('/api/') and not current_path.startswith('/login'):
            try:
                # 构建完整路径
                full_path = _prefix_public_redirect_target(current_path, _public_path_prefix(self.environ))
                if query_string:
                    full_path += '?' + query_string
                # 对路径进行URL编码（确保quote函数已导入）
                redirect_param = quote(full_path, safe='')
                login_url = f'/login?redirect={redirect_param}'
            except Exception as e:
                # 如果编码失败，使用默认登录URL
                logger.warning(f"URL编码失败，使用默认登录URL: {e}")
                login_url = '/login'
        
        headers = [('Location', login_url), ('Content-Length', '0')]
        self.start_response('302 Found', headers)
        self.response_sent = True
        self.response_body = [b'']
        return self.response_body
    
    def check_auth(self, require_admin: bool = False, required_roles: List[str] = None, 
                   require_super_admin: bool = False) -> bool:
        """检查认证"""
        from server.auth.permissions import check_access

        try:
            user = self.get_current_user()
        except Exception as e:
            logger.error(f"检查用户认证时出错: {e}", exc_info=True)
            if self.path.startswith('/api/'):
                if not self.response_sent:
                    self.send_json_response({'error': '认证检查失败', 'authenticated': False}, status=500)
                return False
            if not self.response_sent:
                self.redirect_to_login()
            return False

        result = check_access(
            user,
            super_admin=require_super_admin,
            admin=require_admin,
            roles=required_roles,
        )
        if result.allowed:
            return True
        if self.path.startswith('/api/'):
            if not self.response_sent:
                self.send_json_response(
                    {'success': False, 'error': result.error, 'authenticated': False},
                    status=result.status,
                )
            return False
        if result.status == 401:
            return False
        if not self.response_sent:
            self.send_error(result.status, result.error or '无访问权限')
        return False
    
    def _has_role(self, user: Dict[str, Any], role: str) -> bool:
        """检查用户是否有指定角色"""
        return self.user_manager.user_has_role(user, role) if user else False
    
    def _is_super_admin(self, user: Dict[str, Any]) -> bool:
        """检查是否是超级管理员"""
        return self.user_manager.is_super_admin(user) if user else False


# 导入Handler的处理方法（我们需要直接调用这些方法）
# 由于Handler的方法依赖于self，我们需要创建一个适配器来调用它们
def _read_login_post_body(environ: Dict[str, Any], adapter: Optional['WSGIRequestAdapter'] = None) -> bytes:
    """读取登录 POST 原始字节（优先未消费的 wsgi.input，避免适配器预读导致空 body）。"""
    try:
        content_length = int(environ.get('CONTENT_LENGTH') or 0)
    except (TypeError, ValueError):
        content_length = 0

    wsgi_input = environ.get('wsgi.input')
    if wsgi_input is not None:
        try:
            if content_length > 0:
                data = wsgi_input.read(content_length)
            else:
                data = wsgi_input.read()
            if data:
                return data
        except Exception as e:
            logger.warning(f"从 wsgi.input 读取登录请求体失败: {e}")

    if adapter is not None:
        try:
            adapter.rfile.seek(0)
            if content_length > 0:
                data = adapter.rfile.read(content_length)
            else:
                data = adapter.rfile.read()
            if data:
                return data
        except Exception as e:
            logger.warning(f"从 adapter.rfile 读取登录请求体失败: {e}")
    return b''


def _login_wants_html_redirect(environ: Dict[str, Any]) -> bool:
    """浏览器表单 POST（整页导航）时返回 302+Set-Cookie，比 fetch 更可靠写入 Cookie。"""
    if (environ.get('HTTP_SEC_FETCH_MODE') or '').lower() == 'navigate':
        return True
    accept = (environ.get('HTTP_ACCEPT') or '').lower()
    return accept.startswith('text/html')


def _normalize_login_redirect(target: str, environ: Optional[Dict[str, Any]] = None) -> str:
    target = (target or '/').strip()
    if not target or not target.startswith('/') or target.startswith('//'):
        return _prefix_public_redirect_target('/', _public_path_prefix(environ))
    return _prefix_public_redirect_target(target, _public_path_prefix(environ))


def _login_session_persist_error(
    environ: Dict[str, Any],
    start_response,
    error_msg: str = '会话写入失败，请稍后重试',
) -> List[bytes]:
    """登录认证已通过但 sessions 表写入失败/超时，不发放 Cookie。"""
    logger.error(f"登录会话持久化失败: {error_msg}")
    if _login_wants_html_redirect(environ):
        params = f'error={quote(error_msg, safe="")}'
        headers = [
            ('Location', f'/login?{params}'),
            ('Content-Length', '0'),
        ]
        start_response('302 Found', headers)
        return [b'']
    response_data = json.dumps(
        {'success': False, 'error': error_msg},
        ensure_ascii=False,
    ).encode('utf-8')
    headers = [
        ('Content-Type', 'application/json; charset=utf-8'),
        ('Content-Length', str(len(response_data))),
    ]
    start_response('503 Service Unavailable', headers)
    return [response_data]


def _login_redirect_error(
    environ: Dict[str, Any],
    start_response,
    error_msg: str,
    *,
    requires_captcha: bool = False,
) -> List[bytes]:
    if _login_wants_html_redirect(environ):
        params = f'error={quote(error_msg, safe="")}'
        if requires_captcha:
            params += '&requires_captcha=1'
        headers = [
            ('Location', f'/login?{params}'),
            ('Content-Length', '0'),
        ]
        start_response('302 Found', headers)
        return [b'']
    response_data = json.dumps(
        {
            'success': False,
            'error': error_msg,
            'requires_captcha': requires_captcha,
        },
        ensure_ascii=False,
    ).encode('utf-8')
    headers = [
        ('Content-Type', 'application/json; charset=utf-8'),
        ('Content-Length', str(len(response_data))),
    ]
    start_response('200 OK', headers)
    return [response_data]


def _read_login_post_fields(environ: Dict[str, Any], adapter: Optional['WSGIRequestAdapter'] = None):
    """解析登录 POST 体（优先 wsgi.input，兼容 CONTENT_LENGTH 缺失）。"""
    try:
        content_length = int(environ.get('CONTENT_LENGTH') or 0)
    except (TypeError, ValueError):
        content_length = 0
    content_type = (environ.get('CONTENT_TYPE') or '').lower()
    username = password = captcha_token = captcha_code = redirect = ''

    post_data_bytes = _read_login_post_body(environ, adapter)
    if not post_data_bytes:
        return username, password, captcha_token, captcha_code, redirect, content_length, content_type

    post_data = post_data_bytes.decode('utf-8') if isinstance(post_data_bytes, bytes) else post_data_bytes
    if 'application/json' in content_type:
        data = json.loads(post_data)
        username = data.get('username', '') or ''
        password = data.get('password', '') or ''
        captcha_token = data.get('captcha_token', '') or ''
        captcha_code = data.get('captcha_code', '') or ''
        redirect = data.get('redirect', '') or ''
    else:
        data = parse_qs(post_data, keep_blank_values=True)
        username = data.get('username', [''])[0]
        password = data.get('password', [''])[0]
        captcha_token = data.get('captcha_token', [''])[0]
        captcha_code = data.get('captcha_code', [''])[0]
        redirect = data.get('redirect', [''])[0]
    return username, password, captcha_token, captcha_code, redirect, content_length, content_type


def _handle_login_direct(
    environ: Dict[str, Any],
    start_response,
    adapter: Optional['WSGIRequestAdapter'] = None,
) -> List[bytes]:
    """直接处理登录请求（签名 Cookie）。"""
    response_data = json.dumps(
        {
            'success': False,
            'code': 403,
            'error': '本地账号密码登录已关闭，请使用钉钉登录',
        },
        ensure_ascii=False,
    ).encode('utf-8')
    headers = [
        ('Content-Type', 'application/json; charset=utf-8'),
        ('Content-Length', str(len(response_data))),
        ('Cache-Control', 'no-cache, no-store, must-revalidate'),
    ]
    start_response('403 Forbidden', headers)
    return [response_data]

    from server.startup_gate import login_allowed
    from server.auth.login_service import client_ip_from_environ, is_https_environ, perform_login

    ok_login, maint = login_allowed()
    if not ok_login and maint:
        msg = maint.get('message') or '系统正在启动，请稍候'
        if _login_wants_html_redirect(environ):
            return _login_redirect_error(environ, start_response, msg)
        response_data = json.dumps(
            {'success': False, 'error': msg, 'startup': maint},
            ensure_ascii=False,
        ).encode('utf-8')
        headers = [
            ('Content-Type', 'application/json; charset=utf-8'),
            ('Content-Length', str(len(response_data))),
        ]
        start_response('503 Service Unavailable', headers)
        return [response_data]

    username = password = captcha_token = captcha_code = redirect = ''
    content_length = int(environ.get('CONTENT_LENGTH') or 0)
    content_type = (environ.get('CONTENT_TYPE') or '').lower()

    try:
        username, password, captcha_token, captcha_code, redirect, content_length, content_type = _read_login_post_fields(
            environ, adapter
        )
    except json.JSONDecodeError as e:
        logger.error(f"解析JSON失败: {e}")
        response_data = json.dumps({'success': False, 'error': '请求格式错误'}, ensure_ascii=False).encode('utf-8')
        headers = [
            ('Content-Type', 'application/json; charset=utf-8'),
            ('Content-Length', str(len(response_data)))
        ]
        start_response('400 Bad Request', headers)
        return [response_data]
    except Exception as e:
        logger.error(f"读取请求体失败: {e}", exc_info=True)
        response_data = json.dumps({'success': False, 'error': '读取请求数据失败'}, ensure_ascii=False).encode('utf-8')
        headers = [
            ('Content-Type', 'application/json; charset=utf-8'),
            ('Content-Length', str(len(response_data)))
        ]
        start_response('400 Bad Request', headers)
        return [response_data]

    redirect_target = _normalize_login_redirect(redirect, environ)
    client_ip = client_ip_from_environ(environ)
    secure = is_https_environ(environ)

    ok, body, set_cookies = perform_login(
        username=username,
        password=password,
        captcha_token=captcha_token,
        captcha_code=captcha_code,
        client_ip=client_ip,
        secure=secure,
    )

    if not ok:
        requires_captcha = bool(body.get('requires_captcha'))
        if _login_wants_html_redirect(environ):
            return _login_redirect_error(
                environ,
                start_response,
                body.get('error') or '登录失败',
                requires_captcha=requires_captcha,
            )
        response_data = json.dumps(body, ensure_ascii=False).encode('utf-8')
        headers = [
            ('Content-Type', 'application/json; charset=utf-8'),
            ('Content-Length', str(len(response_data))),
        ]
        start_response('200 OK', headers)
        return [response_data]

    if _login_wants_html_redirect(environ):
        headers = [('Location', redirect_target), ('Content-Length', '0')]
        for c in set_cookies:
            headers.append(('Set-Cookie', c))
        start_response('302 Found', headers)
        return [b'']

    response_data = json.dumps(body, ensure_ascii=False).encode('utf-8')
    headers = [
        ('Content-Type', 'application/json; charset=utf-8'),
        ('Content-Length', str(len(response_data))),
    ]
    for c in set_cookies:
        headers.append(('Set-Cookie', c))
    start_response('200 OK', headers)
    return [response_data]


def create_handler_methods(adapter: WSGIRequestAdapter):
    """创建Handler方法的包装器"""
    
    # 这里我们需要导入并调用Handler的方法
    # 由于代码量很大，我们创建一个路由系统来调用相应的处理方法
    from server.main import HardwareRDBHandler
    from server.config import STATIC_DIR
    
    # 创建一个Handler实例来访问其方法
    # 但由于Handler需要socket参数，我们需要创建一个模拟的Handler
    class MockHandler(HardwareRDBHandler):
        """模拟Handler，用于调用处理方法"""
        
        def __init__(self, adapter):
            # 不调用父类的__init__，而是手动设置属性
            self.directory = STATIC_DIR
            self.path = adapter.path
            self.query_string = adapter.query_string
            self.command = adapter.method  # 在WSGI环境中，command就是method
            # 创建一个支持字典访问和get方法的headers对象
            class Headers:
                def __init__(self, headers_dict, get_func):
                    self._dict = headers_dict
                    self._get_func = get_func
                def __getitem__(self, key):
                    return self._dict.get(key, '')
                def get(self, key, default=''):
                    return self._dict.get(key, default)
            self.headers = Headers(adapter.headers, adapter.get)
            self.rfile = adapter.rfile
            self.wfile = adapter.wfile
            self.query_params = adapter.query_params
            self.adapter = adapter  # 保存adapter引用
            
            # 设置客户端地址（用于审计日志）
            self.client_address = adapter.client_address
            
            # 设置管理器
            self.user_manager = adapter.user_manager
            self.announcement_mgr = adapter.announcement_mgr
            self.quick_link_mgr = adapter.quick_link_mgr
            self.department_mgr = adapter.department_mgr
            self.todo_mgr = adapter.todo_mgr
        
        def get_current_user(self, skip_session_enrich: bool = False):
            return self.adapter.get_current_user(skip_session_enrich=skip_session_enrich)
        
        def send_json_response(self, data, status=200, set_cookies=None):
            return self.adapter.send_json_response(data, status, set_cookies=set_cookies)
        
        def send_error(self, code, message=None):
            return self.adapter.send_error(code, message)
        
        def send_response(self, code, message=None):
            return self.adapter.send_response(code, message)
        
        def send_header(self, key, value):
            return self.adapter.send_header(key, value)
        
        def end_headers(self):
            return self.adapter.end_headers()
        
        def check_auth(self, require_admin=False, required_roles=None, require_super_admin=False):
            return self.adapter.check_auth(require_admin, required_roles, require_super_admin)
        
        def _has_role(self, user, role):
            return self.adapter._has_role(user, role)
        
        def _is_super_admin(self, user):
            return self.adapter._is_super_admin(user)
        
        def redirect_to_login(self):
            return self.adapter.redirect_to_login()
        
        def redirect_to_home(self):
            """重定向到主页"""
            self.send_response(302)
            self.send_header('Location', '/')
            self.end_headers()
            # 确保设置了response_body（重定向不需要响应体）
            if self.adapter.response_body is None:
                self.adapter.response_body = [b'']
        
        def _get_etag(self, data):
            """生成ETag"""
            return self.adapter._get_etag(data)
        
        def _check_cache(self, etag):
            """检查客户端缓存"""
            return self.adapter._check_cache(etag)
        
        def _should_compress(self, content_type):
            """判断是否应该压缩"""
            return self.adapter._should_compress(content_type)
        
        def _compress_response(self, data):
            """压缩响应数据"""
            return self.adapter._compress_response(data)
    
    return MockHandler(adapter)


def wsgi_application(environ: Dict[str, Any], start_response) -> List[bytes]:
    """
    WSGI应用入口
    这是Gunicorn会调用的函数
    """
    try:
        start_response = _with_public_prefix_headers(environ, start_response)
        method = environ.get('REQUEST_METHOD', 'GET')
        path = environ.get('PATH_INFO', '/') or '/'
        path_norm = path.rstrip('/') or '/'

        if method == 'HEAD' and path_norm == '/':
            redirect_target = _prefix_public_redirect_target('/', _public_path_prefix(environ))
            headers = [('Location', f'/login?redirect={quote(redirect_target, safe="")}'), ('Content-Length', '0')]
            start_response('302 Found', headers)
            return [b'']

        if method == 'HEAD' and path_norm == '/login':
            headers = [('Content-Type', 'text/html; charset=utf-8'), ('Content-Length', '0')]
            start_response('200 OK', headers)
            return [b'']

        if method == 'GET' and path_norm == '/api/health':
            from server.health import handle_health_wsgi

            return handle_health_wsgi(environ, start_response)

        if method == 'GET' and path_norm == '/favicon.ico':
            favicon_path = os.path.join(STATIC_DIR, 'neo-logo.svg')
            if os.path.isfile(favicon_path):
                with open(favicon_path, 'rb') as fav:
                    body = fav.read()
                headers = [
                    ('Content-Type', 'image/svg+xml'),
                    ('Content-Length', str(len(body))),
                    ('Cache-Control', f'max-age={CACHE_MAX_AGE}'),
                ]
                start_response('200 OK', headers)
                return [body]
            headers = [('Content-Length', '0')]
            start_response('204 No Content', headers)
            return [b'']

        if method == 'GET' and path_norm == '/api/startup/status':
            from server.startup_gate import get_startup_status

            payload = get_startup_status()
            response_data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
            headers = [
                ('Content-Type', 'application/json; charset=utf-8'),
                ('Content-Length', str(len(response_data))),
                ('Cache-Control', 'no-store'),
            ]
            start_response('200 OK', headers)
            return [response_data]

        # 登录必须在 WSGIRequestAdapter 之前处理，避免预读 wsgi.input 导致 body 为空
        if method == 'POST' and path_norm == '/api/auth/login':
            try:
                return _handle_login_direct(environ, start_response)
            except Exception as e:
                import traceback
                error_trace = traceback.format_exc()
                logger.error(f"处理登录请求失败: {e}\n{error_trace}", exc_info=True)
                error_body = json.dumps({'success': False, 'error': str(e)}, ensure_ascii=False).encode('utf-8')
                headers = [
                    ('Content-Type', 'application/json; charset=utf-8'),
                    ('Content-Length', str(len(error_body)))
                ]
                start_response('500 Internal Server Error', headers)
                return [error_body]

        adapter = WSGIRequestAdapter(environ, start_response)
        handler = create_handler_methods(adapter)
        
        method = adapter.method
        path = adapter.path
        
        # 路由到相应的处理方法
        if method == 'GET':
            # 验证码API
            if path == '/api/captcha':
                try:
                    from server.captcha import get_captcha_manager
                    import base64
                    
                    from server.captcha import HAS_PIL
                    captcha_mgr = get_captcha_manager()
                    token, image_bytes = captcha_mgr.generate_captcha()
                    
                    image_base64 = base64.b64encode(image_bytes).decode('utf-8')
                    mime = 'image/png' if HAS_PIL else 'image/svg+xml'
                    
                    response_data = json.dumps({
                        'success': True,
                        'token': token,
                        'image': f'data:{mime};base64,{image_base64}'
                    }, ensure_ascii=False).encode('utf-8')
                    headers = [
                        ('Content-Type', 'application/json; charset=utf-8'),
                        ('Content-Length', str(len(response_data)))
                    ]
                    start_response('200 OK', headers)
                    return [response_data]
                except Exception as e:
                    logger.error(f"生成验证码失败: {e}", exc_info=True)
                    response_data = json.dumps({
                        'success': False,
                        'error': '生成验证码失败'
                    }, ensure_ascii=False).encode('utf-8')
                    headers = [
                        ('Content-Type', 'application/json; charset=utf-8'),
                        ('Content-Length', str(len(response_data)))
                    ]
                    start_response('500 Internal Server Error', headers)
                    return [response_data]
            
            if path.startswith('/api/'):
                # 调用Handler的handle_api_get方法
                try:
                    handler.handle_api_get()
                    # 检查是否有响应体（send_json_response会设置response_body）
                    if adapter.response_body is not None:
                        return adapter.response_body
                    # 如果没有响应体，尝试从wfile获取（serve_template等会写入wfile）
                    if adapter.wfile.tell() > 0:
                        # 如果还没有调用start_response，现在调用
                        if not adapter.response_sent:
                            # 确保有响应状态
                            if not adapter.response_status:
                                adapter.response_status = 200
                                adapter.response_status_line = "200 OK"
                            
                            # 确保有Content-Length头
                            content_length = adapter.wfile.tell()
                            has_content_length = any(h[0].lower() == 'content-length' for h in adapter.response_headers)
                            if not has_content_length:
                                adapter.response_headers.append(('Content-Length', str(content_length)))
                            
                            # 直接调用start_response（不通过end_headers）
                            adapter.start_response(adapter.response_status_line, adapter.response_headers)
                            adapter.response_sent = True
                            adapter.headers_ended = True
                        return [adapter.wfile.getvalue()]
                    # 如果没有响应体且没有调用start_response，返回默认响应
                    if not adapter.response_sent:
                        adapter.send_json_response({'error': 'No response'}, status=500)
                        return adapter.response_body if adapter.response_body else [b'']
                    # 默认返回空响应
                    return [b'']
                except Exception as e:
                    import traceback
                    error_trace = traceback.format_exc()
                    logger.error(f"处理API GET请求失败: {e}\n{error_trace}")
                    # 如果还没有调用start_response，先调用
                    if not adapter.response_sent:
                        adapter.send_error(500, str(e))
                    return adapter.response_body if adapter.response_body else [b'']
            else:
                # 处理页面请求
                try:
                    handler.handle_page_get()
                    # 检查是否有响应体
                    if adapter.response_body is not None:
                        return adapter.response_body
                    # 如果没有响应体，尝试从wfile获取（serve_template会写入wfile）
                    if adapter.wfile.tell() > 0:
                        # 如果还没有调用start_response，现在调用
                        if not adapter.response_sent and adapter.response_status:
                            # 确保响应头包含Content-Length
                            has_content_length = any(h[0].lower() == 'content-length' for h in adapter.response_headers)
                            if not has_content_length:
                                content_length = adapter.wfile.tell()
                                adapter.response_headers.append(('Content-Length', str(content_length)))
                            # 调用start_response
                            status_line = adapter.response_status_line
                            adapter.start_response(status_line, adapter.response_headers)
                            adapter.response_sent = True
                        return [adapter.wfile.getvalue()]
                    # 如果响应头已结束但没有内容，可能是重定向或其他情况
                    if adapter.headers_ended:
                        if adapter.response_status in (302, 301):
                            # 重定向响应
                            if not adapter.response_sent:
                                status_line = adapter.response_status_line
                                has_content_length = any(h[0].lower() == 'content-length' for h in adapter.response_headers)
                                if not has_content_length:
                                    adapter.response_headers.append(('Content-Length', '0'))
                                adapter.start_response(status_line, adapter.response_headers)
                                adapter.response_sent = True
                            return [b'']
                        elif adapter.response_status:
                            # 其他状态码，但还没有调用start_response
                            if not adapter.response_sent:
                                status_line = adapter.response_status_line
                                has_content_length = any(h[0].lower() == 'content-length' for h in adapter.response_headers)
                                if not has_content_length:
                                    adapter.response_headers.append(('Content-Length', '0'))
                                adapter.start_response(status_line, adapter.response_headers)
                                adapter.response_sent = True
                            return [b'']
                    # 默认返回空响应（这不应该发生，但作为后备）
                    logger.warning(f"未处理的响应: path={path}, status={adapter.response_status}, headers_ended={adapter.headers_ended}, response_sent={adapter.response_sent}")
                    return [b'']
                except Exception as e:
                    import traceback
                    error_trace = traceback.format_exc()
                    logger.error(f"处理页面GET请求失败: {e}\n{error_trace}", exc_info=True)
                    # 返回详细的错误信息（开发环境）
                    error_html = f"""<html>
<head><title>Internal Server Error</title></head>
<body>
<h1>Internal Server Error</h1>
<p>错误: {str(e)}</p>
<pre>{error_trace}</pre>
</body>
</html>"""
                    error_body = error_html.encode('utf-8')
                    headers = [
                        ('Content-Type', 'text/html; charset=utf-8'),
                        ('Content-Length', str(len(error_body)))
                    ]
                    adapter.start_response('500 Internal Server Error', headers)
                    return [error_body]
        
        elif method == 'POST':
            if path.startswith('/api/'):
                # 特殊处理登录请求，直接处理避免适配器问题
                if path_norm == '/api/auth/login':
                    try:
                        return _handle_login_direct(environ, start_response, adapter)
                    except Exception as e:
                        import traceback
                        error_trace = traceback.format_exc()
                        logger.error(f"处理登录请求失败: {e}\n{error_trace}", exc_info=True)
                        error_body = json.dumps({'success': False, 'error': str(e)}, ensure_ascii=False).encode('utf-8')
                        headers = [
                            ('Content-Type', 'application/json; charset=utf-8'),
                            ('Content-Length', str(len(error_body)))
                        ]
                        start_response('500 Internal Server Error', headers)
                        return [error_body]
                
                try:
                    handler.handle_api_post()
                    # 检查是否有响应体（send_json_response会设置response_body）
                    if adapter.response_body is not None:
                        return adapter.response_body
                    # 如果没有响应体，尝试从wfile获取（send_response/send_header/end_headers/wfile.write会写入wfile）
                    if adapter.wfile.tell() > 0:
                        # 如果还没有调用start_response，现在调用
                        if not adapter.response_sent:
                            # 更新Content-Length（因为wfile.write可能在end_headers之后）
                            content_length = adapter.wfile.tell()
                            # 移除旧的Content-Length（如果存在）
                            adapter.response_headers = [(k, v) for k, v in adapter.response_headers if k.lower() != 'content-length']
                            # 添加正确的Content-Length
                            adapter.response_headers.append(('Content-Length', str(content_length)))
                            
                            # 调用start_response
                            status_line = adapter.response_status_line if adapter.response_status else "200 OK"
                            if not adapter.response_status:
                                adapter.response_status = 200
                                adapter.response_status_line = "200 OK"
                            
                            adapter.start_response(status_line, adapter.response_headers)
                            adapter.response_sent = True
                        return [adapter.wfile.getvalue()]
                    # 如果响应头已结束但没有内容，可能是重定向或其他情况
                    if adapter.headers_ended:
                        if adapter.response_status in (302, 301):
                            # 重定向响应
                            if not adapter.response_sent:
                                adapter.end_headers()
                            return [b'']
                        elif adapter.response_status:
                            # 其他状态码，但还没有调用start_response
                            if not adapter.response_sent:
                                adapter.end_headers()
                            return [b'']
                    # 默认返回空响应
                    logger.warning(f"POST请求未返回响应: path={path}, status={adapter.response_status}, response_sent={adapter.response_sent}")
                    return [b'']
                except Exception as e:
                    import traceback
                    error_trace = traceback.format_exc()
                    logger.error(f"处理API POST请求失败: {e}\n{error_trace}", exc_info=True)
                    # 如果还没有调用start_response，先调用
                    if not adapter.response_sent:
                        adapter.send_error(500, str(e))
                    return adapter.response_body if adapter.response_body else [b'']
            else:
                return adapter.send_error(404, 'Not Found')
        
        elif method == 'PUT':
            if path.startswith('/api/'):
                try:
                    handler.handle_api_put()
                    if adapter.response_body is not None:
                        return adapter.response_body
                    if adapter.wfile.tell() > 0:
                        return [adapter.wfile.getvalue()]
                    return [b'']
                except Exception as e:
                    logger.error(f"处理API PUT请求失败: {e}", exc_info=True)
                    return adapter.send_error(500, str(e))
            else:
                return adapter.send_error(404, 'Not Found')
        
        elif method == 'DELETE':
            if path.startswith('/api/'):
                try:
                    handler.handle_api_delete()
                    if adapter.response_body is not None:
                        return adapter.response_body
                    if adapter.wfile.tell() > 0:
                        return [adapter.wfile.getvalue()]
                    return [b'']
                except Exception as e:
                    logger.error(f"处理API DELETE请求失败: {e}", exc_info=True)
                    return adapter.send_error(500, str(e))
            else:
                return adapter.send_error(404, 'Not Found')
        
        else:
            return adapter.send_error(405, 'Method Not Allowed')
    
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        logger.error(f"WSGI应用错误: {e}\n{error_trace}", exc_info=True)
        
        # 返回HTML错误页面（更友好）
        error_html = f"""<html>
<head><title>Internal Server Error</title></head>
<body>
<h1>Internal Server Error</h1>
<p>服务器内部错误，请查看日志获取详细信息。</p>
<pre>{str(e)}</pre>
</body>
</html>"""
        error_body = error_html.encode('utf-8')
        headers = [
            ('Content-Type', 'text/html; charset=utf-8'),
            ('Content-Length', str(len(error_body)))
        ]
        start_response('500 Internal Server Error', headers)
        return [error_body]


# 启动完成标志（每个worker进程一个）
_worker_ready = threading.Event()
_worker_initialized = False
_init_lock = threading.Lock()

def _initialize_worker():
    """初始化worker（每个worker进程调用一次）- 阶段1优化：添加重试机制，阶段2优化：异步预加载"""
    global _worker_initialized
    with _init_lock:
        if _worker_initialized:
            return
        
        # 阶段1优化：添加重试机制（最多3次）
        max_retries = 3
        retry_delays = [5, 10, 20]  # 重试间隔：5秒、10秒、20秒
        last_error = None
        
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    logger.warning(f"🔄 Worker初始化重试（第{attempt + 1}次，共{max_retries}次）...")
                    import time
                    time.sleep(retry_delays[attempt - 1])
                
                logger.info("=" * 60)
                logger.info("🔄 Worker进程正在初始化...")
                logger.info("=" * 60)
                
                # 初始化管理器（这会触发单例初始化）
                from server.user_manager import UserManager
                from server.announcement_manager import AnnouncementManager
                from server.quick_link_manager import QuickLinkManager
                from server.department_manager import DepartmentManager
                from server.todo_manager import TodoManager
                
                # 预初始化管理器（触发单例创建）
                user_mgr = UserManager()
                announcement_mgr = AnnouncementManager(base_dir=BASE_DIR)
                quick_link_mgr = QuickLinkManager()
                department_mgr = DepartmentManager()
                todo_mgr = TodoManager()
                
                # 初始化预加载器（每个worker进程都需要预加载数据）
                from server.data_preloader import get_data_preloader
                from server.config import PRELOAD_USERS, PRELOAD_ANNOUNCEMENTS, PRELOAD_DEPARTMENTS, PRELOAD_TODOS, ASYNC_PRELOAD
                
                preloader = get_data_preloader()
                # 确保预加载器有正确的管理器引用
                preloader.set_managers(user_mgr, announcement_mgr, department_mgr, todo_mgr)
                logger.info(f"[DEBUG] 预加载器管理器设置完成: user_manager={preloader.user_manager is not None}, announcement_mgr={preloader.announcement_mgr is not None}, todo_mgr={preloader.todo_mgr is not None}")
                
                # 阶段2优化：异步预加载（非阻塞模式）
                # 如果启用异步预加载，worker立即就绪，数据在后台加载
                if ASYNC_PRELOAD and (PRELOAD_USERS or PRELOAD_ANNOUNCEMENTS or PRELOAD_DEPARTMENTS or PRELOAD_TODOS):
                    logger.info("🔄 开始异步预加载数据（非阻塞模式，worker立即就绪）...")
                    import threading
                    def async_preload():
                        try:
                            preloader.preload_all(user_mgr, announcement_mgr, department_mgr, todo_mgr)
                            logger.info("✅ 异步数据预加载完成")
                        except Exception as e:
                            logger.error(f"异步预加载失败: {e}", exc_info=True)
                    
                    preload_thread = threading.Thread(target=async_preload, daemon=True)
                    preload_thread.start()
                    logger.info("✅ Worker进程已就绪（数据在后台加载中）")
                else:
                    # 同步预加载（阻塞模式，确保数据就绪）
                    if PRELOAD_USERS or PRELOAD_ANNOUNCEMENTS or PRELOAD_DEPARTMENTS or PRELOAD_TODOS:
                        logger.info("🔄 开始同步预加载数据（阻塞模式，确保数据就绪）...")
                        preloader.preload_all(user_mgr, announcement_mgr, department_mgr, todo_mgr)
                        logger.info("✅ 数据预加载完成，worker已就绪")
                
                # 注意：钉钉同步任务已在Gunicorn master进程启动时执行（gunicorn_config.py的on_starting钩子）
                # 这里不再执行，避免重复同步
                
                # 启动定时通知任务（使用文件锁确保只有一个进程执行）
                logger.info("正在启动定时通知任务（Worker进程）...")
                try:
                    from server.scheduled_notifications import start_scheduled_notifications
                    start_scheduled_notifications()
                    logger.info("✅ 定时通知任务已启动（Worker进程，使用文件锁防止重复执行）")
                except Exception as e:
                    logger.error(f"❌ 启动定时通知任务失败（Worker进程）: {e}", exc_info=True)
                    logger.warning("   定时通知功能可能不可用（可能已在其他进程中运行）")
                
                _worker_initialized = True
                _worker_ready.set()
                
                logger.info("=" * 60)
                logger.info("✅ Worker进程初始化完成，已就绪接受请求")
                logger.info("=" * 60)
                return  # 成功，退出重试循环
                
            except Exception as e:
                last_error = e
                logger.error(f"Worker初始化失败（第{attempt + 1}次尝试）: {e}", exc_info=True)
                if attempt < max_retries - 1:
                    logger.warning(f"将在{retry_delays[attempt]}秒后重试...")
                else:
                    logger.error(f"Worker初始化失败（已重试{max_retries}次），放弃初始化")
                    raise  # 最后一次失败，抛出异常


def wsgi_application_with_init(environ: Dict[str, Any], start_response) -> List[bytes]:
    """带初始化检查的WSGI应用"""
    # 确保worker已初始化
    if not _worker_initialized:
        _initialize_worker()
    
    # 等待worker就绪（最多等待10秒）
    if not _worker_ready.wait(timeout=10):
        logger.error("Worker初始化超时")
        error_body = b'{"error": "Server is initializing, please try again later"}'
        headers = [
            ('Content-Type', 'application/json; charset=utf-8'),
            ('Content-Length', str(len(error_body)))
        ]
        start_response('503 Service Unavailable', headers)
        return [error_body]
    
    # 调用原始WSGI应用
    return wsgi_application(environ, start_response)


# WSGI应用实例（Gunicorn会调用这个）
# 使用带初始化检查的版本
application = wsgi_application_with_init
