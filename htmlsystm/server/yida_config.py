# -*- coding: utf-8 -*-
"""宜搭(YiDa)表单同步配置。

设计原则（见对接方案）：
- 通用同步器只负责把宜搭 FORM-* 实例原样拉回来入库，不强行理解业务字段。
- 密钥走环境变量，不入库、不写死在代码里。
- 物料投影层再基于原始 JSON 抽取 4 个业务字段写入物料库。
"""
from __future__ import annotations

import os

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
    # 查询人钉钉 userId
    'query_user_id': (os.getenv('YIDA_QUERY_USER_ID') or '01115324500438248944').strip(),
}


# 同步写入物料库时，新建库使用的默认访问密码（material_db 每个库要求有密码）。
# 走环境变量，不写死；建议设置一个团队约定的物料库默认密码。
LIBRARY_PASSWORD = (os.getenv('YIDA_LIBRARY_PASSWORD') or '').strip()

# 自动发现物料表单时，按标题包含以下任一关键词判定为“物料优选表”（过滤掉 PCB/领料/测试等无关表单）。
MATERIAL_FORM_TITLE_KEYWORDS = ['物料优选', '(FB)', '(L)', '(R)', '(C)', '(ECA)']


def check_yida_config():
    """校验宜搭配置是否完整。Returns: (ok, error_message)。"""
    if not YIDA_CONFIG.get('system_token'):
        return False, '未配置 YIDA_SYSTEM_TOKEN（宜搭系统令牌），请在环境变量中设置'
    if not YIDA_CONFIG.get('app_type'):
        return False, '未配置 YIDA_APP_TYPE（宜搭应用编码）'
    if not YIDA_CONFIG.get('query_user_id'):
        return False, '未配置 YIDA_QUERY_USER_ID（查询人钉钉 userId）'
    return True, None


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
    'replacement_group': ['替代组标签', '替代组', '替代分组', '替代组别'],
}

YIDA_MATERIAL_SOURCES = [
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
