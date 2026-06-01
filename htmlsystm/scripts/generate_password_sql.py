#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成用户密码重置 SQL（不依赖 MySQL 连接，可在 htmlsystm 容器内运行）。"""
import argparse
import os
import random
import string
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.security import PasswordHasher


def _generate_strong_password(length: int = 14) -> str:
    chars = string.ascii_letters + string.digits + '!@#$%^&*()_+-='
    pwd = ''.join(random.choices(chars, k=length))
    if not any(c.isupper() for c in pwd):
        pwd = random.choice(string.ascii_uppercase) + pwd[1:]
    if not any(c.islower() for c in pwd):
        pwd = pwd[0] + random.choice(string.ascii_lowercase) + pwd[2:]
    if not any(c.isdigit() for c in pwd):
        pwd = pwd[:2] + random.choice(string.digits) + pwd[3:]
    if not any(c in '!@#$%^&*()_+-=' for c in pwd):
        pwd = pwd[:3] + random.choice('!@#$%^&*') + pwd[4:]
    return pwd


def main() -> None:
    parser = argparse.ArgumentParser(description='生成用户密码重置 SQL')
    parser.add_argument('username', nargs='?', default='zzw', help='用户名，默认 zzw')
    parser.add_argument('--password', help='指定新密码（须符合强度要求）')
    parser.add_argument(
        '--sql-only',
        action='store_true',
        help='仅输出 UPDATE 语句到 stdout（供管道导入 MySQL）',
    )
    args = parser.parse_args()

    password = (args.password or '').strip() or _generate_strong_password()
    hashed = PasswordHasher.hash_password(password)
    username = args.username.strip()
    sql = (
        f"UPDATE users SET password = '{hashed}', updated_time = NOW() "
        f"WHERE username = '{username}';"
    )

    if args.sql_only:
        print(sql, file=sys.stdout)
        print(f"{username}\t{password}", file=sys.stderr)
    else:
        print(f"-- 用户: {username}")
        print(f"-- 新密码: {password}")
        print(sql)


if __name__ == '__main__':
    main()
