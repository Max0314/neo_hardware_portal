#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gunicorn worker fork 后重置不可 fork 的单例状态。

preload_app=True 时 master 进程会初始化 MySQL 连接池等资源；
fork 后 worker 继承的 socket/锁状态不可用，会导致 HTTP 路径下 DB 查询失败，
而独立 python -c 进程则正常。
"""
from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)


def reset_worker_state(worker_pid: int = 0) -> None:
    """在每个 Gunicorn worker fork 后调用，重建进程内单例。"""
    pid_label = worker_pid or 'unknown'
    logger.info(f"post_fork: 重置 worker {pid_label} 的 fork-unsafe 单例")

    _reset_mysql_pool()
    _reset_wsgi_adapters()
    _reset_worker_init_flags()
    _reset_security_manager()
    _reset_data_preloader()


def _reset_mysql_pool() -> None:
    from server.mysql_connection_pool import MySQLConnectionPool

    MySQLConnectionPool.reset_after_fork()


def reset_mysql_pool_only() -> None:
    """仅重置 MySQL 连接池（登录重试用，不触碰 worker 初始化标志）。"""
    _reset_mysql_pool()


def _reset_wsgi_adapters() -> None:
    from server.wsgi_app import WSGIRequestAdapter

    if hasattr(WSGIRequestAdapter, '_managers'):
        delattr(WSGIRequestAdapter, '_managers')


def _reset_worker_init_flags() -> None:
    import server.wsgi_app as wsgi_module

    wsgi_module._worker_initialized = False
    wsgi_module._worker_ready.clear()
    wsgi_module._init_lock = threading.Lock()


def _reset_security_manager() -> None:
    from server.security_manager import SecurityManager
    import server.security_manager as security_module

    SecurityManager._instance = None
    SecurityManager._lock = threading.Lock()
    security_module._security_manager = None


def _reset_data_preloader() -> None:
    import server.data_preloader as preloader_module

    preloader_module._data_preloader = None
