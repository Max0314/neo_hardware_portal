# -*- coding: utf-8 -*-
"""TreeMirror 写通镜像语义。远端用 LocalStore 顶替，验证的是镜像逻辑本身。"""
import os
import tempfile
import unittest

from server.object_store import LocalStore
from server.tree_mirror import TreeMirror


def _write(root, rel, data=b'x'):
    path = os.path.join(root, rel.replace('/', os.sep))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as fh:
        fh.write(data)


class TestTreeMirror(unittest.TestCase):
    def setUp(self):
        self._local = tempfile.TemporaryDirectory()
        self._remote = tempfile.TemporaryDirectory()
        self.remote = LocalStore(self._remote.name)
        self.mirror = TreeMirror(self._local.name, self.remote)

    def tearDown(self):
        self._local.cleanup()
        self._remote.cleanup()

    def test_sync_uploads_new_and_changed_only(self):
        _write(self._local.name, 'hw/a1/metadata.json', b'v1')
        _write(self._local.name, 'hw/a1/attachments/文 件.bin', b'bin')

        up, rm, errs = self.mirror.sync_subtree('hw/a1')
        self.assertEqual((2, 0, []), (up, rm, errs))

        # 未变更 → 全跳过
        up, rm, _ = self.mirror.sync_subtree('hw/a1')
        self.assertEqual((0, 0), (up, rm))

        # 变更一个 → 只传一个
        _write(self._local.name, 'hw/a1/metadata.json', b'v2')
        up, _, _ = self.mirror.sync_subtree('hw/a1')
        self.assertEqual(1, up)
        self.assertEqual(b'v2', self.remote.get_bytes('hw/a1/metadata.json'))

    def test_sync_of_vanished_dir_cleans_remote(self):
        _write(self._local.name, 'hw/a2/content.html', b'c')
        self.mirror.sync_subtree('hw/a2')
        self.assertTrue(self.remote.exists('hw/a2/content.html'))

        # 本地删除后再同步同一前缀 → 远端跟着清空（删除/移动共用此语义）
        import shutil
        shutil.rmtree(os.path.join(self._local.name, 'hw', 'a2'))
        up, rm, _ = self.mirror.sync_subtree('hw/a2')

        self.assertEqual((0, 1), (up, rm))
        self.assertFalse(self.remote.exists('hw/a2/content.html'))

    def test_locks_and_temp_files_are_not_mirrored(self):
        _write(self._local.name, 'hw/a3/metadata.json', b'm')
        _write(self._local.name, 'hw/a3/metadata.json.lock', b'')
        _write(self._local.name, 'hw/a3/x.tmp', b'')
        _write(self._local.name, 'locks/scheduler.lock', b'')

        self.mirror.sync_subtree('hw/a3')
        self.mirror.reconcile()

        self.assertEqual({'hw/a3/metadata.json'}, set(self.remote.iter_keys('')))

    def test_extra_excludes_for_vector_artifacts(self):
        mirror = TreeMirror(self._local.name, self.remote,
                            exclude_suffixes=('.sqlite3',))
        _write(self._local.name, 'kb/custom-r_knowledge.json', b'{}')
        _write(self._local.name, 'kb/custom-r/chroma.sqlite3', b'\x00')

        mirror.reconcile()

        self.assertEqual({'kb/custom-r_knowledge.json'}, set(self.remote.iter_keys('')))

    def test_prefixes_containing_finds_old_location(self):
        _write(self._local.name, 'boardA/aid-9/metadata.json', b'm')
        self.mirror.sync_subtree('boardA/aid-9')

        self.assertEqual(['boardA/aid-9'], self.mirror.prefixes_containing('aid-9'))

    def test_restore_all_pulls_tree_when_local_empty(self):
        self.remote.put_bytes('hw/a4/content.html', b'html')
        self.remote.put_bytes('hw/a4/attachments/中文.xlsx', b'xls')

        n = self.mirror.restore_all()

        self.assertEqual(2, n)
        with open(os.path.join(self._local.name, 'hw', 'a4', 'content.html'), 'rb') as fh:
            self.assertEqual(b'html', fh.read())

    def test_restore_all_refuses_when_local_has_files(self):
        """本地有数据时绝不用远端覆盖——防止旧备份冲掉新数据。"""
        _write(self._local.name, 'hw/a5/content.html', b'newer-local')
        self.remote.put_bytes('hw/a5/content.html', b'older-remote')

        self.assertEqual(0, self.mirror.restore_all())
        with open(os.path.join(self._local.name, 'hw', 'a5', 'content.html'), 'rb') as fh:
            self.assertEqual(b'newer-local', fh.read())

    def test_reconcile_heals_missed_sync_and_stale_remote(self):
        _write(self._local.name, 'hw/a6/metadata.json', b'm')   # 漏传
        self.remote.put_bytes('hw/gone/old.txt', b'stale')      # 本地已无
        # 让镜像先"记住"过 stale 对象（模拟历史同步）
        _write(self._local.name, 'hw/gone/old.txt', b'stale')
        self.mirror.sync_subtree('hw/gone')
        os.remove(os.path.join(self._local.name, 'hw', 'gone', 'old.txt'))
        os.removedirs(os.path.join(self._local.name, 'hw', 'gone'))

        up, rm = self.mirror.reconcile()

        self.assertGreaterEqual(up, 1)
        self.assertEqual(1, rm)
        self.assertTrue(self.remote.exists('hw/a6/metadata.json'))
        self.assertFalse(self.remote.exists('hw/gone/old.txt'))

    def test_none_store_is_inert(self):
        mirror = TreeMirror(self._local.name, None)
        _write(self._local.name, 'hw/a7/x.txt', b'x')

        self.assertEqual((0, 0, []), mirror.sync_subtree('hw/a7'))
        self.assertEqual(0, mirror.delete_subtree('hw/a7'))
        self.assertEqual(0, mirror.restore_all())
        self.assertEqual((0, 0), mirror.reconcile())


if __name__ == '__main__':
    unittest.main()
