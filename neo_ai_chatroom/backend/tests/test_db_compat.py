# -*- coding: utf-8 -*-
"""db_compat 适配层的纯逻辑测试（不连数据库）。

连接行为由部署前的真实环境验证覆盖；这里只锁定两类最容易悄悄出错的逻辑：
占位符翻译和 Row 的双形态访问。
"""
import unittest

from backend.models.db_compat import Row, _translate


class TestTranslate(unittest.TestCase):
    def test_question_marks_become_pyformat(self):
        self.assertEqual(
            "SELECT * FROM t WHERE a = %s AND b = %s",
            _translate("SELECT * FROM t WHERE a = ? AND b = ?"),
        )

    def test_literal_percent_is_escaped(self):
        """LIKE '%x%' 这类字面 % 必须翻倍，否则 pymysql 会当格式化符解析。"""
        self.assertEqual(
            "SELECT * FROM t WHERE s LIKE '%%已完成%%' AND id = %s",
            _translate("SELECT * FROM t WHERE s LIKE '%已完成%' AND id = ?"),
        )

    def test_no_placeholders_passthrough(self):
        self.assertEqual("SELECT 1", _translate("SELECT 1"))


class TestRow(unittest.TestCase):
    def setUp(self):
        self.row = Row(["id", "name", "count"], ("u-1", "巴巴塔", 3))

    def test_access_by_name_and_index(self):
        self.assertEqual("u-1", self.row["id"])
        self.assertEqual("巴巴塔", self.row[1])
        self.assertEqual(3, self.row["count"])

    def test_dict_conversion_preserves_order(self):
        self.assertEqual({"id": "u-1", "name": "巴巴塔", "count": 3}, dict(self.row))

    def test_iteration_and_len(self):
        self.assertEqual(["u-1", "巴巴塔", 3], list(self.row))
        self.assertEqual(3, len(self.row))

    def test_contains_and_get(self):
        self.assertIn("name", self.row)
        self.assertIsNone(self.row.get("missing"))


if __name__ == "__main__":
    unittest.main()
