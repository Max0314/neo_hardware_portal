# -*- coding: utf-8 -*-
"""object_store 的本地实现与 key 安全校验。

OssStore 的网络行为不在单测覆盖（签名已在生产桶实测），这里保证两个后端
接口一致、key 校验拦住路径穿越、中文文件名可用。
"""
import unittest
import tempfile

from server.object_store import LocalStore, ObjectStoreError, _check_key


class TestKeyValidation(unittest.TestCase):
    def test_rejects_traversal_and_absolute(self):
        for bad in ('', '/abs', 'a/../b', 'a//b', 'a\\b', '../x'):
            with self.assertRaises(ObjectStoreError, msg=bad):
                _check_key(bad)

    def test_accepts_normal_keys(self):
        for ok in ('a.txt', 'a/b/c.json', 'hardware/公告-1/附件 表格.xlsx'):
            self.assertEqual(ok, _check_key(ok))


class TestLocalStore(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = LocalStore(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_put_get_roundtrip_with_chinese_key(self):
        key = 'announcements/公告A/附件/网络模板（绿色列）.xlsx'
        self.store.put_bytes(key, b'\x00\x01data')

        self.assertEqual(b'\x00\x01data', self.store.get_bytes(key))
        self.assertTrue(self.store.exists(key))

    def test_get_missing_returns_none(self):
        self.assertIsNone(self.store.get_bytes('nope/none.bin'))
        self.assertFalse(self.store.exists('nope/none.bin'))

    def test_delete_is_idempotent(self):
        self.store.put_bytes('a/b.txt', b'x')
        self.store.delete('a/b.txt')
        self.store.delete('a/b.txt')  # 第二次不抛

        self.assertFalse(self.store.exists('a/b.txt'))

    def test_iter_keys_and_delete_prefix(self):
        for k in ('p/1.txt', 'p/sub/2.txt', 'q/3.txt'):
            self.store.put_bytes(k, b'x')

        self.assertEqual({'p/1.txt', 'p/sub/2.txt'}, set(self.store.iter_keys('p/')))
        self.assertEqual(2, self.store.delete_prefix('p/'))
        self.assertEqual({'q/3.txt'}, set(self.store.iter_keys('')))

    def test_copy(self):
        self.store.put_bytes('src.txt', b'payload')
        self.store.copy('src.txt', 'dst/copy.txt')

        self.assertEqual(b'payload', self.store.get_bytes('dst/copy.txt'))

    def test_key_cannot_escape_root(self):
        with self.assertRaises(ObjectStoreError):
            self.store.put_bytes('../escape.txt', b'x')


if __name__ == '__main__':
    unittest.main()
