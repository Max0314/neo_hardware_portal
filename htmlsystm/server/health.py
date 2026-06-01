# -*- coding: utf-8 -*-
"""轻量存活探针（容器 healthcheck / 网关巡检，不走会话与 auth/check）。"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs

from server.logger import logger

_DB_PING_TIMEOUT_SEC = 2.0


def _wants_db_check(environ: Optional[Dict[str, Any]]) -> bool:
    if not environ:
        return False
    qs = environ.get('QUERY_STRING') or ''
    params = parse_qs(qs, keep_blank_values=True)
    val = (params.get('db') or [''])[0]
    return str(val).strip().lower() in ('1', 'true', 'yes')


def _ping_mysql(timeout_sec: float = _DB_PING_TIMEOUT_SEC) -> bool:
    def _run() -> bool:
        from server.db_adapter import get_connection_pool

        pool = get_connection_pool()
        with pool.get_cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
        return True

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            return bool(executor.submit(_run).result(timeout=timeout_sec))
    except FuturesTimeoutError:
        logger.warning("health db ping 超时(%ss)", timeout_sec)
        return False
    except Exception as exc:
        logger.warning("health db ping 失败: %s", exc)
        return False


def health_payload(*, check_db: bool = False) -> Tuple[dict, int]:
    body: Dict[str, Any] = {'ok': True, 'service': 'htmlsystm'}
    if not check_db:
        return body, 200
    db_ok = _ping_mysql()
    body['db'] = db_ok
    if db_ok:
        return body, 200
    body['ok'] = False
    return body, 503


def handle_health_wsgi(environ: Dict[str, Any], start_response) -> List[bytes]:
    check_db = _wants_db_check(environ)
    payload, status_code = health_payload(check_db=check_db)
    response_data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    status_line = '200 OK' if status_code == 200 else '503 Service Unavailable'
    headers = [
        ('Content-Type', 'application/json; charset=utf-8'),
        ('Content-Length', str(len(response_data))),
        ('Cache-Control', 'no-store'),
    ]
    start_response(status_line, headers)
    return [response_data]
