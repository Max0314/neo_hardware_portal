# -*- coding: utf-8 -*-
"""把被空同步清空的物料库当前表，从各自最近一个非空历史版本恢复回来。

一次错误的宜搭同步把当前表覆盖成了只有表头的空表，真实数据被压入历史版本。本脚本
逐库找出最近一个非空历史版本并还原为当前表；历史版本本身保持不动，不删除任何数据。

用法::

    # 只读：打印恢复计划，不写库（默认行为）
    python3 scripts/material_restore_from_history.py

    # 只看某几个库
    python3 scripts/material_restore_from_history.py --library "0402电阻(R)"

    # 真正恢复：需要双确认
    python3 scripts/material_restore_from_history.py --apply --confirm-restore

恢复前请先备份 material_db_libraries 表。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import material_db_manager as mdb  # noqa: E402
from server.db_adapter import get_connection_pool  # noqa: E402


def _rows(table: Any) -> int:
    """物料表数据行数；表头不计入，损坏或旧格式按 0 行处理。"""
    if not isinstance(table, dict):
        return 0
    data = table.get('data')
    if not isinstance(data, list):
        return 0
    return max(len(data) - 1, 0)


def _pick_history(history: List[Any]) -> Optional[Dict[str, Any]]:
    """取最近一个非空历史版本。历史按新→旧排列，因此顺序扫描即可。"""
    for index, item in enumerate(history or []):
        if _rows(item) > 0:
            return {'index': index, 'table': item, 'rows': _rows(item)}
    return None


def build_plan(only: Optional[List[str]] = None) -> Dict[str, List[Dict[str, Any]]]:
    """只读扫描全部物料库，分类出可恢复、无需恢复和无法恢复的库。"""
    wanted = {name.strip() for name in (only or []) if name.strip()}
    restorable, skipped, unrecoverable = [], [], []

    for lib in mdb.list_libraries():
        name = (lib.get('name') or '').strip()
        if wanted and name not in wanted:
            continue
        cur_rows = _rows(lib.get('currentTable'))
        entry = {'id': lib.get('id'), 'name': name, 'cur_rows': cur_rows}

        if cur_rows > 0:
            skipped.append(entry)
            continue

        candidate = _pick_history(lib.get('historyTables') or [])
        if not candidate:
            entry['hist_n'] = len(lib.get('historyTables') or [])
            unrecoverable.append(entry)
            continue

        entry.update({
            'hist_index': candidate['index'],
            'hist_rows': candidate['rows'],
            'hist_at': (candidate['table'] or {}).get('updatedAt'),
            'hist_file': (candidate['table'] or {}).get('fileName'),
            '_table': candidate['table'],
        })
        restorable.append(entry)

    missing = wanted - {
        e['name'] for group in (restorable, skipped, unrecoverable) for e in group
    }
    return {
        'restorable': restorable,
        'skipped': skipped,
        'unrecoverable': unrecoverable,
        'missing': [{'name': n} for n in sorted(missing)],
    }


def restore_one(entry: Dict[str, Any], user_display: str) -> None:
    """把选中的历史版本写回当前表。历史列表保持原样，不移除该版本。"""
    table = dict(entry['_table'])
    table.pop('rowCount', None)
    table.setdefault('fileName', f"历史恢复-{entry['name']}.xlsx")
    table['updatedAt'] = mdb._now_str()
    table['restoredFrom'] = {
        'historyIndex': entry['hist_index'],
        'originalUpdatedAt': entry.get('hist_at'),
        'rows': entry['hist_rows'],
    }

    pool = get_connection_pool()
    with pool.get_cursor() as cursor:
        cursor.execute(
            'UPDATE material_db_libraries SET current_table_json=%s, updated_at=%s WHERE id=%s',
            (json.dumps(table, ensure_ascii=False), mdb._now_str(), entry['id']),
        )
    mdb.log_audit(
        None, user_display, 'upload_table', entry['id'], entry['name'],
        {
            'source': 'restore_from_history',
            'historyIndex': entry['hist_index'],
            'rows': entry['hist_rows'],
            'originalUpdatedAt': entry.get('hist_at'),
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description='从历史版本恢复被清空的物料库当前表')
    parser.add_argument('--library', action='append', default=[],
                        help='只处理指定库名，可重复；省略则处理全部')
    parser.add_argument('--apply', action='store_true', help='真正写库')
    parser.add_argument('--confirm-restore', action='store_true',
                        help='与 --apply 同时提供才会写库')
    parser.add_argument('--user', default='历史恢复脚本', help='审计日志中记录的操作者')
    args = parser.parse_args()

    if args.apply and not args.confirm_restore:
        print('❌ 拒绝写库：--apply 需要同时提供 --confirm-restore。默认命令始终只读。')
        sys.exit(2)

    plan = build_plan(args.library)

    if plan['missing']:
        print(f"⚠️  以下库名不存在：{'、'.join(e['name'] for e in plan['missing'])}\n")

    print(f"可恢复 {len(plan['restorable'])} 个库：")
    total = 0
    for e in sorted(plan['restorable'], key=lambda x: -x['hist_rows']):
        total += e['hist_rows']
        print(f"  {e['name']:<28} 当前 {e['cur_rows']:>4} 行 → 恢复 {e['hist_rows']:>4} 行"
              f"  (历史[{e['hist_index']}] @ {e['hist_at']})")
    print(f"  合计将恢复 {total} 行\n")

    if plan['unrecoverable']:
        print(f"无法从历史恢复 {len(plan['unrecoverable'])} 个库（所有历史版本均为空）：")
        for e in plan['unrecoverable']:
            print(f"  {e['name']:<28} 历史版本 {e['hist_n']} 个，全部 0 行")
        print()

    print(f"当前表非空、跳过 {len(plan['skipped'])} 个库\n")

    if not args.apply:
        print('以上为只读计划，未写库。确认无误后加 --apply --confirm-restore 执行恢复。')
        return

    if not plan['restorable']:
        print('没有可恢复的库，未写库。')
        return

    done = 0
    for e in plan['restorable']:
        try:
            restore_one(e, args.user)
            done += 1
            print(f"✅ 已恢复 {e['name']}：{e['hist_rows']} 行")
        except Exception as exc:  # 单库失败不影响其余库
            print(f"❌ 恢复失败 {e['name']}: {exc}")
    print(f"\n恢复完成：{done}/{len(plan['restorable'])} 个库。历史版本未删除。")


if __name__ == '__main__':
    main()
