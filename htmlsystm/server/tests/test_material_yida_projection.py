# -*- coding: utf-8 -*-
"""宜搭物料投影的单目标选库测试。"""
import unittest
from unittest.mock import patch

from server import material_yida_projection as projection


class TestSyncTargetLibraryNames(unittest.TestCase):
    def _library(self, name, form_uuid=None, library_id=None):
        current_table = {}
        if form_uuid:
            current_table['sourceFormUuid'] = form_uuid
        return {
            'id': library_id or name,
            'name': name,
            'currentTable': current_table,
        }

    @patch.object(projection.mdb, 'list_libraries')
    def test_exact_yida_title_wins_when_new_and_legacy_libraries_exist(self, list_libraries):
        list_libraries.return_value = [
            self._library('0402电容'),
            self._library('0402电容(C)'),
        ]

        targets = projection._sync_target_library_names('0402电容(C)', 'FORM-CAP-0402')

        self.assertEqual(['0402电容(C)'], targets)

    @patch.object(projection.mdb, 'list_libraries')
    def test_existing_legacy_library_is_reused_without_creating_title_library(self, list_libraries):
        list_libraries.return_value = [self._library('0402电容')]

        targets = projection._sync_target_library_names('0402电容(C)', 'FORM-CAP-0402')

        self.assertEqual(['0402电容'], targets)

    @patch.object(projection.mdb, 'list_libraries')
    def test_yida_title_library_is_created_when_no_candidate_exists(self, list_libraries):
        list_libraries.return_value = []

        targets = projection._sync_target_library_names('0402电容(C)', 'FORM-CAP-0402')

        self.assertEqual(['0402电容(C)'], targets)

    @patch.object(projection.mdb, 'list_libraries')
    def test_same_form_uuid_is_reused_after_yida_form_rename(self, list_libraries):
        list_libraries.return_value = [
            self._library('旧表名(C)', 'FORM-CAP-0402'),
            self._library('新表名(C)', 'FORM-OTHER'),
        ]

        targets = projection._sync_target_library_names('新表名(C)', 'FORM-CAP-0402')

        self.assertEqual(['旧表名(C)'], targets)


class TestSyncFormToLibrary(unittest.TestCase):
    @patch.object(projection.mdb, 'batch_import_libraries')
    @patch.object(projection.mdb, 'list_libraries')
    @patch.object(projection, 'build_rows_for_form')
    def test_sync_writes_one_target_with_yida_source_metadata(
        self,
        build_rows_for_form,
        list_libraries,
        batch_import_libraries,
    ):
        build_rows_for_form.return_value = {
            'rows': [['M001', '0402电容', '', '', 'group-1', '优选', '']],
            'instances': 1,
            'multi': True,
            'slot_count': 1,
            'group_projection': 'instance_key',
            'group_label_fields': [],
        }
        list_libraries.return_value = [
            self._library('0402电容'),
            self._library('0402电容(C)'),
        ]
        batch_import_libraries.return_value = {
            'created': 0,
            'updated': 1,
            'skipped': 0,
            'unchanged': 0,
        }
        source = {
            'form_uuid': 'FORM-CAP-0402',
            'source_name': '0402电容(C)',
            'library_name': '0402电容(C)',
        }

        result = projection.sync_form_to_library(source, password='test-password')

        self.assertEqual(['0402电容(C)'], result['target_libraries'])
        items = batch_import_libraries.call_args.args[0]
        self.assertEqual(1, len(items))
        self.assertEqual('0402电容(C)', items[0]['name'])
        current_table = items[0]['currentTable']
        self.assertEqual('FORM-CAP-0402', current_table['sourceFormUuid'])
        self.assertEqual('0402电容(C)', current_table['sourceTitle'])
        self.assertTrue(
            batch_import_libraries.call_args.kwargs['skip_unchanged_history']
        )

    @patch.object(projection.mdb, 'batch_import_libraries')
    @patch.object(projection.mdb, 'list_libraries')
    @patch.object(projection, 'build_rows_for_form')
    def test_configured_library_name_override_is_preserved(
        self,
        build_rows_for_form,
        list_libraries,
        batch_import_libraries,
    ):
        build_rows_for_form.return_value = {
            'rows': [['M001', '自定义物料', '', '', '', '', '']],
            'instances': 1,
            'multi': False,
            'slot_count': 1,
            'group_projection': 'field',
            'group_label_fields': [],
        }
        list_libraries.return_value = []
        batch_import_libraries.return_value = {
            'created': 1,
            'updated': 0,
            'skipped': 0,
            'unchanged': 0,
        }
        source = {
            'form_uuid': 'FORM-CUSTOM',
            'source_name': '宜搭源表标题',
            'library_name': '门户配置库名',
        }

        result = projection.sync_form_to_library(source, password='test-password')

        build_args = build_rows_for_form.call_args.args
        self.assertEqual('门户配置库名', build_args[1])
        items = batch_import_libraries.call_args.args[0]
        self.assertEqual('门户配置库名', items[0]['name'])
        self.assertEqual('宜搭源表标题', items[0]['currentTable']['sourceTitle'])
        self.assertEqual('门户配置库名', result['library'])

    @patch.object(projection.mdb, 'batch_import_libraries')
    @patch.object(projection.mdb, 'list_libraries')
    @patch.object(projection, 'build_rows_for_form')
    def test_empty_projection_never_overwrites_existing_library(
        self,
        build_rows_for_form,
        list_libraries,
        batch_import_libraries,
    ):
        build_rows_for_form.return_value = {
            'rows': [], 'instances': 2, 'multi': False, 'slot_count': 1,
            'group_projection': 'field', 'group_label_fields': [],
        }
        list_libraries.return_value = [{
            'id': 'library-id', 'name': '0402电容(C)',
            'currentTable': {'data': [['物料代码'], ['OLD-001']]},
        }]

        with self.assertRaises(projection.YidaSyncSafetyError) as ctx:
            projection.sync_form_to_library({
                'form_uuid': 'FORM-CAP-0402',
                'source_name': '0402电容(C)',
                'library_name': '0402电容(C)',
            }, password='test-password')

        self.assertIn('未覆盖任何物料库', str(ctx.exception))
        # 读到了实例、只是物料代码为空 —— 要指向源表填写，而不是权限
        self.assertIn('2 条实例', str(ctx.exception))
        self.assertIn('物料代码字段全部为空', str(ctx.exception))

    @patch('server.material_db_manager.batch_import_libraries')
    @patch('server.material_db_manager.list_libraries')
    @patch('server.material_yida_projection.build_rows_for_form')
    def test_zero_instances_reports_permission_not_empty_codes(
        self,
        build_rows_for_form,
        list_libraries,
        batch_import_libraries,
    ):
        """一条实例都没读到，最常见的原因是查询人没有该表单的数据权限。

        这两种空结果必须给出不同的排查方向：混成一句会把权限问题误导成源表没填数据，
        2026-08-01 的事故正是这样被延误的。
        """
        build_rows_for_form.return_value = {
            'rows': [], 'instances': 0, 'multi': False, 'slot_count': 1,
            'group_projection': 'field', 'group_label_fields': [],
        }
        list_libraries.return_value = [{
            'id': 'library-id', 'name': '0402电容(C)',
            'currentTable': {'data': [['物料代码'], ['OLD-001']]},
        }]

        with self.assertRaises(projection.YidaSyncSafetyError) as ctx:
            projection.sync_form_to_library({
                'form_uuid': 'FORM-CAP-0402',
                'source_name': '0402电容(C)',
                'library_name': '0402电容(C)',
            }, password='test-password')

        message = str(ctx.exception)
        self.assertIn('未读到任何实例', message)
        self.assertIn('YIDA_QUERY_USER_ID', message)
        self.assertNotIn('物料代码字段全部为空', message)
        batch_import_libraries.assert_not_called()
        batch_import_libraries.assert_not_called()

    @patch.object(projection.mdb, 'batch_import_libraries')
    @patch.object(projection.mdb, 'list_libraries')
    @patch.object(projection, 'build_rows_for_form')
    def test_large_row_drop_never_overwrites_existing_library(
        self,
        build_rows_for_form,
        list_libraries,
        batch_import_libraries,
    ):
        build_rows_for_form.return_value = {
            'rows': [['NEW-001', '', '', '', '', '', '']], 'instances': 1,
            'multi': False, 'slot_count': 1, 'group_projection': 'field',
            'group_label_fields': [],
        }
        list_libraries.return_value = [{
            'id': 'library-id', 'name': '0402电容(C)',
            'currentTable': {'data': [['物料代码']] + [[f'OLD-{i}'] for i in range(20)]},
        }]

        with self.assertRaises(projection.YidaSyncSafetyError) as ctx:
            projection.sync_form_to_library({
                'form_uuid': 'FORM-CAP-0402',
                'source_name': '0402电容(C)',
                'library_name': '0402电容(C)',
            }, password='test-password')

        self.assertIn('行数异常下降', str(ctx.exception))
        batch_import_libraries.assert_not_called()

    @staticmethod
    def _library(name):
        return {'id': name, 'name': name, 'currentTable': {}}


if __name__ == '__main__':
    unittest.main()
