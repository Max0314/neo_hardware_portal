# -*- coding: utf-8 -*-
"""公告阅读催办：向未完成待办（未读）人员发送钉钉工作通知。"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from server.config import DINGTALK_CONFIG, PUBLIC_BASE_URL
from server.dingtalk_notify_util import get_dingtalk_access_token_unified, send_corpconversation_with_retry
from server.dingtalk_url_util import build_announcement_detail_dingtalk_url
from server.logger import logger


def _is_todo_pending(todo: dict) -> bool:
    status = str(todo.get('status') or '未完成')
    done = todo.get('done', False)
    userid = str(todo.get('userid') or '').strip()
    if not userid:
        return False
    if status in ('已完成', 'done') or done is True:
        return False
    return True


def notify_pending_readers(
    announcement_mgr: Any,
    todo_mgr: Any,
    *,
    announcement_id: Optional[str] = None,
    base_url: Optional[str] = None,
    resolve_userids: Optional[Callable[[List[str]], List[str]]] = None,
    filter_userids: Optional[Callable[[List[str]], List[str]]] = None,
) -> Dict[str, Any]:
    """
    对已审批公告中未完成阅读待办的用户发送工作通知。
    announcement_id 为空时处理全部已审批公告。
    """
    base_url = (base_url or PUBLIC_BASE_URL or '').rstrip('/')
    announcements = announcement_mgr.get_announcements(status='approved', include_temp=False)
    if announcement_id:
        aid = str(announcement_id).strip()
        announcements = [a for a in announcements if isinstance(a, dict) and str(a.get('id') or '') == aid]
        if not announcements:
            return {
                'success': False,
                'error': '公告不存在或未审批通过',
                'announcements_processed': 0,
                'users_notified': 0,
                'users_failed': 0,
                'details': [],
            }

    access_token = get_dingtalk_access_token_unified()
    if not access_token:
        return {
            'success': False,
            'error': '无法获取钉钉 access_token',
            'announcements_processed': 0,
            'users_notified': 0,
            'users_failed': 0,
            'details': [],
        }

    announcements_processed = 0
    users_notified = 0
    users_failed = 0
    details: List[Dict[str, Any]] = []

    for announcement in announcements:
        if not isinstance(announcement, dict):
            continue
        aid = str(announcement.get('id') or '').strip()
        title = str(announcement.get('title') or '无标题').strip()
        if not aid:
            continue

        todos = todo_mgr.get_all_todos(aid)
        if not todos:
            continue

        pending_userids = []
        for todo in todos:
            if not isinstance(todo, dict) or not _is_todo_pending(todo):
                continue
            uid = str(todo.get('userid') or '').strip()
            if uid and uid not in pending_userids:
                pending_userids.append(uid)

        if not pending_userids:
            details.append({
                'announcement_id': aid,
                'title': title,
                'pending_count': 0,
                'notified': 0,
                'skipped': True,
            })
            continue

        if resolve_userids:
            pending_userids = resolve_userids(pending_userids)
        if filter_userids:
            pending_userids = filter_userids(pending_userids)

        if not pending_userids:
            details.append({
                'announcement_id': aid,
                'title': title,
                'pending_count': len(todos),
                'notified': 0,
                'error': '无有效钉钉 userid',
            })
            continue

        detail_url = build_announcement_detail_dingtalk_url(aid, base_url)
        msg_content = {
            'msgtype': 'link',
            'link': {
                'title': title,
                'text': f'请及时阅读公告：{title}',
                'messageUrl': detail_url,
                'picUrl': 'https://img.alicdn.com/imgextra/i1/O1CN01Kq8eYq1xWqJY5Y5Y5_!!6000000006441-2-tps-200-200.png',
            },
        }
        ok, err = send_corpconversation_with_retry(
            access_token,
            pending_userids,
            msg_content,
            log_context=f' 催读公告={aid}',
        )
        n = len(pending_userids)
        if ok:
            announcements_processed += 1
            users_notified += n
            details.append({
                'announcement_id': aid,
                'title': title,
                'pending_count': n,
                'notified': n,
            })
            logger.info('催读通知已发送: %s (%s), %s 人', title, aid, n)
        else:
            announcements_processed += 1
            users_failed += n
            details.append({
                'announcement_id': aid,
                'title': title,
                'pending_count': n,
                'notified': 0,
                'error': err or '发送失败',
            })
            logger.warning('催读通知失败: %s (%s): %s', title, aid, err)

    if not details and not announcement_id:
        return {
            'success': True,
            'message': '没有需要催读的公告或全部已完成阅读',
            'announcements_processed': 0,
            'users_notified': 0,
            'users_failed': 0,
            'details': [],
        }

    return {
        'success': users_failed == 0 or users_notified > 0,
        'message': f'已处理 {announcements_processed} 条公告，通知 {users_notified} 人'
        + (f'，失败 {users_failed} 人' if users_failed else ''),
        'announcements_processed': announcements_processed,
        'users_notified': users_notified,
        'users_failed': users_failed,
        'details': details,
    }
