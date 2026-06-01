# -*- coding: utf-8 -*-
"""唯一改密入口：自助改密、超管代改、钉钉默认口令、启动审计。"""
import secrets
import string
from typing import Any, Dict, Optional, Tuple

from server.logger import logger
from server.security import PasswordHasher, InputValidator

DEFAULT_DINGTALK_PASSWORD = 'CHXW_HW_123456'
STATUS_ACTIVE = 'active'


def _looks_hashed(stored: str) -> bool:
    s = (stored or '').strip()
    if not s:
        return False
    if s.startswith('$2b$') or s.startswith('$2a$'):
        return True
    if s.startswith('sha512:'):
        return True
    if ':' in s and len(s.split(':', 1)[-1]) == 64:
        return True
    return False


class PasswordService:
    def __init__(self, user_manager=None):
        self._user_manager = user_manager

    @property
    def user_manager(self):
        if self._user_manager is None:
            from server.user_manager import UserManager
            self._user_manager = UserManager()
        return self._user_manager

    @staticmethod
    def default_password_hash() -> str:
        return PasswordHasher.hash_password(DEFAULT_DINGTALK_PASSWORD)

    @staticmethod
    def generate_temporary_password(length: int = 16) -> str:
        alphabet = string.ascii_letters + string.digits + '!@#$%^&*'
        while True:
            pwd = ''.join(secrets.choice(alphabet) for _ in range(length))
            ok, _ = InputValidator.validate_password(pwd, check_strength=True)
            if ok:
                return pwd

    def invalidate_user_sessions(self, user_id: int, memory_sessions=None, memory_lock=None) -> int:
        from server.auth.session_index import bump_user_session_rev
        from server.auth.session_sync import notify_sessions_invalidated, purge_memory_sessions_for_user

        removed = bump_user_session_rev(int(user_id))
        notify_sessions_invalidated(int(user_id))
        if memory_sessions is not None and memory_lock is not None:
            purge_memory_sessions_for_user(int(user_id), memory_sessions, memory_lock)
        return removed

    def _verify_old_password(self, username: str, old_password: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
        user = self.user_manager.authenticate_user_for_login(username, old_password)
        if not user:
            return False, None
        return True, user

    def change_own_password(
        self,
        *,
        user_id: int,
        username: str,
        old_password: str,
        new_password: str,
        memory_sessions=None,
        memory_lock=None,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """已登录或未登录（须旧密码）自助改密。"""
        old_password = (old_password or '').strip()
        new_password = (new_password or '').strip()
        username = (username or '').strip()

        if not old_password:
            return False, '请输入当前密码', {}
        if not new_password:
            return False, '请输入新密码', {}

        ok, err = InputValidator.validate_password(new_password, check_strength=True)
        if not ok:
            return False, err or '新密码不符合要求', {}

        if old_password == new_password:
            return False, '新密码不能与当前密码相同', {}

        verified, user = self._verify_old_password(username, old_password)
        if not verified or not user:
            return False, '当前密码错误', {}
        if int(user.get('id') or 0) != int(user_id):
            return False, '用户身份不匹配', {}

        status = user.get('status')
        if status != STATUS_ACTIVE:
            return False, '账号不可用，无法修改密码', {}

        return self._apply_password_update(
            int(user_id),
            new_password,
            memory_sessions=memory_sessions,
            memory_lock=memory_lock,
            clear_auto_login=True,
        )

    def admin_reset_password(
        self,
        target_user_id: int,
        new_password: str,
        *,
        skip_strength: bool = False,
        memory_sessions=None,
        memory_lock=None,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """超管或运维脚本代改密码（无需旧密码）。"""
        new_password = (new_password or '').strip()
        if not new_password:
            return False, '请输入新密码', {}

        if not skip_strength:
            ok, err = InputValidator.validate_password(new_password, check_strength=True)
            if not ok:
                return False, err or '新密码不符合要求', {}

        user = self.user_manager.get_user_by_id(int(target_user_id))
        if not user:
            return False, '用户不存在', {}

        return self._apply_password_update(
            int(target_user_id),
            new_password,
            memory_sessions=memory_sessions,
            memory_lock=memory_lock,
            clear_auto_login=True,
        )

    def admin_reset_by_username(
        self,
        username: str,
        new_password: str,
        *,
        memory_sessions=None,
        memory_lock=None,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        user = self.user_manager.get_user_by_username(username) if hasattr(self.user_manager, 'get_user_by_username') else None
        if not user:
            from server.db_adapter import get_connection_pool
            pool = get_connection_pool()
            with pool.get_cursor() as cursor:
                cursor.execute('SELECT id FROM users WHERE username = %s LIMIT 1', (username,))
                row = cursor.fetchone()
                if not row:
                    return False, f'未找到用户: {username}', {}
                uid = row['id'] if isinstance(row, dict) else row[0]
            return self.admin_reset_password(uid, new_password, memory_sessions=memory_sessions, memory_lock=memory_lock)
        return self.admin_reset_password(int(user['id']), new_password, memory_sessions=memory_sessions, memory_lock=memory_lock)

    def _apply_password_update(
        self,
        user_id: int,
        new_password: str,
        *,
        memory_sessions=None,
        memory_lock=None,
        clear_auto_login: bool = False,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        success, message = self.user_manager.update_user(
            user_id,
            {'password': new_password},
            skip_session_invalidation=True,
        )
        if not success:
            return False, message or '密码修改失败', {}

        removed = self.invalidate_user_sessions(user_id, memory_sessions, memory_lock)
        logger.info(f'密码已更新 user_id={user_id}, sessions_removed={removed}')

        meta = {'clearAutoLogin': clear_auto_login, 'sessionsRemoved': removed}
        return True, '密码修改成功', meta

    def audit_passwords(self) -> Dict[str, int]:
        """启动时：将明文 password 转为 bcrypt。"""
        stats = {'plaintext': 0, 'bcrypt': 0, 'legacy_sha': 0, 'fixed': 0}
        try:
            from server.db_adapter import get_connection_pool
            pool = get_connection_pool()
            with pool.get_cursor() as cursor:
                cursor.execute('SELECT id, username, password FROM users')
                rows = cursor.fetchall() or []
            for row in rows:
                if isinstance(row, dict):
                    uid, uname, stored = row.get('id'), row.get('username'), row.get('password')
                else:
                    uid, uname, stored = row[0], row[1], row[2]
                stored = (stored or '').strip()
                if not stored:
                    continue
                if stored.startswith('$2b$') or stored.startswith('$2a$'):
                    stats['bcrypt'] += 1
                elif stored.startswith('sha512:') or (':' in stored and len(stored.split(':')[-1]) == 64):
                    stats['legacy_sha'] += 1
                elif not _looks_hashed(stored):
                    stats['plaintext'] += 1
                    new_hash = PasswordHasher.hash_password(stored)
                    with pool.get_cursor() as cursor:
                        cursor.execute(
                            'UPDATE users SET password = %s, updated_time = NOW() WHERE id = %s',
                            (new_hash, uid),
                        )
                    stats['fixed'] += 1
                    logger.info(f'密码审计: 用户 {uname!r} 明文已哈希 (id={uid})')
            if stats['fixed']:
                logger.info(f'密码审计完成: {stats}')
        except Exception as e:
            logger.warning(f'密码审计失败: {e}', exc_info=True)
        return stats


_password_service: Optional[PasswordService] = None


def get_password_service(user_manager=None) -> PasswordService:
    global _password_service
    if _password_service is None:
        _password_service = PasswordService(user_manager)
    elif user_manager is not None:
        _password_service._user_manager = user_manager
    return _password_service
