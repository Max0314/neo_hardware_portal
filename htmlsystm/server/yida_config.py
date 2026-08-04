# -*- coding: utf-8 -*-
"""宜搭(YiDa)表单同步配置。

设计原则（见对接方案）：
- 通用同步器只负责把宜搭 FORM-* 实例原样拉回来入库，不强行理解业务字段。
- 密钥走环境变量，不入库、不写死在代码里。
- 物料投影层再基于原始 JSON 抽取 4 个业务字段写入物料库。
"""
from __future__ import annotations

import json
import os


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ('1', 'true', 'yes', 'on')


def _env_float(name: str, default: float) -> float:
    value = (os.getenv(name) or '').strip()
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        raise ValueError(f'{name} 必须是数字，当前值无效')

# raw 表里的来源系统标识（区分不同来源/系统复用同一套同步器）
SOURCE_SYSTEM = 'hardware_material'

# ==================== 宜搭应用凭证 ====================
# 换取钉钉 access_token 复用现有钉钉 app（config.py 的 DINGTALK_CONFIG.client_id/secret），
# 这里只放宜搭应用自身的 appType / systemToken / 查询人。
YIDA_CONFIG = {
    # 宜搭应用编码（硬件协助）
    'app_type': (os.getenv('YIDA_APP_TYPE') or 'APP_MRBK7RVLFEMKQ1B36GIF').strip(),
    # 宜搭系统令牌（系统配置→应用秘钥里的 systemToken，必填，走环境变量）
    'system_token': (os.getenv('YIDA_SYSTEM_TOKEN') or '').strip(),
    # 查询人钉钉 userId（必填，走环境变量）。
    # 宜搭按这个人的数据权限返回表单实例，因此它决定同步能取到哪些数据。此处曾写死某位
    # 员工的 userId：该员工调离硬件研发部后，42 张表单返回「没有权限」、30 张返回 0 条实例，
    # 同步在无人察觉的情况下把物料库覆盖成了空表。不要再放默认值，缺失时应显式报错。
    'query_user_id': (os.getenv('YIDA_QUERY_USER_ID') or '').strip(),
}


# 同步写入物料库时，新建库使用的默认访问密码（material_db 每个库要求有密码）。
# 走环境变量，不写死；建议设置一个团队约定的物料库默认密码。
LIBRARY_PASSWORD = (os.getenv('YIDA_LIBRARY_PASSWORD') or '').strip()

# 特殊多物料替代表单：一条宜搭实例里有“物料代码1..N/物料描述1..N”，但替代组标签
# 不是独立字段，而是由同一行的规格字段拼接而成。
# 可通过环境变量手动追加 FORM ID，便于后续新增同类表单：
#   YIDA_SPECIAL_MATERIAL_FORMS=FORM-AAA,FORM-BBB
# 或 JSON：
#   YIDA_SPECIAL_MATERIAL_FORMS=[
#     {"form_uuid":"FORM-AAA","library_name":"容阻感优选表",
#      "group_label_fields":["Value","Voltage Rating","Tolerance","Package"]}
#   ]
SPECIAL_GROUP_LABEL_FIELDS = [
    'Value',
    'Voltage Rating',
    'Wattage/Amp',
    'Tolerance',
    'Temp Tolerance',
    'Life Time',
    'Material',
    'Package',
]


def _parse_special_material_sources():
    raw = (os.getenv('YIDA_SPECIAL_MATERIAL_FORMS') or '').strip()
    if not raw:
        return []

    def normalize(item):
        if isinstance(item, str):
            form_uuid = item.strip()
            if not form_uuid:
                return None
            return {
                'form_uuid': form_uuid,
                'source_name': form_uuid,
                'library_name': form_uuid,
                'projection': 'attribute_group_slots',
                'group_label_fields': SPECIAL_GROUP_LABEL_FIELDS,
            }
        if not isinstance(item, dict):
            return None
        form_uuid = (item.get('form_uuid') or item.get('formUuid') or '').strip()
        if not form_uuid:
            return None
        label_fields = item.get('group_label_fields') or item.get('groupLabelFields') or SPECIAL_GROUP_LABEL_FIELDS
        return {
            **item,
            'form_uuid': form_uuid,
            'source_name': item.get('source_name') or item.get('sourceName') or item.get('library_name') or form_uuid,
            'library_name': item.get('library_name') or item.get('libraryName') or item.get('source_name') or form_uuid,
            'projection': item.get('projection') or 'attribute_group_slots',
            'group_label_fields': label_fields if isinstance(label_fields, list) else SPECIAL_GROUP_LABEL_FIELDS,
        }

    try:
        parsed = json.loads(raw)
        items = parsed if isinstance(parsed, list) else [parsed]
    except json.JSONDecodeError:
        items = [x.strip() for x in raw.replace(';', ',').split(',')]
    return [x for x in (normalize(item) for item in items) if x]


YIDA_SPECIAL_MATERIAL_SOURCES = _parse_special_material_sources()

# 安全默认值：同步源必须由管理员明确列出 form_uuid。自动按标题发现的表单只可
# 在排查阶段显式开启，不能作为生产写入的默认来源。
YIDA_AUTO_DISCOVER_MATERIAL_FORMS = _env_bool(
    'YIDA_AUTO_DISCOVER_MATERIAL_FORMS', False
)

# 每日全量同步默认关闭；它应在白名单和历史数据核验完成后再由运维显式开启。
YIDA_SYNC_SCHEDULER_ENABLED = _env_bool('YIDA_SYNC_SCHEDULER_ENABLED', False)

# 保护已有物料库免受异常减量覆盖。仅当原库至少有指定数量的物料时生效。
YIDA_MIN_ROW_RETAIN_RATIO = _env_float('YIDA_MIN_ROW_RETAIN_RATIO', 0.5)
YIDA_ROW_REDUCTION_MIN_BASELINE = int(
    os.getenv('YIDA_ROW_REDUCTION_MIN_BASELINE') or '20'
)
if not 0 < YIDA_MIN_ROW_RETAIN_RATIO <= 1:
    raise ValueError('YIDA_MIN_ROW_RETAIN_RATIO 必须大于 0 且不超过 1')
if YIDA_ROW_REDUCTION_MIN_BASELINE < 1:
    raise ValueError('YIDA_ROW_REDUCTION_MIN_BASELINE 必须至少为 1')

# 自动发现物料表单时，按标题包含以下任一关键词判定为“物料优选表”（过滤掉 PCB/领料/测试等无关表单）。
MATERIAL_FORM_TITLE_KEYWORDS = ['物料优选', '(FB)', '(L)', '(R)', '(C)', '(ECA)',
                                '一体式成型电感', 'CPU&WIFI']

# 命中后再排除：以下是“中间表/流程/统计/底层元数据”，不是物料明细优选表，不同步。
MATERIAL_FORM_EXCLUDE_KEYWORDS = [
    '中间表', '数据集', '统计', '申请表', '审批', '审核', '记录',
    '表名', '名称与', '必填属性', '通知', '齐套', 'Etype', '配置', '建库',
]


def check_yida_config():
    """校验宜搭配置是否完整。Returns: (ok, error_message)。"""
    if not YIDA_CONFIG.get('system_token'):
        return False, '未配置 YIDA_SYSTEM_TOKEN（宜搭系统令牌），请在环境变量中设置'
    if not YIDA_CONFIG.get('app_type'):
        return False, '未配置 YIDA_APP_TYPE（宜搭应用编码）'
    if not YIDA_CONFIG.get('query_user_id'):
        return False, (
            '未配置 YIDA_QUERY_USER_ID（查询人钉钉 userId）。宜搭按该账号的数据权限返回'
            '表单实例，请使用对全部物料表单有数据权限的账号，并优先使用专用服务账号。'
        )
    return True, None


def check_material_sync_config():
    """校验物料同步的安全开关和白名单。

    宜搭基本凭据可用不代表允许把任意标题命中的表单写入物料库。没有显式
    白名单时，只有管理员明确设置自动发现开关才允许继续，且该模式仅适合诊断。
    """
    configured = (YIDA_SPECIAL_MATERIAL_SOURCES or []) + (YIDA_MATERIAL_SOURCES or [])
    if configured:
        unnamed = [
            src.get('form_uuid')
            for src in configured
            if (src.get('form_uuid') or '')
            == (src.get('library_name') or src.get('source_name') or '')
        ]
        if unnamed:
            return False, (
                '宜搭物料白名单缺少稳定库名：' + ', '.join(unnamed[:3])
                + '。请使用 JSON 为每个 form_uuid 配置 library_name。'
            )
        return True, None
    if YIDA_AUTO_DISCOVER_MATERIAL_FORMS:
        return True, None
    return False, (
        '未配置 YIDA_MATERIAL_FORMS 白名单；为防止未知宜搭表覆盖物料库，'
        '同步已阻止。请先用预检脚本确认表单，再配置 form_uuid 与 library_name。'
    )


# ==================== 物料表单源 ====================
# 一张宜搭表单 ↔ 一个物料库。form_uuid 与 field_map 待“探针”确认后填入。
#
# field_map：宜搭表单组件ID -> 标准业务字段。四个目标字段：
#   material_code      物料代码
#   material_name      物料名称（宜搭表单里叫“物料描述”）
#   replacement_group  替代组标签
#   preferred          优选情况
#
# 注意：不同表单的组件ID不同（同事已确认），因此不手工逐表配 field_map，而是按下面的
# 中文标题自动映射——同步时读每张表的字段定义(字段ID↔标题)，把目标字段对到本表的组件ID。
# 仅当某表标题特殊、自动映射失败时，才在该表 source 里手工写 field_map 覆盖。

# 目标字段 -> 该字段在宜搭表单里可能的中文标题（按标题自动匹配，含同义词；越靠前优先级越高）
MATERIAL_TARGET_LABELS = {
    'material_code': ['物料代码', '物料编码', '物料编号'],
    'material_name': ['物料描述', '物料名称', '描述'],
    'preferred': ['优选情况', '优选状态', '优选'],
    'replacement_group': ['替代组标签', '替代组', '替代分组', '替代组别', '替代项目组', '替代项目'],
}

_DEFAULT_YIDA_MATERIAL_SOURCES = [
    # {
    #     'source_name': '阻容物料优选表',
    #     'form_uuid': 'FORM-XXXXXXXXXXXX',
    #     'library_name': '阻容物料优选表',   # 写入哪个物料库（material_db_libraries 按库名 upsert）
    #     'field_map': {
    #         'material_code': 'textField_xxxxx',
    #         'material_name': 'textField_xxxxx',
    #         'replacement_group': 'textField_xxxxx',
    #         'preferred': 'selectField_xxxxx',
    #     },
    # },
    # ... 其余 5 张表单同理 ...
]


def _parse_material_sources():
    """从 JSON 白名单读取普通物料表单，不接受只有 FORM ID 的简写。

    省略 library_name 会导致表单 UUID 被当作库名，发生改名或误建库时难以
    追溯，因此这里要求每个来源提供稳定的库名。
    """
    raw = (os.getenv('YIDA_MATERIAL_FORMS') or '').strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError('YIDA_MATERIAL_FORMS 必须是 JSON 对象或 JSON 数组') from exc
    items = parsed if isinstance(parsed, list) else [parsed]
    sources = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError('YIDA_MATERIAL_FORMS 的每一项必须是 JSON 对象')
        form_uuid = (item.get('form_uuid') or item.get('formUuid') or '').strip()
        library_name = (
            item.get('library_name') or item.get('libraryName') or ''
        ).strip()
        if not form_uuid or not library_name:
            raise ValueError(
                'YIDA_MATERIAL_FORMS 的每项必须包含 form_uuid 和 library_name'
            )
        sources.append({
            **item,
            'form_uuid': form_uuid,
            'library_name': library_name,
            'source_name': (
                item.get('source_name') or item.get('sourceName') or library_name
            ).strip(),
        })
    return sources


YIDA_MATERIAL_SOURCES = _DEFAULT_YIDA_MATERIAL_SOURCES + _parse_material_sources()
