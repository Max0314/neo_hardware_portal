#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库管理模块
已完全迁移到MySQL，不再支持SQLite
"""
import os
import threading
from contextlib import contextmanager
from typing import List, Dict, Any, Optional

from server.db_adapter import get_connection_pool
from server.logger import logger


class Database:
    """数据库管理类，提供线程安全的MySQL数据库操作"""
    
    _lock = threading.Lock()  # 线程锁，保护数据库操作
    
    def __init__(self):
        """初始化数据库连接"""
        self.pool = get_connection_pool()
        self._initialized = True
    
    def init_database(self):
        """初始化数据库表结构（MySQL模式由mysql_schema管理）"""
        # MySQL表结构由mysql_schema模块统一管理，这里不需要初始化
        pass
    
    @contextmanager
    def get_cursor(self):
        """获取数据库游标的上下文管理器，自动处理事务"""
        with self.pool.get_cursor() as cursor:
                yield cursor
    
    def execute_query(self, query: str, params: tuple = ()):
        """
        执行查询语句（线程安全）
        
        Args:
            query: SQL查询语句（使用%s占位符）
            params: 查询参数
            
        Returns:
            游标对象
        """
        try:
            with self.pool.get_cursor() as cursor:
                cursor.execute(query, params)
                return cursor
        except Exception as e:
            logger.error(f"执行查询失败: {e}\n查询语句: {query}\n参数: {params}", exc_info=True)
            raise
    
    def execute_many(self, query: str, params_list: List[tuple]) -> None:
        """
        批量执行查询（线程安全）
        
        Args:
            query: SQL查询语句（使用%s占位符）
            params_list: 参数列表
        """
        try:
            with self.pool.get_cursor() as cursor:
                cursor.executemany(query, params_list)
        except Exception as e:
            logger.error(f"批量执行查询失败: {e}", exc_info=True)
            raise
    
    def commit(self):
        """提交事务（MySQL连接池自动管理）"""
        # MySQL连接池自动管理事务，这里不需要手动提交
        pass
    
    def rollback(self):
        """回滚事务（MySQL连接池自动管理）"""
        # MySQL连接池自动管理事务，这里不需要手动回滚
        pass
    
    def close(self):
        """关闭数据库连接（MySQL连接池自动管理）"""
        # MySQL连接池自动管理连接，这里不需要手动关闭
        pass
    
    def get_all_users(self) -> List[Dict[str, Any]]:
        """
        获取所有用户
        
        Returns:
            用户列表
        """
        try:
            with self.pool.get_cursor() as cursor:
                cursor.execute('SELECT * FROM users ORDER BY created_time DESC')
                rows = cursor.fetchall()
            users = []
            for row in rows:
                if isinstance(row, dict):
                    users.append(row)
                else:
                    # 如果是tuple，转换为字典
                    columns = [desc[0] for desc in cursor.description] if hasattr(cursor, 'description') else []
                    users.append(dict(zip(columns, row)) if columns else {})
            return users
        except Exception as e:
            logger.error(f"获取用户列表失败: {e}", exc_info=True)
            return []
    
    def __enter__(self):
        """上下文管理器入口"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        return False
