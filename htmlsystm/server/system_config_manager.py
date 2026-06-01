#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
系统配置管理器
用于管理系统的各种配置项，包括定时通知开关等
"""
import os
import sys
import json
from typing import Optional, Dict, Any

# 添加项目根目录到Python路径
_current_file_dir = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(_current_file_dir)
sys.path.insert(0, BASE_DIR)

from server.config import USE_MYSQL, MYSQL_CONFIG
from server.logger import logger
from server.mysql_connection_pool import get_mysql_connection_pool


class SystemConfigManager:
    """系统配置管理器"""
    
    def __init__(self):
        self.use_mysql = USE_MYSQL
        self.pool = get_mysql_connection_pool() if self.use_mysql else None
    
    def get_config(self, config_key: str, default_value: str = None) -> Optional[str]:
        """获取配置值
        
        Args:
            config_key: 配置键
            default_value: 默认值（如果配置不存在）
        
        Returns:
            配置值，如果不存在则返回默认值
        """
        try:
            if self.use_mysql and self.pool:
                with self.pool.get_cursor() as cursor:
                    cursor.execute(
                        'SELECT config_value FROM system_config WHERE config_key = %s',
                        (config_key,)
                    )
                    row = cursor.fetchone()
                    if row:
                        if isinstance(row, dict):
                            return row.get('config_value', default_value)
                        else:
                            return row[0] if row else default_value
                    return default_value
            else:
                # 如果未使用MySQL，使用文件存储（降级方案）
                return self._get_config_from_file(config_key, default_value)
        except Exception as e:
            logger.error(f"获取配置失败: {e}", exc_info=True)
            return default_value
    
    def set_config(self, config_key: str, config_value: str, description: str = None) -> bool:
        """设置配置值
        
        Args:
            config_key: 配置键
            config_value: 配置值
            description: 配置描述（可选）
        
        Returns:
            是否设置成功
        """
        try:
            if self.use_mysql and self.pool:
                with self.pool.get_cursor() as cursor:
                    if description:
                        cursor.execute('''
                            INSERT INTO system_config (config_key, config_value, description)
                            VALUES (%s, %s, %s)
                            ON DUPLICATE KEY UPDATE 
                                config_value = VALUES(config_value),
                                description = VALUES(description)
                        ''', (config_key, config_value, description))
                    else:
                        cursor.execute('''
                            INSERT INTO system_config (config_key, config_value)
                            VALUES (%s, %s)
                            ON DUPLICATE KEY UPDATE config_value = VALUES(config_value)
                        ''', (config_key, config_value))
                    cursor.connection.commit()
                    return True
            else:
                # 如果未使用MySQL，使用文件存储（降级方案）
                return self._set_config_to_file(config_key, config_value)
        except Exception as e:
            logger.error(f"设置配置失败: {e}", exc_info=True)
            return False
    
    def get_config_bool(self, config_key: str, default_value: bool = False) -> bool:
        """获取布尔类型配置值
        
        Args:
            config_key: 配置键
            default_value: 默认值
        
        Returns:
            布尔值
        """
        value = self.get_config(config_key, str(default_value).lower())
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ('true', '1', 'yes', 'on', 'enabled')
        return bool(value) if value else default_value
    
    def set_config_bool(self, config_key: str, value: bool, description: str = None) -> bool:
        """设置布尔类型配置值
        
        Args:
            config_key: 配置键
            value: 布尔值
            description: 配置描述（可选）
        
        Returns:
            是否设置成功
        """
        return self.set_config(config_key, 'true' if value else 'false', description)
    
    def _get_config_from_file(self, config_key: str, default_value: str = None) -> Optional[str]:
        """从文件读取配置（降级方案）"""
        try:
            from server.config import DATA_DIR
            config_file = os.path.join(DATA_DIR, 'system_config.json')
            if os.path.exists(config_file):
                with open(config_file, 'r', encoding='utf-8') as f:
                    configs = json.load(f)
                    return configs.get(config_key, default_value)
            return default_value
        except Exception as e:
            logger.warning(f"从文件读取配置失败: {e}")
            return default_value
    
    def _set_config_to_file(self, config_key: str, config_value: str) -> bool:
        """将配置写入文件（降级方案）"""
        try:
            from server.config import DATA_DIR
            os.makedirs(DATA_DIR, exist_ok=True)
            config_file = os.path.join(DATA_DIR, 'system_config.json')
            
            # 读取现有配置
            configs = {}
            if os.path.exists(config_file):
                try:
                    with open(config_file, 'r', encoding='utf-8') as f:
                        configs = json.load(f)
                except:
                    pass
            
            # 更新配置
            configs[config_key] = config_value
            
            # 写入文件
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(configs, f, ensure_ascii=False, indent=2)
            
            return True
        except Exception as e:
            logger.error(f"写入配置到文件失败: {e}")
            return False


# 全局单例
_config_manager = None
_config_lock = __import__('threading').Lock()


def get_config_manager() -> SystemConfigManager:
    """获取配置管理器单例"""
    global _config_manager
    with _config_lock:
        if _config_manager is None:
            _config_manager = SystemConfigManager()
        return _config_manager


# 配置键常量
CONFIG_KEY_SCHEDULED_NOTIFICATIONS_ENABLED = 'scheduled_notifications_enabled'
CONFIG_KEY_SCHEDULED_NOTIFICATIONS_TIMES = 'scheduled_notifications_times'

