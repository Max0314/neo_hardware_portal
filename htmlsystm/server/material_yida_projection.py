# -*- coding: utf-8 -*-
"""宜搭 → 物料库 投影（阶段2）。

把宜搭物料优选表实例，按 4 个目标字段投影成物料库的标准表(7列)，写入 material_db_libraries。
- 单物料表(MCU/DC-DC)：一条实例 1 行；替代组标签取该字段值。
- 结构件(螺钉)：一条实例 1 行；无替代组标签则留空。
- 多物料替代组表(磁珠/电感/电阻/电容)：一条实例的 物料代码1..N 拆成 N 行，
  同实例 N 行共享一个替代组标签(库名#序号，体现互为替代)。

字段映射靠 yida_client.auto_map_material_fields 按中文标题自动完成，不逐表手配。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from server import material_db_manager as mdb
from server.logger import logger
from server.yida_client import (
    auto_map_material_fields, extract_instance_meta, get_form_schema,
    iter_form_instances, list_forms_in_app,
)
from server.yida_config import (
    LIBRARY_PASSWORD, MATERIAL_FORM_TITLE_KEYWORDS, YIDA_MATERIAL_SOURCES,
)

# 物料库标准表头（与 material-database.html STANDARD_HEADERS 一致）
STANDARD_HEADERS = ['物料代码', '物料描述', 'pads库物料描述', '成本单价', '替代组标签', '优选情况', '备注说明']


def _s(v: Any) -> str:
    return '' if v is None else str(v).strip()


def discover_material_forms(return_all: bool = False):
    """自动发现应用下的物料优选表单，按标题关键词过滤（兼容全角括号）。
    return_all=True 时返回 (全部表单, 命中表单) 便于诊断。"""
    all_forms = list_forms_in_app()  # 不限类型，取全部
    seen = set()
    picked = []
    for f in all_forms:
        title = f.get('title') or ''
        norm = title.replace('（', '(').replace('）', ')')
        if f['form_uuid'] in seen:
            continue
        if any(kw in norm for kw in MATERIAL_FORM_TITLE_KEYWORDS):
            seen.add(f['form_uuid'])
            picked.append({'form_uuid': f['form_uuid'], 'source_name': title, 'library_name': title})
    if return_all:
        return all_forms, picked
    return picked


def build_rows_for_form(form_uuid: str, library_name: str, *,
                        create_from_gmt: str, create_to_gmt: str) -> Dict[str, Any]:
    """读 schema→自动映射→拉实例→拆成物料行(7列)。Returns: {rows, instances, multi, slot_count}。"""
    fields, _ = get_form_schema(form_uuid)
    mp = auto_map_material_fields(fields)
    if mp['missing_in_first_slot']:
        raise RuntimeError(f'必填字段未匹配 {mp["missing_in_first_slot"]}（该表标题用词特殊，需补同义词）')
    multi = mp['multi']
    slots = mp['slots']
    # 多物料表用“序号”字段当组键的一部分；找不到序号就用实例ID尾段
    seq_field = next((f['field_id'] for f in fields if (f.get('label') or '').strip() == '序号'), None)

    rows: List[List[str]] = []
    n_inst = 0
    for inst in iter_form_instances(form_uuid, create_from_gmt=create_from_gmt, create_to_gmt=create_to_gmt):
        n_inst += 1
        meta = extract_instance_meta(inst)
        fd = meta.get('form_data') or {}
        group_key = ''
        if multi:
            seq = _s(fd.get(seq_field)) if seq_field else ''
            inst_id = _s(meta.get('form_instance_id'))
            group_key = f'{library_name}#{seq or inst_id[-8:] or n_inst}'
        for slot in slots:
            code = _s(fd.get(slot.get('material_code')))
            if not code:
                continue
            desc = _s(fd.get(slot.get('material_name')))
            pref = _s(fd.get(slot.get('preferred')))
            if multi:
                group = group_key
            else:
                rg = slot.get('replacement_group')
                group = _s(fd.get(rg)) if rg else ''
            # 列顺序：物料代码 物料描述 pads库物料描述 成本单价 替代组标签 优选情况 备注说明
            rows.append([code, desc, '', '', group, pref, ''])
    return {'rows': rows, 'instances': n_inst, 'multi': multi, 'slot_count': mp['slot_count']}


def sync_form_to_library(source: Dict[str, Any], *,
                         create_from_gmt: Optional[str] = None,
                         create_to_gmt: Optional[str] = None,
                         password: Optional[str] = None,
                         user_id: Optional[int] = None,
                         user_display: str = '宜搭同步') -> Dict[str, Any]:
    """同步一张宜搭表单到对应物料库（按库名 upsert，旧表进 history）。"""
    pwd = (password or LIBRARY_PASSWORD or '').strip()
    if not pwd:
        raise ValueError('未配置物料库默认密码（环境变量 YIDA_LIBRARY_PASSWORD）')
    library_name = source.get('library_name') or source.get('source_name') or source['form_uuid']
    now = datetime.now()
    create_to_gmt = create_to_gmt or (now + timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S')
    create_from_gmt = create_from_gmt or '2015-01-01 00:00:00'

    built = build_rows_for_form(source['form_uuid'], library_name,
                                create_from_gmt=create_from_gmt, create_to_gmt=create_to_gmt)
    data = [list(STANDARD_HEADERS)] + built['rows']
    current_table = {
        'fileName': f'宜搭同步-{library_name}.xlsx',
        'updatedAt': now.strftime('%Y-%m-%dT%H:%M:%S'),
        'data': data,
    }
    res = mdb.batch_import_libraries(
        [{'name': library_name, 'currentTable': current_table}],
        overwrite=True, default_prefix='', default_password=pwd,
        user_id=user_id, user_display=user_display,
    )
    logger.info(f"✅ 宜搭同步 {library_name}: 实例 {built['instances']} 条 → 物料 {len(built['rows'])} 行 "
                f"(multi={built['multi']}, slots={built['slot_count']}, {res})")
    return {
        'library': library_name, 'form_uuid': source['form_uuid'],
        'instances': built['instances'], 'rows': len(built['rows']),
        'multi': built['multi'], 'slot_count': built['slot_count'],
        'created': res.get('created', 0), 'updated': res.get('updated', 0),
    }


def sync_material_forms(sources: Optional[List[Dict[str, Any]]] = None, *,
                        password: Optional[str] = None,
                        user_id: Optional[int] = None,
                        user_display: str = '宜搭同步') -> Dict[str, Any]:
    """同步多张表单。sources 为空时：用 YIDA_MATERIAL_SOURCES，否则自动发现。"""
    if sources is None:
        sources = YIDA_MATERIAL_SOURCES or discover_material_forms()
    results = []
    ok = failed = 0
    for src in sources:
        try:
            results.append(sync_form_to_library(src, password=password, user_id=user_id, user_display=user_display))
            ok += 1
        except Exception as e:
            logger.error(f"宜搭同步失败 {src.get('library_name') or src.get('form_uuid')}: {e}", exc_info=True)
            results.append({'library': src.get('library_name') or src.get('form_uuid'),
                            'form_uuid': src.get('form_uuid'), 'error': str(e)})
            failed += 1
    return {'total': len(sources), 'ok': ok, 'failed': failed, 'results': results}
