# -*- coding: utf-8 -*-
"""宜搭(YiDa)开放接口客户端：鉴权 + 表单实例查询。

鉴权：钉钉应用凭证换 access_token（复用现有钉钉 app 的 client_id/secret）。
查询：POST /v1.0/yida/forms/instances/search，请求头带 x-acs-dingtalk-access-token。

只做“把实例拉回来”，不解释业务字段。所有网络调用带超时与有限重试，失败抛异常由上层记录。
"""
from __future__ import annotations

import json
import random
import ssl
import time
import urllib.error
import urllib.request
from urllib.parse import urlencode
from typing import Any, Dict, List, Optional, Tuple

from server.config import DINGTALK_CONFIG
from server.logger import logger
from server.yida_config import YIDA_CONFIG, MATERIAL_TARGET_LABELS

ACCESS_TOKEN_URL = 'https://api.dingtalk.com/v1.0/oauth2/accessToken'
INSTANCE_SEARCH_URL = 'https://api.dingtalk.com/v1.0/yida/forms/instances/search'

# 简单的进程内 token 缓存
_token_cache: Dict[str, Any] = {'token': None, 'expire_at': 0.0}


def _ssl_context() -> ssl.SSLContext:
    """使用系统受信任 CA 校验钉钉 API 的 TLS 证书。"""
    return ssl.create_default_context()


def _retry_delay(retry_base_sec: float, attempt: int) -> float:
    """指数退避加少量抖动，避免多个表单失败时同时重试上游。"""
    return retry_base_sec * (2 ** attempt) + random.uniform(0, 0.5)


def _first_not_none(*values: Any) -> Any:
    """取第一个非 None 的值。

    不能用 `a or b` 串联：总数为 0 是合法结果，会被 `or` 当成缺失继续向后取。
    """
    for value in values:
        if value is not None:
            return value
    return None


def _post_json(url: str, body: Dict[str, Any], headers: Dict[str, str],
               timeout: int = 30, max_retries: int = 3, retry_base_sec: float = 2.0) -> Dict[str, Any]:
    """POST JSON，对超时/5xx 做有限重试。返回解析后的 dict；非 2xx 或解析失败抛异常。"""
    data = json.dumps(body, ensure_ascii=False).encode('utf-8')
    last_err: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method='POST')
            with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
                text = resp.read().decode('utf-8')
                return json.loads(text) if text else {}
        except urllib.error.HTTPError as e:
            err_body = ''
            try:
                err_body = e.read().decode('utf-8')
            except Exception:
                pass
            # 4xx（鉴权/参数/权限）不重试，直接抛出
            if 400 <= e.code < 500:
                raise RuntimeError(f'宜搭接口 {e.code}: {err_body[:300] or e.reason}')
            last_err = RuntimeError(f'宜搭接口 {e.code}: {err_body[:300] or e.reason}')
        except (urllib.error.URLError, TimeoutError, ssl.SSLError) as e:
            last_err = e
        except json.JSONDecodeError as e:
            last_err = RuntimeError(f'宜搭接口返回非 JSON: {e}')
        if attempt < max_retries - 1:
            time.sleep(_retry_delay(retry_base_sec, attempt))
    raise last_err if last_err else RuntimeError('宜搭接口调用失败')


def get_access_token(force_refresh: bool = False) -> str:
    """用钉钉应用凭证换 access_token（带 5 分钟提前量缓存）。"""
    now = time.time()
    if not force_refresh and _token_cache['token'] and _token_cache['expire_at'] - 300 > now:
        return _token_cache['token']

    app_key = DINGTALK_CONFIG.get('client_id', '')
    app_secret = DINGTALK_CONFIG.get('client_secret', '')
    if not app_key or not app_secret:
        raise RuntimeError('缺少钉钉 client_id / client_secret（DINGTALK_CLIENT_SECRET 环境变量未配置？）')

    result = _post_json(
        ACCESS_TOKEN_URL,
        {'appKey': app_key, 'appSecret': app_secret},
        {'Content-Type': 'application/json'},
    )
    token = result.get('accessToken') or result.get('access_token')
    if not token:
        raise RuntimeError(f'获取 access_token 失败: {json.dumps(result, ensure_ascii=False)[:300]}')
    expire_in = int(result.get('expireIn') or result.get('expires_in') or 7200)
    _token_cache['token'] = token
    _token_cache['expire_at'] = now + expire_in
    return token


def search_form_instances(
    form_uuid: str,
    *,
    current_page: int = 1,
    page_size: int = 100,
    create_from_gmt: Optional[str] = None,
    create_to_gmt: Optional[str] = None,
    modified_from_gmt: Optional[str] = None,
    modified_to_gmt: Optional[str] = None,
    search_field_json: str = '{}',
    access_token: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], int]:
    """查询一页表单实例。Returns: (实例列表, 总数)。

    时间窗口二选一：create_*（按创建时间，适合补数）或 modified_*（按修改时间，适合增量）。
    """
    token = access_token or get_access_token()
    body: Dict[str, Any] = {
        'appType': YIDA_CONFIG['app_type'],
        'systemToken': YIDA_CONFIG['system_token'],
        'userId': YIDA_CONFIG['query_user_id'],
        'formUuid': form_uuid,
        'language': 'zh_CN',
        'searchFieldJson': search_field_json,
        'currentPage': current_page,
        'pageSize': min(int(page_size or 100), 100),
    }
    if create_from_gmt:
        body['createFromTimeGMT'] = create_from_gmt
    if create_to_gmt:
        body['createToTimeGMT'] = create_to_gmt
    if modified_from_gmt:
        body['modifiedFromTimeGMT'] = modified_from_gmt
    if modified_to_gmt:
        body['modifiedToTimeGMT'] = modified_to_gmt

    headers = {
        'Content-Type': 'application/json',
        'x-acs-dingtalk-access-token': token,
    }
    result = _post_json(INSTANCE_SEARCH_URL, body, headers)

    # 宜搭返回结构在不同版本里略有差异，做防御性解析
    data = (
        result.get('data')
        or result.get('result')
        or (result.get('content') if isinstance(result.get('content'), list) else None)
        or []
    )
    if isinstance(data, dict):
        data = data.get('data') or data.get('list') or []
    nested = result.get('result')
    total = _first_not_none(
        result.get('totalCount'),
        result.get('total'),
        nested.get('totalCount') if isinstance(nested, dict) else None,
    )
    if total is None:
        total = len(data)
    return list(data), int(total)


def iter_form_instances(
    form_uuid: str,
    *,
    create_from_gmt: Optional[str] = None,
    create_to_gmt: Optional[str] = None,
    modified_from_gmt: Optional[str] = None,
    modified_to_gmt: Optional[str] = None,
    page_size: int = 100,
    max_pages: int = 1000,
):
    """按时间窗口逐页拉取一张表单的全部实例（生成器，逐条产出）。"""
    token = get_access_token()
    page = 1
    seen = 0
    while page <= max_pages:
        instances, total = search_form_instances(
            form_uuid,
            current_page=page,
            page_size=page_size,
            create_from_gmt=create_from_gmt,
            create_to_gmt=create_to_gmt,
            modified_from_gmt=modified_from_gmt,
            modified_to_gmt=modified_to_gmt,
            access_token=token,
        )
        if not instances:
            break
        for inst in instances:
            yield inst
        seen += len(instances)
        logger.info(f'宜搭拉取 {form_uuid}: 第 {page} 页 {len(instances)} 条，累计 {seen}/{total}')
        # 只按「本页未满」判定结束。此处曾用 seen >= total 提前跳出，而 total 解析失败时
        # 会回退成本页长度，于是每张表都只同步了第一页。
        if len(instances) < page_size:
            break
        page += 1
    else:
        logger.warning(
            f'宜搭拉取 {form_uuid}: 已达最大页数 {max_pages}（累计 {seen} 条），可能仍有未同步数据'
        )


def extract_instance_meta(inst: Dict[str, Any]) -> Dict[str, Any]:
    """从一条实例里抽取通用元信息（字段名在不同版本里有别名，做兼容）。"""
    def pick(*keys):
        for k in keys:
            v = inst.get(k)
            if v not in (None, ''):
                return v
        return None

    form_data = inst.get('formData')
    if not isinstance(form_data, dict):
        form_data = inst.get('data') if isinstance(inst.get('data'), dict) else {}

    return {
        'form_instance_id': pick('formInstanceId', 'instanceId', 'processInstanceId'),
        'created_time': pick('createTimeGMT', 'gmtCreate', 'createTime'),
        'modified_time': pick('modifiedTimeGMT', 'gmtModified', 'modifiedTime', 'updateTime'),
        'originator_user_id': pick('creator', 'creatorUserId', 'originatorUserId', 'userId'),
        'originator_name': pick('creatorName', 'originatorName'),
        'title': pick('title', 'formInstanceTitle'),
        'form_data': form_data,
    }


# ==================== 表单字段定义（用于按中文标题自动映射） ====================
# 不同表单组件ID不同，故同步时读取每张表的字段定义(字段ID↔中文标题)，自动对到 4 个目标字段。
# 接口路径取自仓库内置官方 SDK（alibabacloud_dingtalk/yida_1_0：GetFormComponentDefinitionList）：
#   GET /v1.0/yida/forms/definitions/{appType}/{formUuid}
#   query: systemToken / userId / language；header: x-acs-dingtalk-access-token
#   返回: {result: [{fieldId, label, componentName, parentId}]}（label 即中文标题，parentId 标识子表单字段）
SCHEMA_URL = 'https://api.dingtalk.com/v1.0/yida/forms/definitions/{app_type}/{form_uuid}'


def _get_json(url: str, headers: Dict[str, str], timeout: int = 30,
              max_retries: int = 3, retry_base_sec: float = 2.0) -> Dict[str, Any]:
    last_err: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, headers=headers, method='GET')
            with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
                text = resp.read().decode('utf-8')
                return json.loads(text) if text else {}
        except urllib.error.HTTPError as e:
            body = ''
            try:
                body = e.read().decode('utf-8')
            except Exception:
                pass
            if 400 <= e.code < 500:
                raise RuntimeError(f'{e.code}: {body[:300] or e.reason}')
            last_err = RuntimeError(f'{e.code}: {body[:300] or e.reason}')
        except (urllib.error.URLError, TimeoutError, ssl.SSLError) as e:
            last_err = e
        except json.JSONDecodeError as e:
            last_err = RuntimeError(f'返回非 JSON: {e}')
        if attempt < max_retries - 1:
            time.sleep(_retry_delay(retry_base_sec, attempt))
    raise last_err if last_err else RuntimeError('GET 调用失败')


def _zh_label(label: Any) -> str:
    """label 可能是 dict、i18n JSON 字符串或普通字符串，统一取中文标题。"""
    if isinstance(label, dict):
        return (label.get('zh_CN') or label.get('zhCN') or label.get('zh') or '').strip()
    if isinstance(label, str):
        s = label.strip()
        if s.startswith('{'):
            try:
                d = json.loads(s)
                return (d.get('zh_CN') or d.get('zhCN') or d.get('zh') or '').strip()
            except Exception:
                return s
        return s
    return ''


def _parse_schema_fields(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """从 GetFormComponentDefinitionList 返回里抽出字段。
    返回结构 {result:[{fieldId,label,componentName,parentId}]}（兼容旧 content/key 写法）。"""
    rows = result.get('result') or result.get('content') or result.get('data') or []
    if isinstance(rows, dict):
        rows = rows.get('result') or rows.get('list') or rows.get('content') or []
    fields: List[Dict[str, Any]] = []
    for c in rows:
        if not isinstance(c, dict):
            continue
        fid = c.get('fieldId') or c.get('key') or c.get('componentId')
        if not fid:
            continue
        label = c.get('label')
        if label is None and isinstance(c.get('props'), dict):
            label = c['props'].get('label')
        fields.append({
            'field_id': str(fid),
            'label': _zh_label(label),
            'type': c.get('componentName') or c.get('type') or '',
            'parent_id': c.get('parentId') or '',
        })
    return fields


def get_form_schema(form_uuid: str, access_token: Optional[str] = None):
    """获取表单字段定义。Returns: (fields, used_url)，fields=[{field_id,label,type,parent_id}]。"""
    token = access_token or get_access_token()
    headers = {'x-acs-dingtalk-access-token': token, 'Content-Type': 'application/json'}
    qs = urlencode({
        'systemToken': YIDA_CONFIG['system_token'],
        'userId': YIDA_CONFIG['query_user_id'],
        'language': 'zh_CN',
    })
    url = SCHEMA_URL.format(app_type=YIDA_CONFIG['app_type'], form_uuid=form_uuid) + '?' + qs
    fields = _parse_schema_fields(_get_json(url, headers))
    if not fields:
        raise RuntimeError(f'表单 schema 返回空字段（接口可达但无字段）: {url.split("?")[0]}')
    return fields, url


FORM_LIST_URL = 'https://api.dingtalk.com/v1.0/yida/forms'


def list_forms_in_app(form_types: Optional[str] = None, page_size: int = 100, max_pages: int = 50):
    """列出应用下的表单。Returns: [{form_uuid, title, form_type}]。
    form_types 不传则取全部类型（普通表单+流程表单）。"""
    token = get_access_token()
    headers = {'x-acs-dingtalk-access-token': token, 'Content-Type': 'application/json'}
    out: List[Dict[str, Any]] = []
    page = 1
    while page <= max_pages:
        q = {
            'systemToken': YIDA_CONFIG['system_token'],
            'userId': YIDA_CONFIG['query_user_id'],
            'appType': YIDA_CONFIG['app_type'],
            'pageNumber': page,
            'pageSize': min(int(page_size or 100), 100),
        }
        if form_types:
            q['formTypes'] = form_types
        result = _get_json(FORM_LIST_URL + '?' + urlencode(q), headers)
        body = result.get('result') if isinstance(result.get('result'), dict) else result
        data = body.get('data') or []
        for d in data:
            if isinstance(d, dict) and d.get('formUuid'):
                # title 可能是 i18n 字典/JSON 串，统一取中文
                out.append({'form_uuid': d.get('formUuid'), 'title': _zh_label(d.get('title')), 'form_type': d.get('formType') or ''})
        total = int(body.get('totalCount') or len(out))
        if len(data) < page_size or len(out) >= total:
            break
        page += 1
    return out


def auto_map_material_fields(schema_fields: List[Dict[str, Any]]) -> Dict[str, Any]:
    """按中文标题映射 4 个目标字段，兼容三种表形态：
      - 单物料表（物料代码/物料描述/...）              -> 1 个槽位
      - 单物料无替代组（结构件）                        -> 1 个槽位，replacement_group 为 None
      - 多物料替代组表（物料代码1..N/物料描述1..N/...） -> N 个槽位（一条实例拆成 N 行）

    Returns: {
        'multi': bool, 'slot_count': int,
        'slots': [{material_code, material_name, preferred, replacement_group} -> field_id|None],
        'missing_in_first_slot': [未匹配的目标字段],
    }
    """
    by_label: Dict[str, str] = {}
    by_norm_label: Dict[str, str] = {}

    def norm_label(v: Any) -> str:
        s = (str(v or '')).strip().lower()
        s = ''.join(s.split())
        return s.replace('（', '(').replace('）', ')')

    for f in schema_fields:
        lb = (f.get('label') or '').strip()
        if lb:
            by_label.setdefault(lb, f['field_id'])
            by_norm_label.setdefault(norm_label(lb), f['field_id'])

    def find(target: str, suffix: str = '') -> Optional[str]:
        for lb in MATERIAL_TARGET_LABELS[target]:
            for cand in (f'{lb}{suffix}', f'{lb} {suffix}'.rstrip()):
                if cand in by_label:
                    return by_label[cand]
                hit = by_norm_label.get(norm_label(cand))
                if hit:
                    return hit
        return None

    # 探测编号槽位（物料代码1、物料代码2 ...），最多 20 个
    slot_numbers = [n for n in range(1, 21) if find('material_code', str(n))]
    slots: List[Dict[str, Optional[str]]] = []
    if slot_numbers:
        for n in slot_numbers:
            s = str(n)
            slots.append({
                'material_code': find('material_code', s),
                'material_name': find('material_name', s),
                'preferred': find('preferred', s),
                # 替代组标签：优先带编号，否则取该表统一的替代组字段（多物料表常以实例本身为替代组）
                'replacement_group': find('replacement_group', s) or find('replacement_group'),
            })
        multi = True
    else:
        slots.append({
            'material_code': find('material_code'),
            'material_name': find('material_name'),
            'preferred': find('preferred'),
            'replacement_group': find('replacement_group'),
        })
        multi = False

    first = slots[0] if slots else {}
    # 仅 物料代码+物料描述 为硬必填；优选情况/替代组标签 有的表本就没有，缺失不阻断整表
    missing = [k for k in ('material_code', 'material_name') if not first.get(k)]
    return {'multi': multi, 'slot_count': len(slots), 'slots': slots, 'missing_in_first_slot': missing}
