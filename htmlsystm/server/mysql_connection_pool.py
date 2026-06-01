#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MySQL连接池管理（支持多进程）
替代SQLite连接池，提供更好的并发性能
"""
import threading
from contextlib import contextmanager
from typing import Optional
import os

try:
    import pymysql
    HAS_PYMYSQL = True
except ImportError:
    HAS_PYMYSQL = False
    try:
        import mysql.connector
        from mysql.connector import pooling
        HAS_MYSQL_CONNECTOR = True
    except ImportError:
        HAS_MYSQL_CONNECTOR = False


class MySQLConnectionPool:
    """
    MySQL连接池（每个进程一个连接池，线程安全）
    在Gunicorn多进程环境下，每个worker进程有独立的连接池
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        """单例模式（每个进程一个实例）"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        """初始化连接池"""
        if self._initialized:
            return
        
        # 检查是否有MySQL驱动
        if not HAS_PYMYSQL and not HAS_MYSQL_CONNECTOR:
            raise ImportError("未安装MySQL驱动，请运行: pip install pymysql 或 pip install mysql-connector-python")
        
        # 获取MySQL配置（从环境变量重新读取，确保获取最新值）
        # 注意：直接从环境变量读取，而不是从MYSQL_CONFIG读取，因为MYSQL_CONFIG可能在导入时就已经缓存了
        self.config = {
            'host': os.getenv('MYSQL_HOST', 'localhost'),
            'port': int(os.getenv('MYSQL_PORT', 3306)),
            'user': os.getenv('MYSQL_USER', 'htmlsystm_user'),
            'password': os.getenv('MYSQL_PASSWORD', ''),
            'database': os.getenv('MYSQL_DATABASE', 'htmlsystm'),
            'charset': 'utf8mb4',
            'autocommit': False,
            'pool_size': 10,
            'pool_reset_session': True,
            'pool_recycle': 3600,
        }
        
        # 如果环境变量中没有密码，尝试从MYSQL_CONFIG读取（向后兼容）
        if not self.config.get('password'):
            from server.config import MYSQL_CONFIG
            if MYSQL_CONFIG.get('password'):
                self.config['password'] = MYSQL_CONFIG['password']
        
        # 检查MySQL密码是否设置
        if not self.config.get('password'):
            error_msg = (
                "❌ MySQL密码未设置！\n"
                "请设置 MYSQL_PASSWORD 环境变量:\n"
                "  export MYSQL_PASSWORD='your_password'\n"
                "请检查根目录 .env 中 MYSQL_* 配置，并参考 运维手册.md 第 8 章\n"
                "或运行: bash migration/fix-mysql-and-admin.sh"
            )
            raise ValueError(error_msg)
        
        self.use_pymysql = HAS_PYMYSQL
        
        # 初始化连接池
        self._init_pool()
        self._initialized = True
        
        # 确保数据库模式存在
        self._ensure_schema()
    
    def _init_pool(self):
        """初始化连接池"""
        if self.use_pymysql:
            # 使用pymysql（纯Python实现）
            self.pool_config = {
                'host': self.config['host'],
                'port': self.config['port'],
                'user': self.config['user'],
                'password': self.config['password'],
                'database': self.config['database'],
                'charset': self.config.get('charset', 'utf8mb4'),
                'autocommit': False,
                'cursorclass': pymysql.cursors.DictCursor,  # 返回字典格式
                'connect_timeout': 5,
                'read_timeout': 10,
                'write_timeout': 10,
            }
            # gthread 多线程下 pymysql 连接不可共享；每线程持有一条连接
            self._thread_local = threading.local()
            self._connect_lock = threading.Lock()
            self._max_connections = self.config.get('pool_size', 10)
        else:
            # 使用mysql-connector-python（官方驱动，有连接池）
            pool_size = self.config.pop('pool_size', 10)
            pool_reset_session = self.config.pop('pool_reset_session', True)
            pool_recycle = self.config.pop('pool_recycle', 3600)
            
            self.pool = pooling.MySQLConnectionPool(
                pool_name="htmlsystm_pool",
                pool_size=pool_size,
                pool_reset_session=pool_reset_session,
                pool_recycle=pool_recycle,
                **self.config
            )
    
    def _get_connection_pymysql(self):
        """使用pymysql获取连接（每线程一条，gthread 安全）"""
        if not hasattr(self, '_thread_local'):
            self._thread_local = threading.local()
            self._connect_lock = threading.Lock()

        conn = getattr(self._thread_local, 'connection', None)
        if conn is not None:
            try:
                conn.ping(reconnect=True)
                return conn
            except Exception:
                try:
                    conn.close()
                except Exception:
                    pass
                self._thread_local.connection = None

        with self._connect_lock:
            conn = getattr(self._thread_local, 'connection', None)
            if conn is not None:
                try:
                    conn.ping(reconnect=True)
                    return conn
                except Exception:
                    try:
                        conn.close()
                    except Exception:
                        pass
            conn = pymysql.connect(**self.pool_config)
            self._thread_local.connection = conn
            return conn

    def _return_connection_pymysql(self, conn):
        """归还连接（保留在线程本地，不放入共享池）"""
        pass
    
    @contextmanager
    def get_connection(self):
        """
        获取数据库连接（上下文管理器，线程安全）
        
        使用示例:
            with pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM users")
                results = cursor.fetchall()
                conn.commit()
        """
        if self.use_pymysql:
            conn = self._get_connection_pymysql()
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                self._return_connection_pymysql(conn)
        else:
            # mysql-connector-python
            conn = self.pool.get_connection()
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
    
    @contextmanager
    def get_cursor(self):
        """
        获取数据库游标（上下文管理器，自动提交/回滚）
        
        使用示例:
            with pool.get_cursor() as cursor:
                cursor.execute("SELECT * FROM users")
                results = cursor.fetchall()
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                yield cursor
            finally:
                cursor.close()
    
    def execute_query(self, query: str, params: tuple = ()):
        """执行查询（线程安全）"""
        with self.get_cursor() as cursor:
            cursor.execute(query, params)
            return cursor.fetchall()
    
    def execute_update(self, query: str, params: tuple = ()):
        """执行更新（线程安全）"""
        with self.get_cursor() as cursor:
            cursor.execute(query, params)
            return cursor.rowcount
    
    def _ensure_schema(self):
        """确保数据库模式存在（新库全量初始化；已有库补建 NEO 等增量表）。"""
        try:
            from server.mysql_schema import initialize_mysql_schema, ensure_incremental_schema

            with self.get_cursor() as cursor:
                cursor.execute("SHOW TABLES LIKE 'users'")
                if not cursor.fetchone():
                    initialize_mysql_schema(self)
                else:
                    ensure_incremental_schema(self)
        except ImportError:
            pass
        except Exception as e:
            print(f"数据库模式检查失败: {e}")
    
    def close(self):
        """关闭当前线程持有的连接"""
        if self.use_pymysql:
            conn = getattr(getattr(self, '_thread_local', None), 'connection', None)
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
                self._thread_local.connection = None

    @classmethod
    def reset_after_fork(cls) -> None:
        """fork/post_fork 后重建单例与锁，避免继承失效的 threading.Lock / socket"""
        import server.mysql_connection_pool as mysql_module

        instance = cls._instance
        if instance is not None:
            try:
                instance.close()
            except Exception:
                pass

        cls._instance = None
        cls._lock = threading.Lock()
        mysql_module._mysql_connection_pool = None
        mysql_module._mysql_pool_lock = threading.Lock()


# 全局连接池实例（每个进程一个）
_mysql_connection_pool = None
_mysql_pool_lock = threading.Lock()

def get_mysql_connection_pool() -> MySQLConnectionPool:
    """获取MySQL连接池实例（每个进程一个）"""
    global _mysql_connection_pool
    if _mysql_connection_pool is None:
        with _mysql_pool_lock:
            if _mysql_connection_pool is None:
                _mysql_connection_pool = MySQLConnectionPool()
    return _mysql_connection_pool

