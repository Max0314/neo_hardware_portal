#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库适配器
已完全迁移到MySQL，不再支持SQLite
"""
from server.mysql_connection_pool import get_mysql_connection_pool, MySQLConnectionPool

# 直接使用MySQL连接池
ConnectionPool = MySQLConnectionPool
get_connection_pool = get_mysql_connection_pool

# 导出统一接口
__all__ = ['get_connection_pool', 'ConnectionPool']

