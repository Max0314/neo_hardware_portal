#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""宜搭对接“探针”——部署后在 htmlsystm 目录运行，用于：
  1) 验证钉钉鉴权能否拿到 access_token；
  2) 验证宜搭权限/参数是否正确（能否查到实例）；
  3) 打印每张表单一条样本实例的【字段ID + 示例值】，供你对出
     物料代码 / 物料描述 / 替代组标签 / 优选情况 各对应哪个组件ID，
     再填进 server/yida_config.py 的 YIDA_MATERIAL_SOURCES.field_map。

用法（在 htmlsystm/ 目录下）：
    export YIDA_SYSTEM_TOKEN=xxxx          # 宜搭系统令牌
    # 钉钉密钥沿用现有 DINGTALK_CLIENT_SECRET
    python scripts/yida_probe.py FORM-XXXX [FORM-YYYY ...]
  不带参数时，读取 YIDA_MATERIAL_SOURCES 里配置的 form_uuid。
"""
import os
import sys
from datetime import datetime, timedelta

# 让 `from server...` 可用（scripts 的上级目录就是 htmlsystm）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.yida_config import YIDA_CONFIG, YIDA_MATERIAL_SOURCES, check_yida_config  # noqa: E402
from server.yida_client import get_access_token, search_form_instances, extract_instance_meta  # noqa: E402


def _preview(v, n=60):
    s = '' if v is None else str(v)
    s = s.replace('\n', ' ')
    return s if len(s) <= n else s[:n] + '…'


def probe_form(form_uuid: str, token: str):
    print(f'\n===== 表单 {form_uuid} =====')
    now = datetime.now()
    create_from = '2018-01-01 00:00:00'
    create_to = (now + timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S')
    try:
        instances, total = search_form_instances(
            form_uuid, current_page=1, page_size=5,
            create_from_gmt=create_from, create_to_gmt=create_to,
            access_token=token,
        )
    except Exception as e:
        print(f'  ❌ 查询失败: {e}')
        return
    print(f'  总实例数(窗口内): {total}，本次取样 {len(instances)} 条')
    if not instances:
        print('  ⚠️ 没有取到实例（可能是时间窗口、权限或 formUuid 不对）')
        return
    meta = extract_instance_meta(instances[0])
    print(f"  实例ID: {meta.get('form_instance_id')}  创建时间: {meta.get('created_time')}  发起人: {meta.get('originator_name') or meta.get('originator_user_id')}")
    form_data = meta.get('form_data') or {}
    if not form_data:
        print('  ⚠️ 该实例 formData 为空，打印原始实例顶层键供排查：')
        print('   ', list(instances[0].keys()))
        return
    print('  —— 字段ID -> 示例值（对照这里，找出 4 个目标字段的组件ID）——')
    for fid in sorted(form_data.keys()):
        print(f'    {fid:32s} = {_preview(form_data[fid])}')


def main():
    ok, err = check_yida_config()
    if not ok:
        print(f'❌ 配置不完整: {err}')
        sys.exit(1)
    print(f"宜搭 appType: {YIDA_CONFIG['app_type']}  queryUserId: {YIDA_CONFIG['query_user_id']}  systemToken: {'已配置' if YIDA_CONFIG['system_token'] else '缺失'}")

    try:
        token = get_access_token()
        print(f'✅ 鉴权成功，access_token: {token[:12]}…')
    except Exception as e:
        print(f'❌ 鉴权失败: {e}')
        sys.exit(1)

    form_uuids = sys.argv[1:] or [s.get('form_uuid') for s in YIDA_MATERIAL_SOURCES if s.get('form_uuid')]
    if not form_uuids:
        print('\n⚠️ 未提供 FORM-xxxx：请作为命令行参数传入，或先在 YIDA_MATERIAL_SOURCES 配置 form_uuid。')
        print('   例：python scripts/yida_probe.py FORM-ABC123 FORM-DEF456')
        sys.exit(0)

    for fu in form_uuids:
        probe_form(fu, token)

    print('\n完成。把上面每张表的【字段ID -> 示例值】发我，我据此填好 field_map。')


if __name__ == '__main__':
    main()
