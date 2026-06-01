# -*- coding: utf-8 -*-
"""
超级管理员 (zzw) 凭据：首次启动随机生成并写入 data/admin_credentials.json，
不再使用 .env 中的 SUPER_ADMIN_PASSWORD。
"""
from __future__ import annotations

import json
import os
import secrets
import string
from datetime import datetime
from typing import Dict, Optional, Tuple

from server.config import DATA_DIR
from server.logger import logger

ADMIN_USERNAME = os.getenv('SUPER_ADMIN_USERNAME', 'zzw').strip() or 'zzw'
CREDENTIALS_FILE = os.path.join(DATA_DIR, 'admin_credentials.json')

_PASSWORD_ALPHABET = string.ascii_letters + string.digits + '!@#$%^&*-_=+'


def generate_random_password(length: int = 16) -> str:
    """生成满足复杂度要求的随机密码。"""
    length = max(12, min(int(length or 16), 64))
    while True:
        pwd = ''.join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(length))
        if (
            any(c.islower() for c in pwd)
            and any(c.isupper() for c in pwd)
            and any(c.isdigit() for c in pwd)
            and any(c in '!@#$%^&*-_=+' for c in pwd)
        ):
            return pwd


def load_credentials() -> Optional[Dict[str, str]]:
    if not os.path.isfile(CREDENTIALS_FILE):
        return None
    try:
        with open(CREDENTIALS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        username = str(data.get('username') or ADMIN_USERNAME).strip()
        password = str(data.get('password') or '')
        if username and password:
            return {'username': username, 'password': password}
    except Exception as exc:
        logger.warning('读取 admin_credentials.json 失败: %s', exc)
    return None


def save_credentials(username: str, password: str) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    payload = {
        'username': username,
        'password': password,
        'updated_at': datetime.now().isoformat(timespec='seconds'),
        'note': '管理员登录凭据；勿提交到 Git。重置密码后请用 --password 参数并会更新本文件。',
    }
    with open(CREDENTIALS_FILE, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    try:
        os.chmod(CREDENTIALS_FILE, 0o600)
    except OSError:
        pass


def bootstrap_admin_password(*, create_if_missing: bool = True) -> Tuple[str, str, bool]:
    """
    返回 (username, plain_password, is_newly_generated)。
    若凭据文件已存在则直接读取；否则生成新密码并写入文件。
    """
    existing = load_credentials()
    if existing:
        return existing['username'], existing['password'], False

    if not create_if_missing:
        raise RuntimeError('admin_credentials.json 不存在且未允许创建')

    plain = generate_random_password()
    save_credentials(ADMIN_USERNAME, plain)
    return ADMIN_USERNAME, plain, True


def print_admin_credentials_banner(plain_password: str, *, username: Optional[str] = None) -> None:
    """首次创建管理员时打印到标准输出（docker logs / 启动流水线可见）。"""
    user = username or ADMIN_USERNAME
    border = '=' * 72
    lines = [
        '',
        border,
        '【超级管理员初始密码 — 仅首次启动显示，请立即保存】',
        border,
        f'  用户名: {user}',
        f'  密码:   {plain_password}',
        f'  凭据文件: {CREDENTIALS_FILE}',
        border,
        '  登录: https://<服务器IP>:8000/login',
        '  说明: 不再从 .env 读取 SUPER_ADMIN_PASSWORD；改密请用:',
        '    docker exec stack-htmlsystm python scripts/view_and_reset_admin_password.py \\',
        "      --reset zzw --password '你的新密码'",
        border,
        '',
    ]
    msg = '\n'.join(lines)
    print(msg, flush=True)
    logger.info('已生成超级管理员初始密码（详见上方控制台输出）')
