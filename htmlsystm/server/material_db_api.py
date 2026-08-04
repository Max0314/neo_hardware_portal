#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""物料数据库 REST API（/api/material-db/*）。"""
import json
import re
import uuid
import urllib.parse
from typing import Any, Dict, Optional
from urllib.parse import parse_qs

from server import material_db_manager as mdb
from server.neo_points_client import award_neo_points
from server.logger import logger


class MaterialDbApi:
    """将 HTTP 请求分派到 material_db_manager。"""

    def __init__(self, handler: Any):
        self.h = handler

    def _can_change_password_without_old_password(self, user: Dict[str, Any]) -> bool:
        roles = user.get('roles') or []
        if isinstance(roles, str):
            roles = [r.strip() for r in roles.split(',') if r.strip()]
        return bool({'admin', 'management', 'super_admin'} & set(roles))

    def dispatch(self, method: str, path: str, parsed_path: Any) -> None:
        if not self.h.check_auth():
            return
        user = self.h.get_current_user() or {}
        user_id = user.get('id')
        user_display = user.get('name') or user.get('username') or '未知用户'

        query = parse_qs(parsed_path.query or '')
        body = self._read_json_body() if method in ('POST', 'PUT', 'PATCH') else {}

        # GET /api/material-db/dingtalk-open-url
        if method == 'GET' and path == '/api/material-db/dingtalk-open-url':
            from server.dingtalk_url_util import build_material_db_dingtalk_url
            base = ''
            if hasattr(self.h, '_build_public_base_url'):
                base = self.h._build_public_base_url()
            open_url = build_material_db_dingtalk_url(base)
            page_path = '/neo/systm_tool/material-database.html'
            web_url = (base.rstrip('/') + page_path) if base else page_path
            self.h.send_json_response({
                'success': True,
                'dingtalk_open_url': open_url,
                'web_url': web_url,
            })
            return

        # GET /api/material-db/libraries
        if method == 'GET' and path == '/api/material-db/libraries':
            libs = mdb.list_libraries(include_history_data=False)
            from server.dingtalk_url_util import build_material_db_dingtalk_url
            base = ''
            if hasattr(self.h, '_build_public_base_url'):
                base = self.h._build_public_base_url()
            dingtalk_open_url = build_material_db_dingtalk_url(base)
            self.h.send_json_response({
                'success': True,
                'libraries': libs,
                'dingtalk_open_url': dingtalk_open_url,
            })
            return

        # GET /api/material-db/audit-logs
        if method == 'GET' and path == '/api/material-db/audit-logs':
            lib_id = (query.get('library_id') or [None])[0]
            limit = int((query.get('limit') or ['100'])[0])
            offset = int((query.get('offset') or ['0'])[0])
            logs = mdb.list_audit_logs(lib_id, limit, offset)
            self.h.send_json_response({'success': True, 'logs': logs})
            return

        # GET /api/material-db/yida-sync-status  宜搭同步进度/上次结果
        if method == 'GET' and path == '/api/material-db/yida-sync-status':
            from server.yida_sync_runner import get_status
            self.h.send_json_response({'success': True, 'status': get_status()})
            return

        # POST /api/material-db/yida-sync  触发宜搭→物料库同步（后台线程，管理员）
        if method == 'POST' and path == '/api/material-db/yida-sync':
            if not (self.h._is_super_admin(user) or self.h._has_role(user, 'admin')
                    or self.h._has_role(user, 'management')):
                self.h.send_json_response({'success': False, 'error': '仅管理员可触发宜搭同步'}, status=403)
                return
            from server.yida_config import (
                check_yida_config, check_material_sync_config, LIBRARY_PASSWORD,
            )
            ok, err = check_yida_config()
            if not ok:
                self.h.send_json_response({'success': False, 'error': err}, status=400)
                return
            ok, err = check_material_sync_config()
            if not ok:
                self.h.send_json_response({'success': False, 'error': err}, status=400)
                return
            # 预检库密码：否则同步会启动、但每张表都因缺密码失败(成功 0/N)，原因不直观
            if not LIBRARY_PASSWORD:
                self.h.send_json_response({
                    'success': False,
                    'error': '未配置 YIDA_LIBRARY_PASSWORD（物料库默认访问密码）。'
                             '请在服务器 .env 中添加后重建 htmlsystm 容器，再触发同步。',
                }, status=400)
                return
            from server.yida_sync_runner import start_background_sync, get_status
            started, msg = start_background_sync(user_display)
            self.h.send_json_response({'success': started, 'message': msg, 'status': get_status()})
            return

        m = re.match(r'^/api/material-db/libraries/([^/]+)$', path)
        if m:
            lib_id = m.group(1)
            if method == 'GET':
                lib = mdb.get_library(lib_id)
                if not lib:
                    self.h.send_json_response({'success': False, 'error': '物料库不存在'}, status=404)
                    return
                self.h.send_json_response({'success': True, 'library': lib})
                return
            if method == 'PUT':
                if not self._require_unlock(lib_id, user_id, body):
                    return
                try:
                    lib = mdb.update_library(
                        lib_id,
                        (body.get('name') or '').strip(),
                        body.get('prefix') or '',
                        body.get('currentTable'),
                        body.get('newPassword'),
                        user_id,
                        user_display,
                    )
                    self.h.send_json_response({'success': True, 'library': lib})
                    award_neo_points(user, 'material_db_edit')
                except ValueError as e:
                    self.h.send_json_response({'success': False, 'error': str(e)}, status=400)
                return
            if method == 'DELETE':
                if not self._require_unlock(lib_id, user_id, body):
                    return
                ok = mdb.delete_library(lib_id, user_id, user_display)
                if ok and getattr(self.h, 'user_manager', None):
                    try:
                        n = self.h.user_manager.remove_library_id_from_all_users(lib_id)
                        if n:
                            logger.info(f"delete_library: 已从 {n} 个用户移除库 {lib_id} 的 library_roles")
                    except Exception as e:
                        logger.warning(f"delete_library: 清理用户 library_roles 失败: {e}", exc_info=True)
                self.h.send_json_response({'success': ok})
                return

        if method == 'POST' and path == '/api/material-db/change-password':
            new_password = body.get('newPassword') or body.get('new_password') or ''
            if not self._can_change_password_without_old_password(user):
                old_password = body.get('oldPassword') or body.get('old_password') or ''
                if not mdb.verify_material_password(old_password):
                    self.h.send_json_response({'success': False, 'error': '原密码错误'}, status=403)
                    return
            try:
                mdb.change_material_password(new_password, user_id, user_display)
                self.h.send_json_response({'success': True})
                award_neo_points(user, 'material_db_edit')
            except ValueError as e:
                self.h.send_json_response({'success': False, 'error': str(e)}, status=400)
            return

        # 兼容旧客户端：单库改密入口也会修改全部物料库的共用密码。
        m_change_password = re.match(r'^/api/material-db/libraries/([^/]+)/change-password$', path)
        if m_change_password and method == 'POST':
            lib_id = m_change_password.group(1)
            new_password = body.get('newPassword') or body.get('new_password') or ''
            if not self._can_change_password_without_old_password(user):
                old_password = body.get('oldPassword') or body.get('old_password') or ''
                if not mdb.verify_material_password(old_password):
                    self.h.send_json_response({'success': False, 'error': '原密码错误'}, status=403)
                    return
            try:
                lib = mdb.change_library_password(lib_id, new_password, user_id, user_display)
                self.h.send_json_response({'success': True, 'library': lib})
                award_neo_points(user, 'material_db_edit')
            except ValueError as e:
                self.h.send_json_response({'success': False, 'error': str(e)}, status=400)
            return

        if method == 'POST' and path == '/api/material-db/unlock':
            password = body.get('password') or ''
            if not mdb.verify_material_password(password):
                self.h.send_json_response({'success': False, 'error': '密码错误'}, status=403)
                return
            token, expires_at = mdb.create_material_unlock_token(user_id)
            self.h.send_json_response({
                'success': True,
                'unlockToken': token,
                'expiresAt': expires_at,
            })
            return

        m_unlock = re.match(r'^/api/material-db/libraries/([^/]+)/unlock$', path)
        if m_unlock and method == 'POST':
            lib_id = m_unlock.group(1)
            password = body.get('password') or ''
            if not mdb.verify_library_password(lib_id, password):
                self.h.send_json_response({'success': False, 'error': '密码错误'}, status=403)
                return
            token, expires_at = mdb.create_material_unlock_token(user_id)
            self.h.send_json_response({
                'success': True,
                'unlockToken': token,
                'expiresAt': expires_at,
            })
            return

        m_audit = re.match(r'^/api/material-db/libraries/([^/]+)/audit$', path)
        if m_audit and method == 'POST':
            lib_id = m_audit.group(1)
            if not self._require_unlock(lib_id, user_id, body):
                return
            action = body.get('action') or 'download_current'
            lib = mdb.get_library(lib_id)
            lib_name = (lib or {}).get('name') or ''
            detail = body.get('detail')
            if action in mdb.ACTION_LABELS:
                mdb.log_audit(user_id, user_display, action, lib_id, lib_name, detail)
            self.h.send_json_response({'success': True})
            return

        if method == 'POST' and path == '/api/material-db/libraries':
            if not self._require_unlock(mdb.MATERIAL_LIBRARY_MODULE_ID, user_id, body):
                return
            try:
                lib_id = str(uuid.uuid4())
                lib = mdb.create_library(
                    lib_id,
                    (body.get('name') or '').strip(),
                    body.get('prefix') or '',
                    '',
                    body.get('currentTable'),
                    user_id,
                    user_display,
                )
                self.h.send_json_response({'success': True, 'library': lib})
                award_neo_points(user, 'material_db_edit')
            except ValueError as e:
                self.h.send_json_response({'success': False, 'error': str(e)}, status=400)
            return

        if method == 'POST' and path == '/api/material-db/batch-import':
            if not self._require_unlock(mdb.MATERIAL_LIBRARY_MODULE_ID, user_id, body):
                return
            try:
                items = body.get('items') or []
                overwrite = bool(body.get('overwrite', True))
                unlock_token = self._unlock_token_from(body)
                if overwrite:
                    by_name = {(l.get('name') or '').strip(): l for l in mdb.list_libraries()}
                    for it in items:
                        name = (it.get('name') or '').strip()
                        existing = by_name.get(name)
                        if not existing:
                            continue
                        if not mdb.verify_unlock_token(unlock_token, user_id, existing['id']):
                            self.h.send_json_response({
                                'success': False,
                                'error': f'更新「{name}」须先验证物料库共用密码',
                                'needPassword': True,
                                'libraryId': existing['id'],
                            }, status=403)
                            return
                stats = mdb.batch_import_libraries(
                    body.get('items') or [],
                    bool(body.get('overwrite', True)),
                    body.get('defaultPrefix') or '',
                    '',
                    user_id,
                    user_display,
                )
                self.h.send_json_response({'success': True, **stats})
            except ValueError as e:
                self.h.send_json_response({'success': False, 'error': str(e)}, status=400)
            return

        if method == 'POST' and path == '/api/material-db/migrate':
            try:
                count = mdb.migrate_from_client(
                    body.get('libraries') or [],
                    body.get('defaultPassword') or '',
                    user_id,
                    user_display,
                )
                self.h.send_json_response({'success': True, 'migrated': count})
            except ValueError as e:
                self.h.send_json_response({'success': False, 'error': str(e)}, status=400)
            return

        if method == 'POST' and path == '/api/material-db/remark':
            lib_id = body.get('libraryId') or ''
            if not self._require_unlock(lib_id, user_id, body):
                return
            ok = mdb.update_remark(
                lib_id,
                body.get('materialCode') or '',
                body.get('remark') or '',
                user_id,
                user_display,
            )
            self.h.send_json_response({'success': ok})
            if ok:
                award_neo_points(user, 'material_db_edit')
            return

        if method == 'POST' and path == '/api/material-db/audit-export-all':
            mdb.log_audit(user_id, user_display, 'export_all', None, None, body.get('detail'))
            self.h.send_json_response({'success': True})
            return

        # ---------- 替换对管理（独立管理密码，参考物料库 unlock 机制）----------
        if method == 'GET' and path == '/api/material-db/replacement-groups':
            groups = mdb.get_replacement_groups()
            self.h.send_json_response({
                'success': True,
                'groups': groups,
                'passwordConfigured': mdb.replacement_password_configured(),
            })
            return

        if method == 'GET' and path == '/api/material-db/replacement-groups/password-status':
            self.h.send_json_response({
                'success': True,
                'configured': mdb.replacement_password_configured(),
            })
            return

        if method == 'POST' and path == '/api/material-db/replacement-groups/set-password':
            try:
                mdb.set_replacement_password(
                    body.get('password') or '',
                    user_id,
                    user_display,
                    old_password=body.get('oldPassword'),
                )
                self.h.send_json_response({'success': True})
            except ValueError as e:
                self.h.send_json_response({'success': False, 'error': str(e)}, status=400)
            return

        if method == 'POST' and path == '/api/material-db/replacement-groups/unlock':
            if not mdb.replacement_password_configured():
                self.h.send_json_response({
                    'success': False,
                    'error': '尚未设置替换对管理密码，请先设置',
                    'needSetupPassword': True,
                }, status=403)
                return
            password = body.get('password') or ''
            if not mdb.verify_replacement_password(password):
                self.h.send_json_response({'success': False, 'error': '密码错误'}, status=403)
                return
            token, expires_at = mdb.create_replacement_unlock_token(user_id)
            self.h.send_json_response({
                'success': True,
                'unlockToken': token,
                'expiresAt': expires_at,
            })
            return

        if method == 'PUT' and path == '/api/material-db/replacement-groups':
            if not self._require_replacement_unlock(user_id, body):
                return
            try:
                groups = mdb.save_replacement_groups(
                    body.get('groups') or [],
                    user_id,
                    user_display,
                    action=body.get('auditAction') or 'replacement_update',
                )
                self.h.send_json_response({'success': True, 'groups': groups})
                award_neo_points(user, 'material_db_edit')
            except ValueError as e:
                self.h.send_json_response({'success': False, 'error': str(e)}, status=400)
            return

        if method == 'POST' and path == '/api/material-db/replacement-groups/migrate':
            if not self._require_replacement_unlock(user_id, body):
                return
            try:
                groups = body.get('groups') or []
                if not mdb.replacement_password_configured():
                    pwd = body.get('password') or ''
                    if not pwd:
                        self.h.send_json_response({
                            'success': False,
                            'error': '首次迁移请同时设置替换对管理密码',
                            'needSetupPassword': True,
                        }, status=400)
                        return
                    mdb.set_replacement_password(pwd, user_id, user_display)
                saved = mdb.save_replacement_groups(
                    groups,
                    user_id,
                    user_display,
                    action='replacement_migrate',
                )
                self.h.send_json_response({'success': True, 'groups': saved, 'migrated': len(saved)})
            except ValueError as e:
                self.h.send_json_response({'success': False, 'error': str(e)}, status=400)
            return

        self.h.send_error(404, '接口不存在')

    def _read_json_body(self) -> Dict[str, Any]:
        try:
            length = int(self.h.headers.get('Content-Length', 0))
            if length <= 0:
                return {}
            raw = self.h.rfile.read(length).decode('utf-8')
            return json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return {}

    def _unlock_token_from(self, body: Dict[str, Any]) -> Optional[str]:
        return (
            self.h.headers.get('X-Material-Unlock-Token')
            or body.get('unlockToken')
        )

    def _require_unlock(self, lib_id: str, user_id: int, body: Dict[str, Any]) -> bool:
        token = self._unlock_token_from(body)
        if mdb.verify_unlock_token(token, user_id, lib_id):
            return True
        password = body.get('password')
        if password and mdb.verify_library_password(lib_id, password):
            return True
        self.h.send_json_response(
            {'success': False, 'error': '请先验证物料库密码', 'needPassword': True},
            status=403,
        )
        return False

    def _require_replacement_unlock(self, user_id: int, body: Dict[str, Any]) -> bool:
        token = self._unlock_token_from(body)
        if mdb.verify_replacement_unlock_token(token, user_id):
            return True
        password = body.get('password')
        if password and mdb.verify_replacement_password(password):
            return True
        if not mdb.replacement_password_configured():
            self.h.send_json_response({
                'success': False,
                'error': '尚未设置替换对管理密码，请先设置',
                'needSetupPassword': True,
            }, status=403)
            return False
        self.h.send_json_response({
            'success': False,
            'error': '请先验证替换对管理密码',
            'needPassword': True,
        }, status=403)
        return False

    def _require_unlock_global(self, user_id: int, body: Dict[str, Any]) -> bool:
        """批量/导出：接受请求体中的 unlockTokens: {libId: token} 或单次 password + libraryId。"""
        tokens = body.get('unlockTokens') or {}
        if isinstance(tokens, dict) and tokens:
            lib_id = body.get('libraryId')
            if lib_id and mdb.verify_unlock_token(tokens.get(lib_id), user_id, lib_id):
                return True
        lib_id = body.get('libraryId')
        if lib_id:
            return self._require_unlock(lib_id, user_id, body)
        password = body.get('password')
        if password and lib_id and mdb.verify_library_password(lib_id, password):
            return True
        # 批量导入新建库不需要已有库 unlock，仅需 defaultPassword
        if body.get('defaultPassword'):
            return True
        self.h.send_json_response(
            {'success': False, 'error': '请先验证物料库密码', 'needPassword': True},
            status=403,
        )
        return False
