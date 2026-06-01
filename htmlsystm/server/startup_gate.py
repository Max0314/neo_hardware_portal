# -*- coding: utf-8 -*-
"""开机/栈启动维护门：存在 .startup_lock.json 时禁止登录。"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Optional, Tuple

from server.config import DATA_DIR

LOCK_FILE = os.path.join(DATA_DIR, '.startup_lock.json')
READY_FILE = os.path.join(DATA_DIR, '.startup_ready')


def _read_lock() -> Dict[str, Any]:
    try:
        with open(LOCK_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {'percent': 0, 'message': '系统正在启动，请稍候', 'ready': False}


def get_startup_status() -> Dict[str, Any]:
    """供 /api/startup/status 与登录页轮询。"""
    if os.path.isfile(LOCK_FILE):
        lock = _read_lock()
        return {
            'ready': False,
            'in_progress': True,
            'percent': int(lock.get('percent', 0) or 0),
            'message': str(lock.get('message') or '系统正在启动，请稍候'),
        }
    if os.path.isfile(READY_FILE):
        return {
            'ready': True,
            'in_progress': False,
            'percent': 100,
            'message': '系统已就绪',
        }
    return {
        'ready': True,
        'in_progress': False,
        'percent': 100,
        'message': '系统已就绪（未经过启动流水线，兼容手动 compose up）',
    }


def login_allowed() -> Tuple[bool, Optional[Dict[str, Any]]]:
    """False 时返回维护状态 dict。"""
    if os.path.isfile(LOCK_FILE):
        return False, get_startup_status()
    return True, None


def write_lock(percent: int, message: str) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    payload = {
        'percent': max(0, min(100, int(percent))),
        'message': message,
        'ready': False,
        'updated_at': time.time(),
    }
    with open(LOCK_FILE, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False)
    try:
        if os.path.isfile(READY_FILE):
            os.remove(READY_FILE)
    except OSError:
        pass


def clear_lock_and_mark_ready() -> None:
    try:
        if os.path.isfile(LOCK_FILE):
            os.remove(LOCK_FILE)
    except OSError:
        pass
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(READY_FILE, 'w', encoding='utf-8') as f:
        f.write(str(time.time()))
