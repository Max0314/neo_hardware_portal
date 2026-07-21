#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多物料库（Excel）存储、密码校验与操作审计。"""
import json
import os
import secrets
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from server.db_adapter import get_connection_pool
from server.logger import logger
from server.security import PasswordHasher

UNLOCK_TTL_SECONDS = 30 * 60
REPLACEMENT_MODULE_ID = '__replacement_pairs__'
MATERIAL_LIBRARY_MODULE_ID = '__material_libraries__'
MATERIAL_PASSWORD_SETTING_KEY = 'material_db_global_password_hash'
_unlock_tokens: Dict[str, Dict[str, Any]] = {}

ACTION_LABELS = {
    'create_library': '创建了',
    'update_library': '更新了',
    'upload_table': '上传了',
    'delete_library': '删除了',
    'download_current': '下载了',
    'download_history': '下载了历史表',
    'export_all': '导出了全部',
    'batch_import': '批量导入了',
    'edit_remark': '修改了备注',
    'set_password': '设置了',
    'change_password': '修改了',
    'migrate_local': '从浏览器迁移了',
    'replacement_set_password': '设置了替换对管理密码',
    'replacement_update': '更新了',
    'replacement_migrate': '迁移了替换对数据',
}


def _now_str() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _parse_json(val: Any, default: Any) -> Any:
    if val is None:
        return default
    if isinstance(val, (dict, list)):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except json.JSONDecodeError:
            return default
    return default


def ensure_tables() -> None:
    pool = get_connection_pool()
    with pool.get_cursor() as cursor:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS material_db_libraries (
                id VARCHAR(36) PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                prefix VARCHAR(255) DEFAULT '',
                password_hash VARCHAR(255) NOT NULL,
                current_table_json LONGTEXT,
                history_tables_json LONGTEXT,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                INDEX idx_material_db_name (name)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS material_db_audit (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NULL,
                user_display VARCHAR(255) NOT NULL DEFAULT '',
                action VARCHAR(64) NOT NULL,
                library_id VARCHAR(36) NULL,
                library_name VARCHAR(255) NULL,
                detail TEXT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_mdb_audit_lib (library_id),
                INDEX idx_mdb_audit_time (created_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS material_db_settings (
                setting_key VARCHAR(64) PRIMARY KEY,
                setting_value LONGTEXT NOT NULL,
                updated_at DATETIME NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        ''')


def _cleanup_unlock_tokens() -> None:
    now = time.time()
    expired = [t for t, v in _unlock_tokens.items() if v.get('expires_at', 0) <= now]
    for t in expired:
        _unlock_tokens.pop(t, None)


def create_unlock_token(user_id: int, library_id: str) -> Tuple[str, int]:
    _cleanup_unlock_tokens()
    token = secrets.token_urlsafe(32)
    expires_at = int(time.time()) + UNLOCK_TTL_SECONDS
    _unlock_tokens[token] = {
        'user_id': user_id,
        'library_id': library_id,
        'expires_at': expires_at,
    }
    return token, expires_at


def verify_unlock_token(token: Optional[str], user_id: int, library_id: str) -> bool:
    if not token:
        return False
    _cleanup_unlock_tokens()
    entry = _unlock_tokens.get(token)
    if not entry:
        return False
    if entry.get('user_id') != user_id:
        return False
    if entry.get('library_id') not in (library_id, MATERIAL_LIBRARY_MODULE_ID):
        return False
    if entry.get('expires_at', 0) <= time.time():
        _unlock_tokens.pop(token, None)
        return False
    return True


def clear_unlock_tokens_for_library(library_id: str) -> None:
    for token, entry in list(_unlock_tokens.items()):
        if entry.get('library_id') == library_id:
            _unlock_tokens.pop(token, None)


def clear_material_unlock_tokens() -> None:
    for token, entry in list(_unlock_tokens.items()):
        if entry.get('library_id') != REPLACEMENT_MODULE_ID:
            _unlock_tokens.pop(token, None)


def create_material_unlock_token(user_id: int) -> Tuple[str, int]:
    return create_unlock_token(user_id, MATERIAL_LIBRARY_MODULE_ID)


def log_audit(
    user_id: Optional[int],
    user_display: str,
    action: str,
    library_id: Optional[str] = None,
    library_name: Optional[str] = None,
    detail: Optional[Dict[str, Any]] = None,
) -> None:
    try:
        pool = get_connection_pool()
        with pool.get_cursor() as cursor:
            cursor.execute(
                '''
                INSERT INTO material_db_audit
                (user_id, user_display, action, library_id, library_name, detail)
                VALUES (%s, %s, %s, %s, %s, %s)
                ''',
                (
                    user_id,
                    user_display or '未知用户',
                    action,
                    library_id,
                    library_name,
                    json.dumps(detail, ensure_ascii=False) if detail else None,
                ),
            )
    except Exception as e:
        logger.error(f'记录物料库审计失败: {e}', exc_info=True)


def format_audit_message(row: Dict[str, Any]) -> str:
    action = row.get('action') or ''
    verb = ACTION_LABELS.get(action, action)
    user = row.get('user_display') or '未知用户'
    lib_name = row.get('library_name') or '（未命名）'
    if action == 'export_all':
        return f'{user} {verb}物料库数据'
    if row.get('library_id') == REPLACEMENT_MODULE_ID:
        return f'{user} {verb}替换对数据'
    return f'{user} {verb}「{lib_name}」物料库'


def list_libraries(include_history_data: bool = True) -> List[Dict[str, Any]]:
    ensure_tables()
    pool = get_connection_pool()
    with pool.get_cursor() as cursor:
        cursor.execute(
            '''
            SELECT id, name, prefix, password_hash, current_table_json,
                   history_tables_json, created_at, updated_at
            FROM material_db_libraries
            ORDER BY name
            '''
        )
        rows = cursor.fetchall() or []
    result = []
    for row in rows:
        result.append(_row_to_public_lib(row, include_history_data=include_history_data))
    return result


def get_library(lib_id: str) -> Optional[Dict[str, Any]]:
    ensure_tables()
    pool = get_connection_pool()
    with pool.get_cursor() as cursor:
        cursor.execute(
            '''
            SELECT id, name, prefix, password_hash, current_table_json,
                   history_tables_json, created_at, updated_at
            FROM material_db_libraries WHERE id = %s
            ''',
            (lib_id,),
        )
        row = cursor.fetchone()
    if not row:
        return None
    return _row_to_public_lib(row)


def _row_to_public_lib(
    row: Dict[str, Any], include_history_data: bool = True
) -> Dict[str, Any]:
    created = row.get('created_at')
    updated = row.get('updated_at')
    if hasattr(created, 'strftime'):
        created = created.strftime('%Y-%m-%d %H:%M:%S')
    if hasattr(updated, 'strftime'):
        updated = updated.strftime('%Y-%m-%d %H:%M:%S')
    pwd_hash = row.get('password_hash') or ''
    history = _parse_json(row.get('history_tables_json'), [])
    if not include_history_data:
        history = [
            {
                'fileName': item.get('fileName'),
                'updatedAt': item.get('updatedAt'),
                'rowCount': max(len(item.get('data') or []) - 1, 0),
            }
            for item in history
            if isinstance(item, dict)
        ]
    return {
        'id': row['id'],
        'name': row.get('name') or '',
        'prefix': row.get('prefix') or '',
        'hasPassword': bool(pwd_hash),
        'currentTable': _parse_json(row.get('current_table_json'), None),
        'historyTables': history,
        'createdAt': created or _now_str(),
        'updatedAt': updated or _now_str(),
    }


def verify_library_password(lib_id: str, password: str) -> bool:
    if not _get_library_row(lib_id):
        return False
    return verify_material_password(password)


def _get_library_row(lib_id: str) -> Optional[Dict[str, Any]]:
    ensure_tables()
    pool = get_connection_pool()
    with pool.get_cursor() as cursor:
        cursor.execute('SELECT * FROM material_db_libraries WHERE id = %s', (lib_id,))
        return cursor.fetchone()


def create_library(
    lib_id: str,
    name: str,
    prefix: str,
    password: str,
    current_table: Optional[Dict[str, Any]],
    user_id: Optional[int],
    user_display: str,
) -> Dict[str, Any]:
    ensure_tables()
    now = _now_str()
    pwd_hash = ensure_material_password_hash(password)
    pool = get_connection_pool()
    with pool.get_cursor() as cursor:
        cursor.execute(
            '''
            INSERT INTO material_db_libraries
            (id, name, prefix, password_hash, current_table_json, history_tables_json, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ''',
            (
                lib_id,
                name,
                prefix or '',
                pwd_hash,
                json.dumps(current_table, ensure_ascii=False) if current_table else None,
                json.dumps([], ensure_ascii=False),
                now,
                now,
            ),
        )
    log_audit(user_id, user_display, 'create_library', lib_id, name)
    if current_table:
        log_audit(user_id, user_display, 'upload_table', lib_id, name, {'fileName': current_table.get('fileName')})
    return get_library(lib_id)


def update_library(
    lib_id: str,
    name: str,
    prefix: str,
    new_table: Optional[Dict[str, Any]],
    new_password: Optional[str],
    user_id: Optional[int],
    user_display: str,
) -> Dict[str, Any]:
    row = _get_library_row(lib_id)
    if not row:
        raise ValueError('物料库不存在')
    history = _parse_json(row.get('history_tables_json'), [])
    current = _parse_json(row.get('current_table_json'), None)
    lib_name = name or row.get('name') or ''

    if new_table:
        if current:
            history = [{
                'fileName': current.get('fileName'),
                'updatedAt': current.get('updatedAt'),
                'data': current.get('data'),
            }] + history
        current = new_table
        log_audit(user_id, user_display, 'upload_table', lib_id, lib_name, {'fileName': new_table.get('fileName')})

    pwd_hash = ensure_material_password_hash()

    now = _now_str()
    pool = get_connection_pool()
    with pool.get_cursor() as cursor:
        cursor.execute(
            '''
            UPDATE material_db_libraries
            SET name=%s, prefix=%s, password_hash=%s, current_table_json=%s,
                history_tables_json=%s, updated_at=%s
            WHERE id=%s
            ''',
            (
                lib_name,
                prefix or '',
                pwd_hash,
                json.dumps(current, ensure_ascii=False) if current else None,
                json.dumps(history, ensure_ascii=False),
                now,
                lib_id,
            ),
        )
    log_audit(user_id, user_display, 'update_library', lib_id, lib_name)
    return get_library(lib_id)


def change_library_password(
    lib_id: str,
    new_password: str,
    user_id: Optional[int],
    user_display: str,
) -> Dict[str, Any]:
    change_material_password(new_password, user_id, user_display)
    return get_library(lib_id)


def delete_library(lib_id: str, user_id: Optional[int], user_display: str) -> bool:
    row = _get_library_row(lib_id)
    if not row:
        return False
    pool = get_connection_pool()
    with pool.get_cursor() as cursor:
        cursor.execute('DELETE FROM material_db_libraries WHERE id = %s', (lib_id,))
    log_audit(user_id, user_display, 'delete_library', lib_id, row.get('name'))
    return True


def update_remark(
    lib_id: str,
    material_code: str,
    remark: str,
    user_id: Optional[int],
    user_display: str,
) -> bool:
    row = _get_library_row(lib_id)
    if not row:
        return False
    current = _parse_json(row.get('current_table_json'), None)
    if not current or not isinstance(current.get('data'), list):
        return False
    data = current['data']
    found = False
    for i in range(1, len(data)):
        r = data[i]
        code = str(r[0]).strip() if r and len(r) > 0 and r[0] is not None else ''
        if code == str(material_code or '').strip():
            while len(r) < 7:
                r.append('')
            r[6] = remark
            found = True
            break
    if not found:
        return False
    pool = get_connection_pool()
    with pool.get_cursor() as cursor:
        cursor.execute(
            'UPDATE material_db_libraries SET current_table_json=%s, updated_at=%s WHERE id=%s',
            (json.dumps(current, ensure_ascii=False), _now_str(), lib_id),
        )
    log_audit(
        user_id,
        user_display,
        'edit_remark',
        lib_id,
        row.get('name'),
        {'materialCode': material_code},
    )
    return True


def batch_import_libraries(
    items: List[Dict[str, Any]],
    overwrite: bool,
    default_prefix: str,
    default_password: str,
    user_id: Optional[int],
    user_display: str,
) -> Dict[str, int]:
    import uuid as _uuid

    ensure_material_password_hash(default_password)
    lib_list = list_libraries()
    by_name = {(l.get('name') or '').strip(): l for l in lib_list}
    created = updated = skipped = 0
    now = _now_str()

    for it in items:
        name = (it.get('name') or '').strip()
        if not name:
            skipped += 1
            continue
        table = it.get('currentTable')
        prefix = it.get('prefix', default_prefix) or ''
        existing = by_name.get(name)

        if existing:
            if not overwrite:
                skipped += 1
                continue
            hist = existing.get('historyTables') or []
            cur = existing.get('currentTable')
            if cur:
                hist = [{
                    'fileName': cur.get('fileName'),
                    'updatedAt': cur.get('updatedAt'),
                    'data': cur.get('data'),
                }] + hist
            pool = get_connection_pool()
            with pool.get_cursor() as cursor:
                cursor.execute(
                    '''
                    UPDATE material_db_libraries
                    SET prefix=%s, current_table_json=%s, history_tables_json=%s, updated_at=%s
                    WHERE id=%s
                    ''',
                    (
                        prefix or existing.get('prefix') or '',
                        json.dumps(table, ensure_ascii=False) if table else None,
                        json.dumps(hist, ensure_ascii=False),
                        now,
                        existing['id'],
                    ),
                )
            log_audit(user_id, user_display, 'upload_table', existing['id'], name, {'source': 'batch'})
            updated += 1
        else:
            lib_id = str(_uuid.uuid4())
            pwd = default_password
            create_library(lib_id, name, prefix, pwd, table, user_id, user_display)
            by_name[name] = {'id': lib_id, 'name': name}
            created += 1

    log_audit(user_id, user_display, 'batch_import', None, None, {
        'created': created,
        'updated': updated,
        'skipped': skipped,
    })
    return {'created': created, 'updated': updated, 'skipped': skipped}


def migrate_from_client(
    libraries: List[Dict[str, Any]],
    default_password: str,
    user_id: Optional[int],
    user_display: str,
) -> int:
    if not libraries:
        return 0
    ensure_material_password_hash(default_password)
    count = 0
    for lib in libraries:
        lib_id = lib.get('id') or secrets.token_hex(16)
        name = (lib.get('name') or '未命名物料库').strip()
        if _get_library_row(lib_id):
            continue
        pwd = default_password.strip()
        create_library(
            lib_id,
            name,
            lib.get('prefix') or '',
            pwd,
            lib.get('currentTable'),
            user_id,
            user_display,
        )
        hist = lib.get('historyTables') or []
        if hist:
            pool = get_connection_pool()
            with pool.get_cursor() as cursor:
                cursor.execute(
                    'UPDATE material_db_libraries SET history_tables_json=%s WHERE id=%s',
                    (json.dumps(hist, ensure_ascii=False), lib_id),
                )
        count += 1
    log_audit(user_id, user_display, 'migrate_local', None, None, {'count': count})
    return count


def list_audit_logs(
    library_id: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    ensure_tables()
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    pool = get_connection_pool()
    with pool.get_cursor() as cursor:
        if library_id:
            cursor.execute(
                '''
                SELECT id, user_id, user_display, action, library_id, library_name, detail, created_at
                FROM material_db_audit
                WHERE library_id = %s
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                ''',
                (library_id, limit, offset),
            )
        else:
            cursor.execute(
                '''
                SELECT id, user_id, user_display, action, library_id, library_name, detail, created_at
                FROM material_db_audit
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                ''',
                (limit, offset),
            )
        rows = cursor.fetchall() or []
    out = []
    for row in rows:
        created = row.get('created_at')
        if hasattr(created, 'strftime'):
            created = created.strftime('%Y-%m-%d %H:%M:%S')
        item = {
            'id': row.get('id'),
            'userDisplay': row.get('user_display'),
            'action': row.get('action'),
            'libraryId': row.get('library_id'),
            'libraryName': row.get('library_name'),
            'detail': _parse_json(row.get('detail'), None),
            'createdAt': created,
            'message': format_audit_message(row),
        }
        out.append(item)
    return out


def _get_setting(key: str, default: Any = None) -> Any:
    ensure_tables()
    pool = get_connection_pool()
    with pool.get_cursor() as cursor:
        cursor.execute(
            'SELECT setting_value FROM material_db_settings WHERE setting_key = %s',
            (key,),
        )
        row = cursor.fetchone()
    if not row:
        return default
    val = row.get('setting_value') if isinstance(row, dict) else row[0]
    return val if val is not None else default


def _set_setting(key: str, value: str) -> None:
    ensure_tables()
    pool = get_connection_pool()
    now = _now_str()
    with pool.get_cursor() as cursor:
        cursor.execute(
            '''
            INSERT INTO material_db_settings (setting_key, setting_value, updated_at)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value), updated_at = VALUES(updated_at)
            ''',
            (key, value, now),
        )


def ensure_material_password_hash(seed_password: str = '') -> str:
    """返回全局物料库密码哈希；首次启用时用环境变量或兼容入参初始化。"""
    pwd_hash = (_get_setting(MATERIAL_PASSWORD_SETTING_KEY) or '').strip()
    if pwd_hash:
        return pwd_hash
    seed = (
        (os.getenv('MATERIAL_DB_GLOBAL_PASSWORD') or '').strip()
        or (os.getenv('YIDA_LIBRARY_PASSWORD') or '').strip()
        or (seed_password or '').strip()
    )
    if not seed:
        raise ValueError('未配置物料库共用密码（MATERIAL_DB_GLOBAL_PASSWORD）')
    pwd_hash = PasswordHasher.hash_password(seed)
    _set_setting(MATERIAL_PASSWORD_SETTING_KEY, pwd_hash)
    pool = get_connection_pool()
    with pool.get_cursor() as cursor:
        cursor.execute(
            'UPDATE material_db_libraries SET password_hash=%s, updated_at=%s',
            (pwd_hash, _now_str()),
        )
    return pwd_hash


def verify_material_password(password: str) -> bool:
    try:
        pwd_hash = ensure_material_password_hash()
    except ValueError:
        return False
    return PasswordHasher.verify_password(password or '', pwd_hash)


def change_material_password(
    new_password: str,
    user_id: Optional[int],
    user_display: str,
) -> None:
    password = (new_password or '').strip()
    if not password:
        raise ValueError('请设置新的物料库共用密码')
    pwd_hash = PasswordHasher.hash_password(password)
    _set_setting(MATERIAL_PASSWORD_SETTING_KEY, pwd_hash)
    pool = get_connection_pool()
    with pool.get_cursor() as cursor:
        cursor.execute(
            'UPDATE material_db_libraries SET password_hash=%s, updated_at=%s',
            (pwd_hash, _now_str()),
        )
    clear_material_unlock_tokens()
    log_audit(
        user_id,
        user_display,
        'change_password',
        MATERIAL_LIBRARY_MODULE_ID,
        '全部物料库（共用密码）',
    )


def replacement_password_configured() -> bool:
    return bool((_get_setting('replacement_pairs_password_hash') or '').strip())


def verify_replacement_password(password: str) -> bool:
    pwd_hash = _get_setting('replacement_pairs_password_hash') or ''
    if not pwd_hash:
        return False
    return PasswordHasher.verify_password(password or '', pwd_hash)


def set_replacement_password(
    password: str,
    user_id: Optional[int],
    user_display: str,
    old_password: Optional[str] = None,
) -> None:
    if not (password or '').strip():
        raise ValueError('请设置替换对管理密码')
    configured = replacement_password_configured()
    if configured:
        if not old_password or not verify_replacement_password(old_password):
            raise ValueError('原密码错误')
    pwd_hash = PasswordHasher.hash_password(password.strip())
    _set_setting('replacement_pairs_password_hash', pwd_hash)
    log_audit(
        user_id,
        user_display,
        'replacement_set_password',
        REPLACEMENT_MODULE_ID,
        '替换对管理',
        None,
    )


def get_replacement_groups() -> List[Dict[str, Any]]:
    raw = _get_setting('replacement_groups_json', '[]')
    groups = _parse_json(raw, [])
    if not isinstance(groups, list):
        return []
    return groups


def save_replacement_groups(
    groups: List[Dict[str, Any]],
    user_id: Optional[int],
    user_display: str,
    action: str = 'replacement_update',
) -> List[Dict[str, Any]]:
    if not isinstance(groups, list):
        raise ValueError('替换组数据格式无效')
    _set_setting('replacement_groups_json', json.dumps(groups, ensure_ascii=False))
    log_audit(
        user_id,
        user_display,
        action,
        REPLACEMENT_MODULE_ID,
        '替换对管理',
        {'count': len(groups)},
    )
    return groups


def create_replacement_unlock_token(user_id: int) -> Tuple[str, int]:
    return create_unlock_token(user_id, REPLACEMENT_MODULE_ID)


def verify_replacement_unlock_token(token: Optional[str], user_id: int) -> bool:
    return verify_unlock_token(token, user_id, REPLACEMENT_MODULE_ID)
