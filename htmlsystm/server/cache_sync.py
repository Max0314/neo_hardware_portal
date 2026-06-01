#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
跨进程缓存同步模块
解决Gunicorn多worker环境下的缓存不一致问题
"""
import os
import time
import threading
from typing import Optional
from server.logger import logger
from server.config import DATA_DIR


class CacheSyncManager:
    """跨进程缓存同步管理器
    
    使用文件系统作为跨进程通信机制，确保所有worker进程的缓存保持一致。
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
        """初始化缓存同步管理器"""
        if self._initialized:
            return
        
        # 缓存失效标记文件
        self.marker_dir = DATA_DIR
        os.makedirs(self.marker_dir, exist_ok=True)
        
        # 各种缓存类型的标记文件
        self.markers = {
            'announcements': os.path.join(self.marker_dir, '.cache_invalidation_marker'),
            'todos': os.path.join(self.marker_dir, '.todo_cache_invalidation_marker'),
            'users': os.path.join(self.marker_dir, '.user_cache_invalidation_marker'),
            'departments': os.path.join(self.marker_dir, '.department_cache_invalidation_marker'),
            'materials': os.path.join(self.marker_dir, '.material_cache_invalidation_marker'),
        }
        
        # 进程内缓存版本号（用于快速检查）
        self.local_cache_versions = {}
        self.version_lock = threading.RLock()
        
        # 标记文件监听间隔（秒）
        self.check_interval = 0.5  # 500ms检查一次
        
        self._initialized = True
        logger.debug("缓存同步管理器初始化完成")
    
    def invalidate_cache(self, cache_type: str, immediate: bool = True):
        """使指定类型的缓存失效（通知所有worker进程）
        
        Args:
            cache_type: 缓存类型（'announcements', 'todos', 'users', 'departments', 'materials'）
            immediate: 是否立即更新标记文件（True=立即，False=延迟）
        """
        if cache_type not in self.markers:
            logger.warning(f"未知的缓存类型: {cache_type}")
            return False
        
        try:
            marker_file = self.markers[cache_type]
            
            # 更新标记文件（使用高精度时间戳）
            current_time = time.time()
            
            # 方法1：写入版本号和时间戳（更可靠）
            version_file = marker_file + '.version'
            try:
                with open(version_file, 'w') as f:
                    f.write(f"{int(current_time * 1000000)}\n")  # 微秒级时间戳
            except Exception as e:
                logger.warning(f"写入版本文件失败: {e}")
            
            # 方法2：更新标记文件的修改时间（兼容旧代码）
            try:
                if not os.path.exists(marker_file):
                    with open(marker_file, 'a'):
                        pass
                os.utime(marker_file, (current_time, current_time))
            except Exception as e:
                logger.warning(f"更新标记文件失败: {e}")
            
            # 更新本地版本号（当前进程立即失效）
            with self.version_lock:
                self.local_cache_versions[cache_type] = current_time
            
            logger.info(f"已使缓存失效: {cache_type} (时间戳: {current_time})")
            return True
            
        except Exception as e:
            logger.error(f"使缓存失效失败: cache_type={cache_type}, error={e}", exc_info=True)
            return False
    
    def check_cache_invalidation(self, cache_type: str) -> Optional[float]:
        """检查缓存是否需要失效（返回标记文件的时间戳，如果比本地新则需失效）
        
        Args:
            cache_type: 缓存类型
            
        Returns:
            标记文件的时间戳（如果比本地新），否则返回None
        """
        if cache_type not in self.markers:
            return None
        
        try:
            marker_file = self.markers[cache_type]
            version_file = marker_file + '.version'
            
            # 优先检查版本文件（更精确）
            marker_time = None
            if os.path.exists(version_file):
                try:
                    with open(version_file, 'r') as f:
                        content = f.read().strip()
                        if content:
                            marker_time = int(content) / 1000000.0  # 从微秒转换为秒
                except Exception:
                    pass
            
            # 如果版本文件不存在，使用标记文件的修改时间
            if marker_time is None and os.path.exists(marker_file):
                try:
                    marker_time = os.path.getmtime(marker_file)
                except Exception:
                    pass
            
            if marker_time is None:
                return None
            
            # 检查是否比本地版本新
            with self.version_lock:
                local_version = self.local_cache_versions.get(cache_type, 0)
            
            if marker_time > local_version:
                logger.debug(f"检测到缓存失效标记: {cache_type}, 标记时间={marker_time}, 本地时间={local_version}")
                return marker_time
            
            return None
            
        except Exception as e:
            logger.warning(f"检查缓存失效标记失败: cache_type={cache_type}, error={e}")
            return None
    
    def update_local_version(self, cache_type: str, timestamp: float = None):
        """更新本地缓存版本号（在重新加载缓存后调用）
        
        Args:
            cache_type: 缓存类型
            timestamp: 时间戳（如果为None则使用当前时间）
        """
        if timestamp is None:
            timestamp = time.time()
        
        with self.version_lock:
            self.local_cache_versions[cache_type] = timestamp
        
        logger.debug(f"已更新本地缓存版本: {cache_type} = {timestamp}")


# 全局单例实例
_cache_sync_manager = None
_cache_sync_lock = threading.Lock()


def get_cache_sync_manager() -> CacheSyncManager:
    """获取缓存同步管理器单例"""
    global _cache_sync_manager
    if _cache_sync_manager is None:
        with _cache_sync_lock:
            if _cache_sync_manager is None:
                _cache_sync_manager = CacheSyncManager()
    return _cache_sync_manager


def invalidate_cache(cache_type: str, immediate: bool = True):
    """使缓存失效（便捷函数）"""
    manager = get_cache_sync_manager()
    return manager.invalidate_cache(cache_type, immediate)


def check_cache_invalidation(cache_type: str) -> Optional[float]:
    """检查缓存是否需要失效（便捷函数）"""
    manager = get_cache_sync_manager()
    return manager.check_cache_invalidation(cache_type)


def update_local_version(cache_type: str, timestamp: float = None):
    """更新本地缓存版本号（便捷函数）"""
    manager = get_cache_sync_manager()
    manager.update_local_version(cache_type, timestamp)


def broadcast_cache_invalidation(cache_type: str) -> bool:
    """仅广播跨进程失效标记，不清除本 worker 热缓存。

    写入方在更新本地缓存后调用，通知其他 worker 重新加载。
    """
    return invalidate_cache(cache_type, immediate=True)

