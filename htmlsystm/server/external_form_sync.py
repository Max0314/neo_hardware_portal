# -*- coding: utf-8 -*-
"""通用宜搭实例同步器：把 FORM-* 实例原样拉回来入库 + 记录同步状态。

职责边界（见对接方案）：只做“宜搭实例同步”，不理解业务字段。
- 原始仓库 external_form_instance_raw：唯一键 source_system+form_uuid+form_instance_id，幂等 upsert，保留完整原始 JSON。
- 同步进度 external_form_sync_checkpoint：每张表单一行，记录窗口/状态/条数/错误。

物料投影（4 字段写物料库）由 material_yida_projection.py 基于本表的原始 JSON 完成（阶段 2）。
"""
from __future__ import annotations

import json
import uuid as _uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from server.db_adapter import get_connection_pool
from server.logger import logger
from server.yida_client import extract_instance_meta, iter_form_instances
from server.yida_config import SOURCE_SYSTEM


def _now_str() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def ensure_tables() -> None:
    pool = get_connection_pool()
    with pool.get_cursor() as cursor:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS external_form_instance_raw (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                source_system VARCHAR(64) NOT NULL,
                source_name VARCHAR(255) DEFAULT '',
                app_type VARCHAR(128) DEFAULT '',
                form_uuid VARCHAR(128) NOT NULL,
                form_name VARCHAR(255) DEFAULT '',
                form_instance_id VARCHAR(128) NOT NULL,
                created_time VARCHAR(64) DEFAULT '',
                modified_time VARCHAR(64) DEFAULT '',
                originator_user_id VARCHAR(128) DEFAULT '',
                originator_name VARCHAR(255) DEFAULT '',
                raw_payload_json LONGTEXT,
                form_data_json LONGTEXT,
                sync_batch_id VARCHAR(64) DEFAULT '',
                synced_at DATETIME NOT NULL,
                sync_status VARCHAR(32) DEFAULT 'ready',
                error_message TEXT NULL,
                UNIQUE KEY uk_src_form_inst (source_system, form_uuid, form_instance_id),
                INDEX idx_efr_form (form_uuid),
                INDEX idx_efr_batch (sync_batch_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS external_form_sync_checkpoint (
                source_system VARCHAR(64) NOT NULL,
                form_uuid VARCHAR(128) NOT NULL,
                last_window_start VARCHAR(64) DEFAULT '',
                last_window_end VARCHAR(64) DEFAULT '',
                last_success_at DATETIME NULL,
                last_status VARCHAR(32) DEFAULT '',
                last_error TEXT NULL,
                last_row_count INT DEFAULT 0,
                updated_at DATETIME NOT NULL,
                PRIMARY KEY (source_system, form_uuid)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        ''')


def _upsert_raw_instances(rows: List[Dict[str, Any]]) -> int:
    """幂等写入原始实例。Returns: 受影响条数（按传入条数计）。"""
    if not rows:
        return 0
    pool = get_connection_pool()
    sql = '''
        INSERT INTO external_form_instance_raw
            (source_system, source_name, app_type, form_uuid, form_name, form_instance_id,
             created_time, modified_time, originator_user_id, originator_name,
             raw_payload_json, form_data_json, sync_batch_id, synced_at, sync_status, error_message)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
            source_name=VALUES(source_name),
            app_type=VALUES(app_type),
            form_name=VALUES(form_name),
            created_time=VALUES(created_time),
            modified_time=VALUES(modified_time),
            originator_user_id=VALUES(originator_user_id),
            originator_name=VALUES(originator_name),
            raw_payload_json=VALUES(raw_payload_json),
            form_data_json=VALUES(form_data_json),
            sync_batch_id=VALUES(sync_batch_id),
            synced_at=VALUES(synced_at),
            sync_status=VALUES(sync_status),
            error_message=VALUES(error_message)
    '''
    with pool.get_cursor() as cursor:
        cursor.executemany(sql, rows)
    return len(rows)


def _update_checkpoint(form_uuid: str, window_start: str, window_end: str,
                       status: str, row_count: int, error: Optional[str]) -> None:
    pool = get_connection_pool()
    now = _now_str()
    success_at = now if status in ('success', 'partial_success') else None
    with pool.get_cursor() as cursor:
        cursor.execute(
            '''
            INSERT INTO external_form_sync_checkpoint
                (source_system, form_uuid, last_window_start, last_window_end,
                 last_success_at, last_status, last_error, last_row_count, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
                last_window_start=VALUES(last_window_start),
                last_window_end=VALUES(last_window_end),
                last_success_at=COALESCE(VALUES(last_success_at), last_success_at),
                last_status=VALUES(last_status),
                last_error=VALUES(last_error),
                last_row_count=VALUES(last_row_count),
                updated_at=VALUES(updated_at)
            ''',
            (SOURCE_SYSTEM, form_uuid, window_start, window_end,
             success_at, status, error, int(row_count or 0), now),
        )


def sync_form(
    source: Dict[str, Any],
    *,
    create_from_gmt: str,
    create_to_gmt: str,
    batch_id: Optional[str] = None,
) -> Dict[str, Any]:
    """同步一张表单某个创建时间窗口的实例到原始仓库。

    source: {'form_uuid', 'source_name'(可选), 'form_name'(可选)}
    Returns: {form_uuid, row_count, status, error, batch_id}
    """
    ensure_tables()
    form_uuid = source['form_uuid']
    source_name = source.get('source_name', '')
    form_name = source.get('form_name', '') or source_name
    batch_id = batch_id or f"{SOURCE_SYSTEM}_{form_uuid}_{int(datetime.now().timestamp() * 1000)}"
    now = _now_str()

    buffer: List[Dict[str, Any]] = []
    written = 0
    BATCH = 200

    def flush():
        nonlocal written
        if buffer:
            written += _upsert_raw_instances(buffer)
            buffer.clear()

    try:
        for inst in iter_form_instances(
            form_uuid,
            create_from_gmt=create_from_gmt,
            create_to_gmt=create_to_gmt,
        ):
            meta = extract_instance_meta(inst)
            inst_id = meta.get('form_instance_id')
            if not inst_id:
                logger.warning(f'宜搭实例缺少 formInstanceId，跳过：{form_uuid}')
                continue
            buffer.append((
                SOURCE_SYSTEM, source_name, source.get('app_type', ''),
                form_uuid, form_name, str(inst_id),
                meta.get('created_time') or '', meta.get('modified_time') or '',
                meta.get('originator_user_id') or '', meta.get('originator_name') or '',
                json.dumps(inst, ensure_ascii=False),
                json.dumps(meta.get('form_data') or {}, ensure_ascii=False),
                batch_id, now, 'ready', None,
            ))
            if len(buffer) >= BATCH:
                flush()
        flush()
        _update_checkpoint(form_uuid, create_from_gmt, create_to_gmt, 'success', written, None)
        logger.info(f'✅ 宜搭同步完成 {form_uuid}: 写入 {written} 条（batch={batch_id}）')
        return {'form_uuid': form_uuid, 'row_count': written, 'status': 'success', 'error': None, 'batch_id': batch_id}
    except Exception as e:
        flush_err = None
        try:
            flush()
        except Exception as fe:
            flush_err = str(fe)
        msg = str(e) if not flush_err else f'{e}; flush:{flush_err}'
        logger.error(f'❌ 宜搭同步失败 {form_uuid}: {msg}', exc_info=True)
        _update_checkpoint(form_uuid, create_from_gmt, create_to_gmt, 'error', written, msg)
        return {'form_uuid': form_uuid, 'row_count': written, 'status': 'error', 'error': msg, 'batch_id': batch_id}


def get_checkpoints() -> List[Dict[str, Any]]:
    ensure_tables()
    pool = get_connection_pool()
    with pool.get_cursor() as cursor:
        cursor.execute('SELECT * FROM external_form_sync_checkpoint WHERE source_system=%s ORDER BY form_uuid', (SOURCE_SYSTEM,))
        return cursor.fetchall() or []
