#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
会话管理模块（支持多进程）
使用MySQL数据库存储会话，解决Gunicorn多进程环境下的会话共享问题
"""
import uuid
import time
import threading
from typing import Optional, Dict, Any

from server.db_adapter import get_connection_pool
from server.logger import logger

# 会话过期时间（秒，默认7天）
SESSION_EXPIRE_TIME = 7 * 24 * 60 * 60


class SessionManager:
    """会话管理器（使用MySQL数据库存储，支持多进程）"""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        """初始化会话管理器"""
        if self._initialized:
            return
        
        self.pool = get_connection_pool()
        self._initialized = True
        self._ensure_session_table()
    
    def _ensure_session_table(self):
        """确保会话表存在（MySQL）"""
        try:
            with self.pool.get_cursor() as cursor:
                # 检查表是否存在
                cursor.execute("SHOW TABLES LIKE 'sessions'")
                table_exists = cursor.fetchone() is not None
                
                if not table_exists:
                    # 表不存在，创建表
                    cursor.execute('''
                        CREATE TABLE IF NOT EXISTS sessions (
                            session_id VARCHAR(255) PRIMARY KEY,
                            user_id INT NOT NULL,
                            user_data TEXT NOT NULL,
                            created_at DOUBLE NOT NULL,
                            expires_at DOUBLE NOT NULL,
                            last_access DOUBLE NOT NULL,
                            INDEX idx_user_id (user_id),
                            INDEX idx_expires_at (expires_at)
                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                    ''')
                    logger.info("已创建sessions表")
        except Exception as e:
            logger.error(f"创建会话表失败: {e}", exc_info=True)
            import traceback
            traceback.print_exc()
    
    def create_session(self, user_data: Dict[str, Any], session_id: Optional[str] = None) -> str:
        """
        创建会话
        
        Args:
            user_data: 用户数据字典
            session_id: 可选的会话ID（如果不提供，则自动生成）
            
        Returns:
            session_id: 会话ID
        """
        if session_id is None:
            session_id = str(uuid.uuid4())
        current_time = time.time()
        expires_at = current_time + SESSION_EXPIRE_TIME
        
        try:
            import json
            user_data_json = json.dumps(user_data, ensure_ascii=False)
            
            # 获取user_id（从user_data中提取）
            user_id = user_data.get('id', 0)
            
            with self.pool.get_cursor() as cursor:
                cursor.execute('''
                    INSERT INTO sessions (session_id, user_id, user_data, created_at, expires_at, last_access)
                    VALUES (%s, %s, %s, %s, %s, %s)
                ''', (session_id, user_id, user_data_json, current_time, expires_at, current_time))
            
            return session_id
        except Exception as e:
            logger.error(f"创建会话失败: {e}", exc_info=True)
            raise
    
    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        获取会话数据
        
        Args:
            session_id: 会话ID
            
        Returns:
            用户数据字典，如果会话不存在或已过期则返回None
        """
        if not session_id:
            return None
        
        try:
            import json
            current_time = time.time()
            
            with self.pool.get_cursor() as cursor:
                cursor.execute('''
                    SELECT user_data, expires_at FROM sessions
                    WHERE session_id = %s AND expires_at > %s
                ''', (session_id, current_time))
                
                row = cursor.fetchone()
                if row:
                    # 处理字典格式的返回
                    if isinstance(row, dict):
                        user_data_str = row.get('user_data', '')
                    else:
                        user_data_str = row[0] if row else ''
                    
                    # 更新最后访问时间（异步更新，不阻塞）
                    try:
                        cursor.execute('''
                            UPDATE sessions SET last_access = %s
                            WHERE session_id = %s
                        ''', (current_time, session_id))
                    except:
                        pass  # 更新失败不影响读取
                    
                    if user_data_str:
                        user_data = json.loads(user_data_str)
                        return user_data
                    return None
                else:
                    # 会话不存在或已过期，清理
                    try:
                        self.delete_session(session_id)
                    except:
                        pass  # 清理失败不影响返回
                    return None
        except Exception as e:
            logger.error(f"获取会话失败: {e}", exc_info=True)
            return None
    
    def delete_session(self, session_id: str):
        """删除会话"""
        if not session_id:
            return
        
        try:
            with self.pool.get_cursor() as cursor:
                cursor.execute('DELETE FROM sessions WHERE session_id = %s', (session_id,))
        except Exception as e:
            logger.error(f"删除会话失败: {e}", exc_info=True)

    def delete_all_sessions_for_user_batched(self, user_id: int, batch_size: int = 200) -> int:
        """分批删除用户全部会话，避免单条 DELETE 锁表。"""
        if not user_id:
            return 0
        total_removed = 0
        batch_size = max(50, min(int(batch_size or 200), 1000))
        try:
            while True:
                with self.pool.get_cursor() as cursor:
                    cursor.execute(
                        'DELETE FROM sessions WHERE user_id = %s LIMIT %s',
                        (int(user_id), batch_size),
                    )
                    removed = int(cursor.rowcount or 0)
                total_removed += removed
                if removed < batch_size:
                    break
            if total_removed > batch_size:
                logger.info(
                    '分批删除用户会话: user_id=%s, removed=%s',
                    user_id,
                    total_removed,
                )
            return total_removed
        except Exception as e:
            logger.error(f'分批删除用户会话失败 user_id={user_id}: {e}', exc_info=True)
            return total_removed

    def delete_sessions_for_user(self, user_id: int) -> int:
        """删除指定用户的全部会话（改密/权限变更后强制重登）。"""
        return self.delete_all_sessions_for_user_batched(user_id)

    def delete_other_sessions_for_user(
        self,
        user_id: int,
        keep_session_id: str,
        *,
        batch_size: int = 200,
    ) -> int:
        """登录成功后删除该用户其它会话（分批 DELETE，避免单条语句锁表拖垮全站）。"""
        if not user_id or not keep_session_id:
            return 0
        total_removed = 0
        batch_size = max(50, min(int(batch_size or 200), 1000))
        try:
            while True:
                with self.pool.get_cursor() as cursor:
                    cursor.execute(
                        'DELETE FROM sessions WHERE user_id = %s AND session_id != %s LIMIT %s',
                        (int(user_id), keep_session_id, batch_size),
                    )
                    removed = int(cursor.rowcount or 0)
                total_removed += removed
                if removed < batch_size:
                    break
            if total_removed > batch_size:
                logger.info(
                    "分批清理用户旧会话: user_id=%s, removed=%s, keep=%s...",
                    user_id,
                    total_removed,
                    keep_session_id[:8],
                )
            return total_removed
        except Exception as e:
            logger.warning(
                f"清理用户旧会话失败 user_id={user_id}, session={keep_session_id[:8]}...: {e}"
            )
            return total_removed
    
    def update_session(self, session_id: str, user_data: Dict[str, Any]):
        """更新会话数据"""
        if not session_id:
            return
        
        try:
            import json
            user_data_json = json.dumps(user_data, ensure_ascii=False)
            current_time = time.time()
            expires_at = current_time + SESSION_EXPIRE_TIME
            
            user_id = user_data.get('id', 0)
            
            with self.pool.get_cursor() as cursor:
                cursor.execute('''
                    UPDATE sessions 
                    SET user_id = %s, user_data = %s, expires_at = %s, last_access = %s
                    WHERE session_id = %s
                ''', (user_id, user_data_json, expires_at, current_time, session_id))
        except Exception as e:
            logger.error(f"更新会话失败: {e}", exc_info=True)
    
    def cleanup_expired_sessions(self):
        """清理过期会话"""
        try:
            current_time = time.time()
            with self.pool.get_cursor() as cursor:
                cursor.execute('DELETE FROM sessions WHERE expires_at < %s', (current_time,))
        except Exception as e:
            logger.error(f"清理过期会话失败: {e}", exc_info=True)


# 全局会话管理器实例
_session_manager = None
_session_manager_lock = threading.Lock()

def get_session_manager() -> SessionManager:
    """获取会话管理器实例"""
    global _session_manager
    if _session_manager is None:
        with _session_manager_lock:
            if _session_manager is None:
                _session_manager = SessionManager()
    return _session_manager


def sync_session_patch(
    session_id: str,
    patch: Dict[str, Any],
    memory_sessions: Optional[Dict[str, Any]] = None,
    memory_lock: Optional[threading.Lock] = None,
) -> bool:
    """合并 patch 到会话并同步 MySQL 与进程内内存。"""
    if not session_id or not patch:
        return False

    user_data: Optional[Dict[str, Any]] = None
    if memory_sessions is not None and memory_lock is not None:
        with memory_lock:
            if session_id in memory_sessions:
                user_data = dict(memory_sessions[session_id])

    if user_data is None:
        try:
            user_data = get_session_manager().get_session(session_id)
            if user_data:
                user_data = dict(user_data)
        except Exception as e:
            logger.warning(f"读取会话失败: session_id={session_id[:8]}..., error={e}")
            return False

    if not user_data:
        return False

    user_data.update(patch)
    try:
        get_session_manager().update_session(session_id, user_data)
    except Exception as e:
        logger.error(f"持久化会话更新失败: {e}", exc_info=True)
        return False

    if memory_sessions is not None and memory_lock is not None:
        with memory_lock:
            if session_id in memory_sessions:
                memory_sessions[session_id].update(patch)
            else:
                memory_sessions[session_id] = user_data
    return True
