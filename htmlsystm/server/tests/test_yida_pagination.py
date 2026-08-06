# -*- coding: utf-8 -*-
"""宜搭实例分页与查询人配置的回归测试。

背景：`total` 的解析曾因运算符优先级失效并回退成本页长度，翻页循环又用
`seen >= total` 提前结束，于是每张表单只同步了第一页 100 条。实测某表单
321 条实例只同步到 100 条。
"""
import unittest
from unittest.mock import patch

from server import yida_client
from server import yida_config


class TestInstanceTotalParsing(unittest.TestCase):
    def _search(self, payload):
        with patch.object(yida_client, '_post_json', return_value=payload), \
             patch.object(yida_client, 'get_access_token', return_value='tok'):
            return yida_client.search_form_instances('FORM-X')

    def test_reads_top_level_total_count(self):
        """宜搭实际返回 {currentPage, data, totalCount}，总数在顶层。"""
        instances, total = self._search(
            {'currentPage': 1, 'data': [{'a': 1}] * 100, 'totalCount': 321}
        )

        self.assertEqual(100, len(instances))
        self.assertEqual(321, total)

    def test_reads_nested_total_count(self):
        instances, total = self._search({'result': {'data': [{'a': 1}], 'totalCount': 7}})

        self.assertEqual(1, len(instances))
        self.assertEqual(7, total)

    def test_zero_total_is_not_replaced_by_page_length(self):
        """0 是合法总数；用 `or` 串联候选值会把它当成缺失。"""
        _, total = self._search({'data': [], 'totalCount': 0})

        self.assertEqual(0, total)

    def test_falls_back_to_page_length_when_total_absent(self):
        _, total = self._search({'data': [{'a': 1}, {'a': 2}]})

        self.assertEqual(2, total)


class TestFirstNotNone(unittest.TestCase):
    def test_zero_wins_over_later_values(self):
        self.assertEqual(0, yida_client._first_not_none(None, 0, 99))

    def test_all_none_returns_none(self):
        self.assertIsNone(yida_client._first_not_none(None, None))


class TestInstancePagination(unittest.TestCase):
    def test_keeps_paging_when_total_is_under_reported(self):
        """即使 total 被低报成一页的长度，也必须继续翻页直到出现不满页。"""
        pages = [
            ([{'i': n} for n in range(100)], 100),   # total 低报为 100
            ([{'i': n} for n in range(100, 200)], 100),
            ([{'i': n} for n in range(200, 250)], 100),  # 不满页 → 结束
        ]
        calls = []

        def fake_search(form_uuid, **kwargs):
            calls.append(kwargs['current_page'])
            return pages[kwargs['current_page'] - 1]

        with patch.object(yida_client, 'search_form_instances', side_effect=fake_search), \
             patch.object(yida_client, 'get_access_token', return_value='tok'):
            got = list(yida_client.iter_form_instances('FORM-X', page_size=100))

        self.assertEqual([1, 2, 3], calls)
        self.assertEqual(250, len(got))

    def test_stops_on_short_first_page(self):
        with patch.object(yida_client, 'search_form_instances',
                          return_value=([{'i': 1}], 1)), \
             patch.object(yida_client, 'get_access_token', return_value='tok'):
            got = list(yida_client.iter_form_instances('FORM-X', page_size=100))

        self.assertEqual(1, len(got))

    def test_warns_instead_of_silently_truncating_at_max_pages(self):
        full_page = [{'i': n} for n in range(100)]
        with patch.object(yida_client, 'search_form_instances',
                          return_value=(full_page, 999999)), \
             patch.object(yida_client, 'get_access_token', return_value='tok'), \
             patch.object(yida_client.logger, 'warning') as warn:
            got = list(yida_client.iter_form_instances('FORM-X', page_size=100, max_pages=3))

        self.assertEqual(300, len(got))
        self.assertEqual(1, warn.call_count)
        self.assertIn('最大页数', warn.call_args[0][0])


class TestQueryUserRequired(unittest.TestCase):
    def test_missing_query_user_is_rejected(self):
        """查询人不能再有硬编码兜底：缺失时必须显式报错而不是静默取不到数据。"""
        config = dict(
            yida_config.YIDA_CONFIG,
            system_token='tok', app_type='APP_X', query_user_id='',
        )
        with patch.object(yida_config, 'YIDA_CONFIG', config):
            ok, message = yida_config.check_yida_config()

        self.assertFalse(ok)
        self.assertIn('YIDA_QUERY_USER_ID', message)

    def test_configured_query_user_passes(self):
        config = dict(
            yida_config.YIDA_CONFIG,
            system_token='tok', app_type='APP_X', query_user_id='123',
        )
        with patch.object(yida_config, 'YIDA_CONFIG', config):
            ok, message = yida_config.check_yida_config()

        self.assertTrue(ok)
        self.assertIsNone(message)


if __name__ == '__main__':
    unittest.main()
