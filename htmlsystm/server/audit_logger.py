#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
操作日志记录模块
记录系统关键操作，用于审计和追踪
"""
import json
from datetime import datetime
from typing import Optional, Dict, Any
from server.db_adapter import get_connection_pool
from server.logger import logger


class AuditLogger:
    """操作日志记录器"""
    
    @staticmethod
    def log_action(
        user_id: Optional[int],
        action: str,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ):
        """
        记录操作日志
        
        Args:
            user_id: 用户ID
            action: 操作类型（如 'create_announcement', 'approve_announcement', 'delete_announcement'）
            resource_type: 资源类型（如 'announcement', 'user', 'board'）
            resource_id: 资源ID
            details: 详细信息（字典）
            ip_address: IP地址
            user_agent: 用户代理
        """
        try:
            pool = get_connection_pool()
            with pool.get_cursor() as cursor:
                details_json = json.dumps(details, ensure_ascii=False) if details else None
                
                cursor.execute('''
                    INSERT INTO audit_logs (user_id, action, resource_type, resource_id, details, ip_address, user_agent, created_time)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                ''', (
                    user_id,
                    action,
                    resource_type,
                    resource_id,
                    details_json,
                    ip_address,
                    user_agent
                ))
                
                logger.debug(f"操作日志已记录: user_id={user_id}, action={action}, resource_type={resource_type}, resource_id={resource_id}")
        except Exception as e:
            logger.error(f"记录操作日志失败: {e}", exc_info=True)
    
    @staticmethod
    def log_announcement_create(user_id: Optional[int], announcement_id: str, title: str, status: str, ip_address: Optional[str] = None, user_agent: Optional[str] = None):
        """记录公告创建操作"""
        AuditLogger.log_action(
            user_id=user_id,
            action='create_announcement',
            resource_type='announcement',
            resource_id=announcement_id,
            details={'title': title, 'status': status},
            ip_address=ip_address,
            user_agent=user_agent
        )
    
    @staticmethod
    def log_announcement_approve(user_id: Optional[int], announcement_id: str, action: str, comment: Optional[str] = None, ip_address: Optional[str] = None, user_agent: Optional[str] = None):
        """记录公告审批操作"""
        AuditLogger.log_action(
            user_id=user_id,
            action='approve_announcement',
            resource_type='announcement',
            resource_id=announcement_id,
            details={'action': action, 'comment': comment},
            ip_address=ip_address,
            user_agent=user_agent
        )
    
    @staticmethod
    def log_announcement_update(user_id: Optional[int], announcement_id: str, title: str, changes: Optional[Dict[str, Any]] = None, ip_address: Optional[str] = None, user_agent: Optional[str] = None):
        """记录公告更新操作"""
        details = {'title': title}
        if changes:
            details['changes'] = changes
        AuditLogger.log_action(
            user_id=user_id,
            action='update_announcement',
            resource_type='announcement',
            resource_id=announcement_id,
            details=details,
            ip_address=ip_address,
            user_agent=user_agent
        )
    
    @staticmethod
    def log_announcement_delete(user_id: Optional[int], announcement_id: str, title: str, soft_delete: bool = False, ip_address: Optional[str] = None, user_agent: Optional[str] = None):
        """记录公告删除操作"""
        AuditLogger.log_action(
            user_id=user_id,
            action='delete_announcement',
            resource_type='announcement',
            resource_id=announcement_id,
            details={'title': title, 'soft_delete': soft_delete},
            ip_address=ip_address,
            user_agent=user_agent
        )
    
    @staticmethod
    def log_todo_create(user_id: Optional[int], announcement_id: str, todo_count: int, success_count: int, failed_count: int, ip_address: Optional[str] = None, user_agent: Optional[str] = None):
        """记录待办任务创建操作"""
        AuditLogger.log_action(
            user_id=user_id,
            action='create_todos',
            resource_type='announcement',
            resource_id=announcement_id,
            details={'todo_count': todo_count, 'success_count': success_count, 'failed_count': failed_count},
            ip_address=ip_address,
            user_agent=user_agent
        )
    
    @staticmethod
    def log_todo_complete(user_id: Optional[int], announcement_id: str, task_id: str, success: bool, ip_address: Optional[str] = None, user_agent: Optional[str] = None):
        """记录待办任务完成操作"""
        AuditLogger.log_action(
            user_id=user_id,
            action='complete_todo',
            resource_type='announcement',
            resource_id=announcement_id,
            details={'task_id': task_id, 'success': success},
            ip_address=ip_address,
            user_agent=user_agent
        )

