#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日志模块
提供统一的日志记录功能
优化：减少控制台输出，只输出关键信息，所有日志记录到文件
"""
import logging
import os
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler

# 日志级别配置
# 控制台日志级别（只输出WARNING及以上，减少输出）
CONSOLE_LOG_LEVEL = os.getenv('CONSOLE_LOG_LEVEL', 'WARNING').upper()
# 文件日志级别（记录所有DEBUG及以上）
FILE_LOG_LEVEL = os.getenv('FILE_LOG_LEVEL', 'DEBUG').upper()
# 全局日志级别
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()

# 是否启用详细日志（DEBUG模式）
ENABLE_VERBOSE_LOGS = os.getenv('ENABLE_VERBOSE_LOGS', '').lower() in ('1', 'true', 'yes')

# 日志目录
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

# 日志文件路径
LOG_FILE = os.path.join(LOG_DIR, 'server.log')
ERROR_LOG_FILE = os.path.join(LOG_DIR, 'error.log')
ACCESS_LOG_FILE = os.path.join(LOG_DIR, 'access.log')  # 访问日志

# 配置日志格式
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
DATE_FORMAT = '%Y-%m-%d %H:%M:%S'
ACCESS_LOG_FORMAT = '%(asctime)s - %(message)s'  # 访问日志格式（简化）

def setup_logger(name='hardware_rdb', log_level=LOG_LEVEL):
    """
    设置日志记录器
    
    优化策略：
    - 控制台：只输出WARNING及以上级别（减少输出，降低服务器压力）
    - 文件：记录所有DEBUG及以上级别（完整记录）
    - 错误日志：单独记录ERROR及以上级别
    - 访问日志：单独记录访问请求（可选）
    
    Args:
        name: 日志记录器名称
        log_level: 日志级别
        
    Returns:
        配置好的日志记录器
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, log_level, logging.INFO))
    
    # 避免重复添加处理器
    if logger.handlers:
        return logger
    
    # 控制台处理器（只输出WARNING及以上，减少输出）
    console_handler = logging.StreamHandler(sys.stdout)
    console_level = logging.DEBUG if ENABLE_VERBOSE_LOGS else getattr(logging, CONSOLE_LOG_LEVEL, logging.WARNING)
    console_handler.setLevel(console_level)
    console_formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)
    
    # 文件处理器（所有日志，完整记录）
    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=50*1024*1024,  # 50MB（增大以支持更多日志）
        backupCount=10,  # 保留10个备份文件
        encoding='utf-8'
    )
    file_level = getattr(logging, FILE_LOG_LEVEL, logging.DEBUG)
    file_handler.setLevel(file_level)
    file_formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)
    
    # 错误日志文件处理器（只记录ERROR及以上）
    error_handler = RotatingFileHandler(
        ERROR_LOG_FILE,
        maxBytes=50*1024*1024,  # 50MB
        backupCount=10,
        encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)
    error_formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)
    error_handler.setFormatter(error_formatter)
    logger.addHandler(error_handler)
    
    return logger

# 创建默认日志记录器
logger = setup_logger()

# 创建访问日志记录器（用于记录HTTP请求）
access_logger = logging.getLogger('hardware_rdb.access')
access_logger.setLevel(logging.INFO)
if not access_logger.handlers:
    access_file_handler = RotatingFileHandler(
        ACCESS_LOG_FILE,
        maxBytes=50*1024*1024,  # 50MB
        backupCount=10,
        encoding='utf-8'
    )
    access_file_handler.setLevel(logging.INFO)
    access_formatter = logging.Formatter(ACCESS_LOG_FORMAT, DATE_FORMAT)
    access_file_handler.setFormatter(access_formatter)
    access_logger.addHandler(access_file_handler)
    access_logger.propagate = False  # 不传播到父logger

