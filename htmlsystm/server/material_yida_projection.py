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
    LIBRARY_PASSWORD, MATERIAL_FORM_TITLE_KEYWORDS, MATERIAL_FORM_EXCLUDE_KEYWORDS,
    SPECIAL_GROUP_LABEL_FIELDS, YIDA_MATERIAL_SOURCES, YIDA_SPECIAL_MATERIAL_SOURCES,
    YIDA_AUTO_DISCOVER_MATERIAL_FORMS, YIDA_MIN_ROW_RETAIN_RATIO,
    YIDA_ROW_REDUCTION_MIN_BASELINE,
)

# 物料库标准表头（与 material-database.html STANDARD_HEADERS 一致）
STANDARD_HEADERS = ['物料代码', '物料描述', 'pads库物料描述', '成本单价', '替代组标签', '优选情况', '备注说明']
LEGACY_LIBRARY_TYPE_SUFFIXES = ('(C)', '(R)', '(L)', '(FB)', '(ECA)')


class YidaSyncSafetyError(RuntimeError):
    """同步投影违反防数据损坏规则时抛出。"""


def _s(v: Any) -> str:
    return '' if v is None else str(v).strip()


def _normalize_library_name(name: str) -> str:
    return _s(name).replace('（', '(').replace('）', ')')


def _legacy_library_aliases(library_name: str) -> List[str]:
    """Return old material-library names that predate YiDa type suffixes.

    YiDa discovery names forms as e.g. ``0201电容(C)`` while older material DB
    libraries were named ``0201电容``.  The alias is used only as a single-target
    compatibility fallback when the YiDa-title library does not exist.
    """
    name = _normalize_library_name(library_name)
    aliases: List[str] = []
    for suffix in LEGACY_LIBRARY_TYPE_SUFFIXES:
        if name.endswith(suffix):
            alias = name[: -len(suffix)].strip()
            if alias and alias != library_name:
                aliases.append(alias)
            break
    return aliases


def _sync_target_library_names(library_name: str, form_uuid: Optional[str] = None) -> List[str]:
    """Resolve exactly one material library for a YiDa form.

    The YiDa form UUID is the durable identity and wins over names.  This keeps a
    renamed form attached to its existing library instead of creating a second
    library.  For libraries created before source metadata was recorded, prefer
    the exact YiDa title, then fall back to the old suffix-less alias.
    """
    source_title = _s(library_name)
    source_form_uuid = _s(form_uuid)
    libraries = mdb.list_libraries()

    if source_form_uuid:
        uuid_matches = []
        for lib in libraries:
            current_table = lib.get('currentTable')
            if not isinstance(current_table, dict):
                continue
            if _s(current_table.get('sourceFormUuid')) == source_form_uuid:
                uuid_matches.append(lib)
        if uuid_matches:
            exact_match = next(
                (lib for lib in uuid_matches if _s(lib.get('name')) == source_title),
                None,
            )
            selected = exact_match or sorted(
                uuid_matches,
                key=lambda lib: (_s(lib.get('name')), _s(lib.get('id'))),
            )[0]
            return [_s(selected.get('name'))]

    existing_names = {
        _s(lib.get('name'))
        for lib in libraries
        if _s(lib.get('name'))
    }
    if source_title in existing_names:
        return [source_title]

    alias = next(
        (name for name in _legacy_library_aliases(source_title) if name in existing_names),
        None,
    )
    return [alias or source_title]


def _table_row_count(table: Any) -> int:
    """返回物料表数据行数；损坏或旧格式数据按 0 行处理。"""
    if not isinstance(table, dict):
        return 0
    data = table.get('data')
    if not isinstance(data, list):
        return 0
    return max(len(data) - 1, 0)


def _validate_projection_before_overwrite(
    source_title: str,
    form_uuid: str,
    target_libraries: List[str],
    incoming_rows: int,
) -> None:
    """在任何写库操作前执行不可绕过的行数安全校验。"""
    if incoming_rows <= 0:
        raise YidaSyncSafetyError(
            f'安全阻断：宜搭表单 {source_title} ({form_uuid}) 提取到 0 条有效物料代码，'
            '未覆盖任何物料库。请检查源数据、字段映射和时间范围。'
        )

    existing_by_name = {
        _s(lib.get('name')): lib for lib in mdb.list_libraries() if _s(lib.get('name'))
    }
    dangerous_reductions = []
    for name in target_libraries:
        existing = existing_by_name.get(_s(name))
        previous_rows = _table_row_count((existing or {}).get('currentTable'))
        if (
            previous_rows >= YIDA_ROW_REDUCTION_MIN_BASELINE
            and incoming_rows < previous_rows * YIDA_MIN_ROW_RETAIN_RATIO
        ):
            dangerous_reductions.append(f'{name}: {previous_rows}→{incoming_rows}')
    if dangerous_reductions:
        raise YidaSyncSafetyError(
            '安全阻断：宜搭投影行数异常下降（' + '；'.join(dangerous_reductions)
            + f'，最低保留比例 {YIDA_MIN_ROW_RETAIN_RATIO:.0%}），未覆盖任何物料库。'
        )


def _field_value(fd: Dict[str, Any], field_id: Optional[str]) -> Any:
    """读字段值；NumberField/部分组件的取值有时在 `field_id_value` 下，做兜底。"""
    if not field_id:
        return None
    val = fd.get(field_id)
    if val in (None, ''):
        val = fd.get(f'{field_id}_value')
    return val


def _strip_group_comma_suffix(label: str) -> str:
    """替代组标签只保留第一个逗号(含全角)前的部分。
    源数据形如 'W-C-0.6PF|50V|A|HQ|0201,0.6PF,A'，逗号后是重复的规格摘要，按需求不拼入标签。"""
    for sep in (',', '，'):
        idx = label.find(sep)
        if idx >= 0:
            label = label[:idx]
    return label.strip()


def _label_key(label: Any) -> str:
    return ''.join(_s(label).lower().split())


def _field_by_labels(fields: List[Dict[str, Any]], labels: List[str]) -> Optional[str]:
    wanted = {_label_key(x) for x in labels if _s(x)}
    if not wanted:
        return None
    for f in fields:
        if _label_key(f.get('label')) in wanted:
            return f.get('field_id')
    return None


def _attribute_group_field_ids(
    fields: List[Dict[str, Any]],
    label_fields: Optional[List[str]] = None,
) -> List[Dict[str, str]]:
    """Resolve special-form attribute fields used to build replacement group labels.

    Missing fields are intentionally ignored so new forms can omit Voltage Rating,
    Wattage/Amp, etc. without breaking the whole YiDa sync.
    """
    label_fields = label_fields or SPECIAL_GROUP_LABEL_FIELDS
    aliases = {
        'Voltage Rating': ['Voltage Rating', 'VoltageRating'],
        'Wattage/Amp': ['Wattage/Amp', 'Wattage', 'Amp', 'Wattage Amp'],
        'Temp Tolerance': ['Temp Tolerance', 'TempTolerance'],
        'Life Time': ['Life Time', 'Lifetime'],
    }
    resolved = []
    for label in label_fields:
        candidates = aliases.get(label, [label])
        fid = _field_by_labels(fields, candidates)
        if fid:
            resolved.append({'label': label, 'field_id': fid})
    return resolved


def _uses_attribute_group_projection(
    source: Dict[str, Any],
    fields: List[Dict[str, Any]],
    multi: bool,
) -> bool:
    if source.get('projection') in ('attribute_group_slots', 'special_attribute_group'):
        return True
    if source.get('group_label_fields'):
        return True
    if not multi:
        return False
    attr_ids = _attribute_group_field_ids(fields)
    labels = {x['label'] for x in attr_ids}
    return 'Value' in labels and 'Package' in labels


def _build_attribute_group_label(
    fd: Dict[str, Any],
    attr_fields: List[Dict[str, str]],
) -> str:
    parts = []
    for item in attr_fields:
        val = _s(_field_value(fd, item['field_id']))
        if val:
            parts.append(val)
    return '|'.join(parts)


def _merge_material_sources(
    configured: List[Dict[str, Any]],
    discovered: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    title_by_uuid = {d.get('form_uuid'): d for d in discovered}
    merged = []
    seen = set()
    for src in configured + discovered:
        form_uuid = src.get('form_uuid')
        if not form_uuid or form_uuid in seen:
            continue
        discovered_src = title_by_uuid.get(form_uuid) or {}
        if (src.get('library_name') or '') == form_uuid and discovered_src.get('library_name'):
            src = {**src, 'library_name': discovered_src.get('library_name'), 'source_name': discovered_src.get('source_name')}
        merged.append(src)
        seen.add(form_uuid)
    return merged


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
        if not any(kw in norm for kw in MATERIAL_FORM_TITLE_KEYWORDS):
            continue
        if any(ex in norm for ex in MATERIAL_FORM_EXCLUDE_KEYWORDS):
            continue
        seen.add(f['form_uuid'])
        picked.append({'form_uuid': f['form_uuid'], 'source_name': title, 'library_name': title})
    if return_all:
        return all_forms, picked
    return picked


def build_rows_for_form(form_uuid: str, library_name: str, *,
                        create_from_gmt: str, create_to_gmt: str,
                        source: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """读 schema→自动映射→拉实例→拆成物料行(7列)。Returns: {rows, instances, multi, slot_count}。"""
    fields, _ = get_form_schema(form_uuid)
    mp = auto_map_material_fields(fields)
    source = dict(source or {'form_uuid': form_uuid, 'library_name': library_name})
    special_source = next((s for s in YIDA_SPECIAL_MATERIAL_SOURCES if s.get('form_uuid') == form_uuid), None)
    if special_source:
        source.update(special_source)
    if mp['missing_in_first_slot']:
        raise RuntimeError(f'必填字段未匹配 {mp["missing_in_first_slot"]}（该表标题用词特殊，需补同义词）')
    multi = mp['multi']
    slots = mp['slots']
    use_attribute_group = _uses_attribute_group_projection(source, fields, multi)
    attr_fields = _attribute_group_field_ids(fields, source.get('group_label_fields') or SPECIAL_GROUP_LABEL_FIELDS) if use_attribute_group else []
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
            seq = _s(_field_value(fd, seq_field)) if seq_field else ''
            inst_id = _s(meta.get('form_instance_id'))
            group_key = f'{library_name}#{seq or inst_id[-8:] or n_inst}'
        for slot in slots:
            code = _s(_field_value(fd, slot.get('material_code')))
            if not code:
                continue
            desc = _s(_field_value(fd, slot.get('material_name')))
            pref = _s(_field_value(fd, slot.get('preferred')))
            if use_attribute_group:
                group = _build_attribute_group_label(fd, attr_fields) or group_key
            elif multi:
                group = group_key
            else:
                rg = slot.get('replacement_group')
                group = _strip_group_comma_suffix(_s(_field_value(fd, rg))) if rg else ''
            # 列顺序：物料代码 物料描述 pads库物料描述 成本单价 替代组标签 优选情况 备注说明
            rows.append([code, desc, '', '', group, pref, ''])
    return {
        'rows': rows,
        'instances': n_inst,
        'multi': multi,
        'slot_count': mp['slot_count'],
        'group_projection': 'attribute_fields' if use_attribute_group else ('instance_key' if multi else 'field'),
        'group_label_fields': [x['label'] for x in attr_fields],
    }


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
    library_name = (
        source.get('library_name')
        or source.get('source_name')
        or source['form_uuid']
    )
    source_title = source.get('source_name') or library_name
    now = datetime.now()
    create_to_gmt = create_to_gmt or (now + timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S')
    create_from_gmt = create_from_gmt or '2015-01-01 00:00:00'

    built = build_rows_for_form(
        source['form_uuid'],
        library_name,
        create_from_gmt=create_from_gmt,
        create_to_gmt=create_to_gmt,
        source=source,
    )
    target_libraries = _sync_target_library_names(library_name, source['form_uuid'])
    _validate_projection_before_overwrite(
        source_title, source['form_uuid'], target_libraries, len(built['rows'])
    )

    data = [list(STANDARD_HEADERS)] + built['rows']
    current_table = {
        'fileName': f'宜搭同步-{library_name}.xlsx',
        'updatedAt': now.strftime('%Y-%m-%dT%H:%M:%S'),
        'sourceFormUuid': source['form_uuid'],
        'sourceTitle': source_title,
        'data': data,
    }
    import_items = []
    for target_name in target_libraries:
        target_table = dict(current_table)
        target_table['fileName'] = f'Yida-sync-{target_name}.xlsx'
        import_items.append({'name': target_name, 'currentTable': target_table})

    res = mdb.batch_import_libraries(
        import_items,
        overwrite=True, default_prefix='', default_password=pwd,
        user_id=user_id, user_display=user_display,
        skip_unchanged_history=True,
    )
    logger.info(f"✅ 宜搭同步 {source_title}: 实例 {built['instances']} 条 → 物料 {len(built['rows'])} 行 "
                f"(multi={built['multi']}, slots={built['slot_count']}, {res})")
    return {
        'library': library_name, 'form_uuid': source['form_uuid'],
        'target_libraries': target_libraries,
        'instances': built['instances'], 'rows': len(built['rows']),
        'multi': built['multi'], 'slot_count': built['slot_count'],
        'group_projection': built.get('group_projection'),
        'group_label_fields': built.get('group_label_fields') or [],
        'created': res.get('created', 0), 'updated': res.get('updated', 0),
        'unchanged': res.get('unchanged', 0),
    }


def sync_material_forms(sources: Optional[List[Dict[str, Any]]] = None, *,
                        password: Optional[str] = None,
                        user_id: Optional[int] = None,
                        user_display: str = '宜搭同步') -> Dict[str, Any]:
    """同步多张表单；默认只使用明确配置的白名单。"""
    if sources is None:
        configured = (YIDA_SPECIAL_MATERIAL_SOURCES or []) + (YIDA_MATERIAL_SOURCES or [])
        discovered = discover_material_forms() if YIDA_AUTO_DISCOVER_MATERIAL_FORMS else []
        sources = _merge_material_sources(
            configured,
            discovered,
        )
    if not sources:
        raise YidaSyncSafetyError(
            '同步源为空：请配置 YIDA_MATERIAL_FORMS 白名单；自动发现默认关闭。'
        )
    results = []
    ok = failed = blocked = 0
    for src in sources:
        try:
            results.append(sync_form_to_library(src, password=password, user_id=user_id, user_display=user_display))
            ok += 1
        except YidaSyncSafetyError as e:
            logger.warning(
                '宜搭同步安全阻断 %s: %s',
                src.get('library_name') or src.get('form_uuid'), e,
            )
            results.append({
                'library': src.get('library_name') or src.get('form_uuid'),
                'form_uuid': src.get('form_uuid'), 'source_name': src.get('source_name'),
                'blocked': True, 'error': str(e),
            })
            failed += 1
            blocked += 1
        except Exception as e:
            logger.error(f"宜搭同步失败 {src.get('library_name') or src.get('form_uuid')}: {e}", exc_info=True)
            results.append({'library': src.get('library_name') or src.get('form_uuid'),
                            'form_uuid': src.get('form_uuid'),
                            'source_name': src.get('source_name'), 'error': str(e)})
            failed += 1
    total_rows = sum(r.get('rows', 0) for r in results if not r.get('error'))
    # 空投影会在写入前被安全阻断，这个字段保留给旧状态兼容。
    empty = sum(1 for r in results if not r.get('error') and r.get('rows', 0) == 0)
    return {'total': len(sources), 'ok': ok, 'failed': failed,
            'blocked': blocked, 'empty': empty, 'total_rows': total_rows, 'results': results}
