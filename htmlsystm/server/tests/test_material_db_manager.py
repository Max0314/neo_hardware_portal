# -*- coding: utf-8 -*-
"""物料库批量导入历史版本行为测试。"""
import unittest
from unittest.mock import MagicMock, patch

from server import material_db_manager as mdb


class TestTableDataComparison(unittest.TestCase):
    def test_compares_only_table_data(self):
        current = {
            'fileName': 'old.xlsx',
            'updatedAt': '2026-07-22T10:00:00',
            'data': [['code'], ['A001']],
        }
        incoming = {
            'fileName': 'new.xlsx',
            'updatedAt': '2026-07-23T10:00:00',
            'data': [['code'], ['A001']],
        }

        self.assertTrue(mdb._same_table_data(current, incoming))

    def test_missing_or_different_data_is_not_unchanged(self):
        self.assertFalse(mdb._same_table_data(None, None))
        self.assertFalse(mdb._same_table_data({}, {}))
        self.assertFalse(
            mdb._same_table_data(
                {'data': [['code'], ['A001']]},
                {'data': [['code'], ['A002']]},
            )
        )


class TestBatchImportUnchangedHistory(unittest.TestCase):
    def setUp(self):
        self.cursor = MagicMock()
        self.pool = MagicMock()
        self.pool.get_cursor.return_value.__enter__.return_value = self.cursor
        self.existing = {
            'id': 'lib-1',
            'name': '0402电容(C)',
            'prefix': '',
            'currentTable': {
                'fileName': 'old.xlsx',
                'updatedAt': '2026-07-22T10:00:00',
                'data': [['code'], ['C001']],
            },
            'historyTables': [
                {
                    'fileName': 'older.xlsx',
                    'updatedAt': '2026-07-21T10:00:00',
                    'data': [['code'], ['C000']],
                }
            ],
        }
        self.incoming = {
            'name': '0402电容(C)',
            'currentTable': {
                'fileName': 'Yida-sync-0402电容(C).xlsx',
                'updatedAt': '2026-07-23T10:00:00',
                'data': [['code'], ['C001']],
            },
        }

    def _run_import(self, skip_unchanged_history=None):
        with (
            patch.object(mdb, 'ensure_material_password_hash'),
            patch.object(mdb, 'list_libraries', return_value=[self.existing]),
            patch.object(mdb, 'get_connection_pool', return_value=self.pool),
            patch.object(mdb, 'log_audit'),
            patch.object(mdb, '_now_str', return_value='2026-07-23 10:00:00'),
        ):
            kwargs = {}
            if skip_unchanged_history is not None:
                kwargs['skip_unchanged_history'] = skip_unchanged_history
            return mdb.batch_import_libraries(
                [self.incoming],
                overwrite=True,
                default_prefix='',
                default_password='',
                user_id=1,
                user_display='tester',
                **kwargs,
            )

    def _update_parameters(self):
        self.assertEqual(self.cursor.execute.call_count, 1)
        return self.cursor.execute.call_args.args[1]

    def test_unchanged_data_refreshes_current_metadata_without_new_history(self):
        stats = self._run_import(skip_unchanged_history=True)
        params = self._update_parameters()

        self.assertEqual(
            stats,
            {'created': 0, 'updated': 0, 'skipped': 0, 'unchanged': 1},
        )
        self.assertIn('"fileName": "Yida-sync-0402电容(C).xlsx"', params[1])
        self.assertIn('"updatedAt": "2026-07-23T10:00:00"', params[1])
        self.assertNotIn('"fileName": "old.xlsx"', params[2])
        self.assertIn('"fileName": "older.xlsx"', params[2])

    def test_default_behavior_still_creates_history(self):
        stats = self._run_import()
        params = self._update_parameters()

        self.assertEqual(
            stats,
            {'created': 0, 'updated': 1, 'skipped': 0, 'unchanged': 0},
        )
        self.assertIn('"fileName": "old.xlsx"', params[2])
        self.assertIn('"fileName": "older.xlsx"', params[2])

    def test_changed_data_still_creates_history_when_skip_is_enabled(self):
        self.incoming['currentTable']['data'] = [['code'], ['C002']]

        stats = self._run_import(skip_unchanged_history=True)
        params = self._update_parameters()

        self.assertEqual(
            stats,
            {'created': 0, 'updated': 1, 'skipped': 0, 'unchanged': 0},
        )
        self.assertIn('"fileName": "old.xlsx"', params[2])


if __name__ == '__main__':
    unittest.main()
