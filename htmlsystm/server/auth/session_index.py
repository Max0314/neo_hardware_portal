# -*- coding: utf-8 -*-
"""轻量会话索引：每用户最多 N 个并发 jti。"""
from __future__ import annotations

import os
import time

from server.db_adapter import get_connection_pool
from server.logger import logger

MAX_SESSIONS_PER_USER = max(1, min(int(os.getenv('MAX_SESSIONS_PER_USER', '10') or 10), 50))


def ensure_auth_session_table(cursor) -> None:
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS auth_session_index (
            jti VARCHAR(64) PRIMARY KEY,
            user_id INT NOT NULL,
            created_at DOUBLE NOT NULL,
            INDEX idx_auth_sess_user_created (user_id, created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    ''')


def migrate_users_session_rev(cursor) -> None:
    cursor.execute(
        """
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'users' AND COLUMN_NAME = 'session_rev'
        LIMIT 1
        """
    )
    if not cursor.fetchone():
        cursor.execute(
            'ALTER TABLE users ADD COLUMN session_rev INT NOT NULL DEFAULT 0'
        )


def get_user_session_rev(user_id: int) -> int:
    try:
        pool = get_connection_pool()
        with pool.get_cursor() as cursor:
            cursor.execute('SELECT session_rev FROM users WHERE id = %s LIMIT 1', (int(user_id),))
            row = cursor.fetchone()
            if not row:
                return 0
            if isinstance(row, dict):
                return int(row.get('session_rev') or 0)
            return int(row[0] or 0)
    except Exception as exc:
        logger.warning('读取 session_rev 失败 user_id=%s: %s', user_id, exc)
        return 0


def bump_user_session_rev(user_id: int) -> int:
    """改密/禁用：递增 rev 并清除全部 jti。"""
    uid = int(user_id)
    revoke_all_for_user(uid)
    try:
        pool = get_connection_pool()
        with pool.get_cursor() as cursor:
            cursor.execute(
                'UPDATE users SET session_rev = session_rev + 1 WHERE id = %s',
                (uid,),
            )
            cursor.execute('SELECT session_rev FROM users WHERE id = %s LIMIT 1', (uid,))
            row = cursor.fetchone()
            if isinstance(row, dict):
                return int(row.get('session_rev') or 0)
            return int(row[0] or 0) if row else 0
    except Exception as exc:
        logger.error('bump session_rev 失败 user_id=%s: %s', uid, exc, exc_info=True)
        return 0


def register_session(user_id: int, jti: str) -> None:
    uid = int(user_id)
    now = time.time()
    pool = get_connection_pool()
    with pool.get_cursor() as cursor:
        cursor.execute(
            'INSERT INTO auth_session_index (jti, user_id, created_at) VALUES (%s, %s, %s)',
            (jti, uid, now),
        )
        cursor.execute(
            'SELECT COUNT(*) AS c FROM auth_session_index WHERE user_id = %s',
            (uid,),
        )
        row = cursor.fetchone()
        count = int(row.get('c') if isinstance(row, dict) else row[0])
        overflow = count - MAX_SESSIONS_PER_USER
        if overflow > 0:
            cursor.execute(
                '''
                DELETE FROM auth_session_index
                WHERE user_id = %s
                ORDER BY created_at ASC
                LIMIT %s
                ''',
                (uid, overflow),
            )
            logger.debug(
                '会话配额清理 user_id=%s removed=%s keep=%s',
                uid,
                overflow,
                MAX_SESSIONS_PER_USER,
            )


def is_jti_active(jti: str) -> bool:
    if not jti:
        return False
    try:
        pool = get_connection_pool()
        with pool.get_cursor() as cursor:
            cursor.execute(
                'SELECT 1 FROM auth_session_index WHERE jti = %s LIMIT 1',
                (jti,),
            )
            return cursor.fetchone() is not None
    except Exception as exc:
        logger.warning('is_jti_active 失败 jti=%s...: %s', jti[:8], exc)
        return False


def revoke_jti(jti: str) -> None:
    if not jti:
        return
    try:
        pool = get_connection_pool()
        with pool.get_cursor() as cursor:
            cursor.execute('DELETE FROM auth_session_index WHERE jti = %s', (jti,))
    except Exception as exc:
        logger.warning('revoke_jti 失败: %s', exc)


def revoke_all_for_user(user_id: int) -> int:
    uid = int(user_id)
    if not uid:
        return 0
    try:
        pool = get_connection_pool()
        with pool.get_cursor() as cursor:
            cursor.execute('DELETE FROM auth_session_index WHERE user_id = %s', (uid,))
            return int(cursor.rowcount or 0)
    except Exception as exc:
        logger.warning('revoke_all_for_user 失败 user_id=%s: %s', uid, exc)
        return 0
