#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
会话亲和性管理模块
在资源充裕的情况下，尽量将同一用户的请求路由到同一个worker进程
通过记录会话到worker的映射，优化会话缓存命中率
"""
import os
import time
import threading
import hashlib
import logging
from typing import Optional, Dict
from server.logger import logger

# 会话亲和性配置
ENABLE_SESSION_AFFINITY = True  # 是否启用会话亲和性
AFFINITY_CACHE_TTL = 300  # 亲和性缓存TTL（秒，5分钟）
AFFINITY_CLEANUP_INTERVAL = 600  # 清理过期映射的间隔（秒，10分钟）

class SessionAffinityManager:
    """会话亲和性管理器
    
    记录会话ID到worker进程的映射，帮助优化会话缓存命中率
    注意：这不能强制路由请求，但可以帮助优化缓存策略
    """
    
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
        """初始化会话亲和性管理器"""
        if self._initialized:
            return
        
        # 会话到worker的映射 {session_id: (worker_id, timestamp)}
        self.session_to_worker = {}
        
        # 当前worker的ID（基于进程PID和启动时间）
        self.current_worker_id = self._get_worker_id()
        
        # 清理线程
        self.cleanup_thread = None
        self.stop_cleanup = threading.Event()
        
        # 启动清理线程
        if ENABLE_SESSION_AFFINITY:
            self._start_cleanup_thread()
        
        self._initialized = True
        logger.info(f"会话亲和性管理器已初始化，当前worker_id={self.current_worker_id}")
    
    def _get_worker_id(self) -> str:
        """获取当前worker的ID（基于进程PID）"""
        pid = os.getpid()
        # 使用PID作为worker ID（简单有效）
        return f"worker_{pid}"
    
    def record_session_access(self, session_id: str) -> Optional[str]:
        """记录会话访问，返回建议的worker ID（如果存在）
        
        Args:
            session_id: 会话ID
            
        Returns:
            建议的worker ID（如果之前访问过），否则返回None
        """
        if not ENABLE_SESSION_AFFINITY or not session_id:
            return None
        
        try:
            with self._lock:
                # 检查是否有该会话的映射
                if session_id in self.session_to_worker:
                    worker_id, timestamp = self.session_to_worker[session_id]
                    # 检查映射是否过期
                    if time.time() - timestamp < AFFINITY_CACHE_TTL:
                        # 更新访问时间
                        self.session_to_worker[session_id] = (worker_id, time.time())
                        return worker_id
                    else:
                        # 映射过期，删除
                        del self.session_to_worker[session_id]
                
                # 记录当前worker
                self.session_to_worker[session_id] = (self.current_worker_id, time.time())
                return None
        except Exception as e:
            logger.debug(f"记录会话访问失败: {e}")
            return None
    
    def get_session_worker(self, session_id: str) -> Optional[str]:
        """获取会话对应的worker ID（如果存在）
        
        Args:
            session_id: 会话ID
            
        Returns:
            worker ID（如果存在且未过期），否则返回None
        """
        if not ENABLE_SESSION_AFFINITY or not session_id:
            return None
        
        try:
            with self._lock:
                if session_id in self.session_to_worker:
                    worker_id, timestamp = self.session_to_worker[session_id]
                    if time.time() - timestamp < AFFINITY_CACHE_TTL:
                        return worker_id
                    else:
                        # 过期，删除
                        del self.session_to_worker[session_id]
        except Exception as e:
            logger.debug(f"获取会话worker失败: {e}")
        
        return None
    
    def _start_cleanup_thread(self):
        """启动清理线程，定期清理过期的映射"""
        def cleanup_worker():
            """清理过期的会话映射"""
            while not self.stop_cleanup.is_set():
                try:
                    self.stop_cleanup.wait(AFFINITY_CLEANUP_INTERVAL)
                    if self.stop_cleanup.is_set():
                        break
                    
                    current_time = time.time()
                    with self._lock:
                        expired_sessions = [
                            session_id for session_id, (_, timestamp) in self.session_to_worker.items()
                            if current_time - timestamp >= AFFINITY_CACHE_TTL
                        ]
                        for session_id in expired_sessions:
                            del self.session_to_worker[session_id]
                        
                        if expired_sessions:
                            logger.debug(f"清理了 {len(expired_sessions)} 个过期的会话映射")
                except Exception as e:
                    logger.error(f"清理会话映射失败: {e}", exc_info=True)
        
        if self.cleanup_thread is None or not self.cleanup_thread.is_alive():
            self.cleanup_thread = threading.Thread(target=cleanup_worker, daemon=True, name="SessionAffinityCleanup")
            self.cleanup_thread.start()
            logger.info("已启动会话亲和性清理线程")
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        with self._lock:
            return {
                'current_worker_id': self.current_worker_id,
                'session_count': len(self.session_to_worker),
                'enabled': ENABLE_SESSION_AFFINITY
            }


# 全局实例
_affinity_manager = None
_affinity_lock = threading.Lock()

def get_session_affinity_manager() -> SessionAffinityManager:
    """获取会话亲和性管理器实例"""
    global _affinity_manager
    if _affinity_manager is None:
        with _affinity_lock:
            if _affinity_manager is None:
                _affinity_manager = SessionAffinityManager()
    return _affinity_manager

