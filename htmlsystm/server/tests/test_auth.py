# -*- coding: utf-8 -*-
"""账号与权限单元测试。"""
import unittest
from unittest.mock import MagicMock, patch

from server.auth.permissions import is_super_admin, check_access, has_any_role
from server.auth.capabilities import user_capabilities
from server.security import PasswordHasher, InputValidator


class TestPermissions(unittest.TestCase):
    def test_super_admin_by_role(self):
        user = {'username': 'alice', 'roles': ['super_admin', 'admin']}
        self.assertTrue(is_super_admin(user))

    def test_super_admin_by_env_username(self):
        user = {'username': 'zzw', 'roles': ['admin']}
        self.assertTrue(is_super_admin(user))

    def test_not_super_admin(self):
        user = {'username': 'bob', 'roles': ['user']}
        self.assertFalse(is_super_admin(user))

    def test_check_access_super_admin(self):
        user = {'username': 'x', 'roles': ['user']}
        r = check_access(user, super_admin=True)
        self.assertFalse(r.allowed)
        self.assertEqual(r.status, 403)

    def test_capabilities(self):
        caps = user_capabilities({'username': 'a', 'roles': ['management']})
        self.assertTrue(caps['canApproveRegistrations'])
        self.assertFalse(caps['canManageAccounts'])


class TestPasswordValidation(unittest.TestCase):
    def test_strong_password(self):
        ok, err = InputValidator.validate_password('Abcdefgh123!@', check_strength=True)
        self.assertTrue(ok, err)

    def test_weak_password(self):
        ok, _ = InputValidator.validate_password('123456', check_strength=True)
        self.assertFalse(ok)

    def test_bcrypt_roundtrip(self):
        h = PasswordHasher.hash_password('TestPass123!@#')
        self.assertTrue(PasswordHasher.verify_password('TestPass123!@#', h))
        self.assertFalse(PasswordHasher.verify_password('wrong', h))
        self.assertFalse(PasswordHasher.verify_password('plain', 'plain'))


class TestSuperAdminBootstrap(unittest.TestCase):
    def test_insert_sql_has_no_role_column(self):
        import os
        path = os.path.join(os.path.dirname(__file__), '..', 'user_manager.py')
        with open(path, 'r', encoding='utf-8') as f:
            src = f.read()
        idx = src.find('def _ensure_super_admin')
        block = src[idx:idx + 4000]
        self.assertIn('INSERT INTO users', block)
        self.assertNotIn(' department, role, roles', block)


class TestDingtalkPassword(unittest.TestCase):
    @patch('server.db_adapter.get_connection_pool')
    def test_new_user_uses_hashed_default(self, mock_pool):
        from server.auth.password_service import PasswordService, DEFAULT_DINGTALK_PASSWORD
        h = PasswordService.default_password_hash()
        self.assertTrue(h.startswith('$2b$') or h.startswith('sha512:'))
        self.assertTrue(PasswordHasher.verify_password(DEFAULT_DINGTALK_PASSWORD, h))


if __name__ == '__main__':
    unittest.main()
