#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pure-function safety tests for material_library_dedupe.py."""

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

import material_library_dedupe as dedupe


def _table(name, data=None):
    return {
        "fileName": f"Yida-sync-{name}.xlsx",
        "updatedAt": "2026-07-23T12:00:00",
        "sourceFormUuid": "FORM-1",
        "sourceTitle": "0402电容(C)",
        "data": data or [["物料代码"], ["A"]],
    }


def _row(identifier, name, history=None, prefix=""):
    return {
        "id": identifier,
        "name": name,
        "prefix": prefix,
        "password_hash": "hash",
        "current_table_json": json.dumps(_table(name), ensure_ascii=False),
        "history_tables_json": json.dumps(history or [], ensure_ascii=False),
        "created_at": "2026-05-01 00:00:00",
        "updated_at": "2026-07-23 12:00:00",
    }


class CurrentTableValidationTests(unittest.TestCase):
    def test_allows_only_library_specific_filename_difference(self):
        legacy = _row("old", "0402电容")
        retained = _row("new", "0402电容(C)")
        self.assertEqual(
            dedupe._validate_current_tables(legacy, retained),
            dedupe._digest([["物料代码"], ["A"]]),
        )

    def test_rejects_any_material_row_difference(self):
        legacy = _row("old", "0402电容")
        retained = _row("new", "0402电容(C)")
        current = json.loads(retained["current_table_json"])
        current["data"][1][0] = "B"
        retained["current_table_json"] = json.dumps(current, ensure_ascii=False)
        with self.assertRaises(dedupe.SafetyError) as caught:
            dedupe._validate_current_tables(legacy, retained)
        self.assertEqual(caught.exception.code, "current_data_mismatch")


class HistoryMergeTests(unittest.TestCase):
    def test_copies_only_data_versions_absent_from_retained_library(self):
        current = _table("0402电容(C)", [["code"], ["current"]])
        common = {
            "fileName": "common.xlsx",
            "updatedAt": "2026-06-01T00:00:00",
            "data": [["code"], ["common"]],
        }
        unique = {
            "fileName": "old-only.xlsx",
            "updatedAt": "2026-05-16T00:00:00",
            "data": [["code"], ["old-only"]],
        }
        legacy = [deepcopy(common), deepcopy(unique), deepcopy(unique)]
        retained = [deepcopy(common)]
        merged, copied = dedupe.merge_unique_history(legacy, retained, current)
        self.assertEqual(len(copied), 1)
        self.assertEqual(len(merged), 2)
        self.assertEqual(
            {entry["data"][1][0] for entry in merged},
            {"common", "old-only"},
        )


class CleanupPlanTests(unittest.TestCase):
    PAIRS = (
        ("0402电容", "0402电容(C)"),
        ("0603电阻", "0603电阻(R)"),
        ("2520功率电感", "2520功率电感(L)"),
    )

    def _complete_rows(self):
        rows = []
        for index, (legacy, retained) in enumerate(self.PAIRS):
            rows.extend(
                [
                    _row(f"old-{index}", legacy),
                    _row(f"new-{index}", retained),
                ]
            )
        rows.append(_row("required", dedupe.REQUIRED_RESTORED_LIBRARY))
        return rows

    def test_safe_complete_plan_targets_only_allowlisted_legacy_names(self):
        plan = dedupe.build_cleanup_plan(self._complete_rows(), [])
        self.assertTrue(plan["safe"])
        self.assertEqual(
            plan["pending_delete_count"], len(self.PAIRS)
        )
        self.assertEqual(
            {
                pair["legacy_name"]
                for pair in plan["pairs"]
                if pair["status"] == "pending_delete"
            },
            {pair[0] for pair in self.PAIRS},
        )

    def test_discovers_full_width_parenthesis_collision(self):
        rows = [
            _row("old", "0603电容"),
            _row("new", "0603电容（C）"),
        ]
        self.assertEqual(
            dedupe.discover_collision_pairs(rows),
            [("0603电容", "0603电容（C）")],
        )

    def test_does_not_discover_uncontrolled_suffix(self):
        rows = [
            _row("old", "自定义库"),
            _row("new", "自定义库(TEST)"),
        ]
        self.assertEqual(dedupe.discover_collision_pairs(rows), [])

    def test_already_clean_database_has_no_dynamic_targets(self):
        rows = [
            _row(f"new-{index}", retained)
            for index, (_, retained) in enumerate(self.PAIRS)
        ]
        rows.append(_row("required", dedupe.REQUIRED_RESTORED_LIBRARY))
        plan = dedupe.build_cleanup_plan(rows, [])
        self.assertTrue(plan["safe"])
        self.assertEqual(plan["collision_pairs"], [])
        self.assertEqual(plan["pending_delete_count"], 0)

    def test_ambiguous_ascii_and_full_width_targets_are_blocked(self):
        rows = [
            _row("old", "0603电容"),
            _row("ascii", "0603电容(C)"),
            _row("full-width", "0603电容（C）"),
            _row("required", dedupe.REQUIRED_RESTORED_LIBRARY),
        ]
        plan = dedupe.build_cleanup_plan(rows, [])
        self.assertFalse(plan["safe"])
        self.assertIn(
            "ambiguous_suffix_collision",
            {error["code"] for error in plan["errors"]},
        )

    def test_permission_reference_blocks_whole_plan(self):
        rows = self._complete_rows()
        legacy = next(row for row in rows if row["name"] == "0402电容")
        plan = dedupe.build_cleanup_plan(
            rows,
            [
                {
                    "id": 7,
                    "username": "manager",
                    "library_roles": legacy["id"],
                }
            ],
        )
        self.assertFalse(plan["safe"])
        pair = next(
            pair for pair in plan["pairs"] if pair["legacy_name"] == "0402电容"
        )
        self.assertEqual(pair["status"], "error")
        self.assertIn(
            "permission_references",
            {error["code"] for error in pair["errors"]},
        )

    def test_missing_required_0805_resistor_blocks_plan(self):
        rows = [
            row
            for row in self._complete_rows()
            if row["name"] != dedupe.REQUIRED_RESTORED_LIBRARY
        ]
        plan = dedupe.build_cleanup_plan(rows, [])
        self.assertFalse(plan["safe"])
        self.assertIn(
            "required_library_missing",
            {error["code"] for error in plan["errors"]},
        )

    def test_cleanup_backup_round_trips_with_integrity_check(self):
        rows = self._complete_rows()
        plan = dedupe.build_cleanup_plan(rows, [])
        document = dedupe._backup_document(
            kind="material-library-dedupe-cleanup",
            plan=plan,
            library_rows=rows,
            users=[],
            audit_rows=[],
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "backup.json"
            dedupe._write_json_backup(document, path)
            loaded = dedupe._load_backup(path)
        self.assertEqual(
            loaded["collision_pairs"],
            [list(pair) for pair in self.PAIRS],
        )
        self.assertEqual(
            loaded["integrity"]["sha256"],
            document["integrity"]["sha256"],
        )


if __name__ == "__main__":
    unittest.main()
