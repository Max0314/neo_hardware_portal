#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""宜搭→物料库 投影测试（阶段2）。默认 dry-run：只拉数据、拆成物料行并预览，不写库。

用法（htmlsystm/ 目录下）：
    export YIDA_SYSTEM_TOKEN=xxxx
    # 预览（不写库）：
    python3 scripts/yida_sync_test.py FORM-XXXX [FORM-YYYY ...]
    # 自动发现所有物料表单并预览：
    python3 scripts/yida_sync_test.py --discover
    # 真正写入物料库（需白名单、YIDA_LIBRARY_PASSWORD 和二次确认）：
    python3 scripts/yida_sync_test.py FORM-XXXX --write --confirm-write
"""
import os
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.yida_config import (  # noqa: E402
    check_yida_config, check_material_sync_config,
    YIDA_MATERIAL_SOURCES, YIDA_SPECIAL_MATERIAL_SOURCES,
)
from server.material_yida_projection import (  # noqa: E402
    build_rows_for_form, sync_form_to_library, discover_material_forms, STANDARD_HEADERS,
)


def preview(form_uuid, name):
    print(f'\n===== {name} ({form_uuid}) =====')
    try:
        built = build_rows_for_form(form_uuid, name,
                                    create_from_gmt='2015-01-01 00:00:00',
                                    create_to_gmt='2099-01-01 00:00:00')
    except Exception as e:
        print(f'  ❌ {e}')
        return
    rows = built['rows']
    print(
        f"  实例 {built['instances']} 条 → 物料 {len(rows)} 行 "
        f"(multi={built['multi']}, 槽位={built['slot_count']}, "
        f"替代组投影={built.get('group_projection')}, 字段={built.get('group_label_fields') or []})"
    )
    print('  表头:', STANDARD_HEADERS)
    for r in rows[:8]:
        print('   ', r)
    if len(rows) > 8:
        print(f'    … 共 {len(rows)} 行')


def main():
    ok, err = check_yida_config()
    if not ok:
        print(f'❌ 配置不完整: {err}'); sys.exit(1)

    args = sys.argv[1:]
    do_write = '--write' in args
    confirmed_write = '--confirm-write' in args
    args = [a for a in args if a not in ('--write', '--confirm-write')]
    if do_write and not confirmed_write:
        print('❌ 拒绝写库：--write 需要同时提供 --confirm-write。默认命令始终只读。')
        sys.exit(2)
    if do_write:
        ok, err = check_material_sync_config()
        if not ok:
            print(f'❌ 拒绝写库：{err}')
            sys.exit(2)

    configured_sources = {
        source.get('form_uuid'): source
        for source in (YIDA_SPECIAL_MATERIAL_SOURCES or []) + (YIDA_MATERIAL_SOURCES or [])
        if source.get('form_uuid')
    }

    if '--discover' in args:
        print('自动发现物料表单中…')
        try:
            all_forms, sources = discover_material_forms(return_all=True)
        except Exception as e:
            print(f'❌ 列出表单失败(GetFormListInApp): {e}')
            sys.exit(1)
        picked_ids = {s['form_uuid'] for s in sources}
        unmatched = [f for f in all_forms if f['form_uuid'] not in picked_ids]
        print(f'应用下共 {len(all_forms)} 张；命中物料优选表 {len(sources)} 张；未命中 {len(unmatched)} 张。')
        print('— 命中的物料表单 —')
        for s in sources:
            print(f"  {s['form_uuid']}  {s['source_name']}")
        print('— 未命中的表单(扫一眼有没有漏掉的物料明细表) —')
        for f in unmatched:
            print(f"  {f['form_uuid']}  {f['title']}  [{f['form_type']}]")
        if not do_write:
            print('\n(仅列出。预览某张：python3 scripts/yida_sync_test.py FORM-xxxx)')
            return
        forms = [(s['form_uuid'], s['library_name']) for s in sources]
    else:
        wanted = [a for a in args if a.startswith('FORM-')]
        if not wanted:
            print('用法: python3 scripts/yida_sync_test.py FORM-xxxx [--write] | --discover'); sys.exit(0)
        # 解析真实表名（否则库名会被写成 form_uuid）
        title_map = {}
        try:
            from server.yida_client import list_forms_in_app
            title_map = {f['form_uuid']: f['title'] for f in list_forms_in_app()}
        except Exception as e:
            print(f'⚠️ 取表名失败，将用 form_uuid 当库名: {e}')
        forms = [(fu, title_map.get(fu) or fu) for fu in wanted]

    if do_write:
        for fu, name in forms:
            source = configured_sources.get(fu)
            if not source:
                print(f'❌ 拒绝写库 {name}: {fu} 不在 YIDA_MATERIAL_FORMS 白名单中')
                continue
            try:
                res = sync_form_to_library(source)
                print(f'✅ 写库: {res}')
            except Exception as e:
                print(f'❌ {name}: {e}')
    else:
        for fu, name in forms:
            preview(fu, name)
        print('\n预览完成（未写库）。确认白名单和投影后，才可加 --write --confirm-write 写库。')


if __name__ == '__main__':
    main()
