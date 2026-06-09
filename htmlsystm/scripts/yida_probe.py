#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""宜搭对接“探针”——部署后在 htmlsystm 目录运行，验证整条链路并确认字段映射方式。

它做三件事：
  1) 验证钉钉鉴权能否拿到 access_token；
  2) 对每张表尝试“获取表单字段定义(schema)”并按中文标题自动映射 4 个目标字段
     （物料代码/物料描述/优选情况/替代组标签）—— 成功则 80+ 张表零手工配置；
  3) 兜底再拉一条样本实例，打印字段ID→示例值（schema 不可用时据此人工对字段）。

用法（在 htmlsystm/ 目录下）：
    export YIDA_SYSTEM_TOKEN=xxxx          # 宜搭系统令牌
    # 钉钉密钥沿用现有 DINGTALK_CLIENT_SECRET
    python scripts/yida_probe.py FORM-XXXX [FORM-YYYY ...]
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.yida_config import YIDA_CONFIG, YIDA_MATERIAL_SOURCES, MATERIAL_TARGET_LABELS, check_yida_config  # noqa: E402
from server.yida_client import (  # noqa: E402
    get_access_token, search_form_instances, extract_instance_meta,
    get_form_schema, auto_map_material_fields,
)


def _preview(v, n=60):
    s = '' if v is None else str(v)
    s = s.replace('\n', ' ')
    return s if len(s) <= n else s[:n] + '…'


def probe_form(form_uuid, token):
    print(f'\n========== 表单 {form_uuid} ==========')

    # 1) 字段定义 + 按标题自动映射
    schema_ok = False
    try:
        fields, used_url = get_form_schema(form_uuid, access_token=token)
        schema_ok = True
        print(f'  [schema] OK，endpoint = {used_url.split("?")[0]}')
        print('  字段ID → 标题:')
        for f in fields:
            pid = f.get('parent_id')
            tail = f"  [{f.get('type')}]" + (f"  ↳子表单@{pid}" if pid else '')
            print(f"    {f['field_id']:34s} = {f.get('label') or '(无标题)'}{tail}")
        mapping, unmatched = auto_map_material_fields(fields)
        print('  —— 自动映射结果 ——')
        for std, labels in MATERIAL_TARGET_LABELS.items():
            fid = mapping.get(std)
            print(f"    {std:18s} -> {fid or '❌ 未匹配 (标题候选: ' + '/'.join(labels) + ')'}")
        if unmatched:
            print(f'  ⚠️ 未匹配的目标字段: {unmatched}（该表标题可能特殊，需手工 field_map 覆盖）')
        else:
            print('  ✅ 4 个目标字段全部自动匹配成功')
    except Exception as e:
        print(f'  [schema] ❌ 获取字段定义失败:\n    {e}')

    # 2) 样本实例（兜底；schema 不可用时据此人工对字段）
    now = datetime.now()
    try:
        instances, total = search_form_instances(
            form_uuid, current_page=1, page_size=3,
            create_from_gmt='2018-01-01 00:00:00',
            create_to_gmt=(now + timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S'),
            access_token=token,
        )
    except Exception as e:
        print(f'  [实例] ❌ 查询失败: {e}')
        return
    print(f'  [实例] 窗口内总数: {total}，取样 {len(instances)} 条')
    if not instances:
        print('  ⚠️ 没取到实例（时间窗/权限/formUuid 可能不对）')
        return
    if not schema_ok:
        meta = extract_instance_meta(instances[0])
        fd = meta.get('form_data') or {}
        print('  —— 字段ID → 示例值（schema 不可用，请据值人工对字段）——')
        for fid in sorted(fd.keys()):
            print(f'    {fid:34s} = {_preview(fd[fid])}')


def main():
    ok, err = check_yida_config()
    if not ok:
        print(f'❌ 配置不完整: {err}')
        sys.exit(1)
    print(f"宜搭 appType={YIDA_CONFIG['app_type']}  userId={YIDA_CONFIG['query_user_id']}  systemToken={'已配置' if YIDA_CONFIG['system_token'] else '缺失'}")

    try:
        token = get_access_token()
        print(f'✅ 鉴权成功 access_token={token[:12]}…')
    except Exception as e:
        print(f'❌ 鉴权失败: {e}')
        sys.exit(1)

    form_uuids = sys.argv[1:] or [s.get('form_uuid') for s in YIDA_MATERIAL_SOURCES if s.get('form_uuid')]
    if not form_uuids:
        print('\n⚠️ 未提供 FORM-xxxx：python scripts/yida_probe.py FORM-ABC FORM-DEF ...')
        sys.exit(0)

    for fu in form_uuids:
        probe_form(fu, token)

    print('\n完成。把上面的输出发我：')
    print('  - 若 [schema] OK 且自动映射全绿 → 我直接接通，80+ 张表零配置。')
    print('  - 若 schema 三个 endpoint 都失败 → 把错误贴我，我据此修正接口路径。')


if __name__ == '__main__':
    main()
