#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
安全管理器
提供IP黑名单、登录失败记录、暴力破解检测等功能
"""
import time
import threading
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
from datetime import datetime, timedelta
from server.logger import logger
from server.db_adapter import get_connection_pool


class SecurityManager:
    """安全管理器 - 单例模式"""
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._initialized = True
        # 登录失败记录：{ip: [(timestamp, username), ...]}
        self._failed_attempts: Dict[str, List[Tuple[float, str]]] = defaultdict(list)
        # IP黑名单：{ip: (block_until_timestamp, reason)}
        self._ip_blacklist: Dict[str, Tuple[float, str]] = {}
        # 清理线程锁
        self._cleanup_lock = threading.Lock()
        # 配置参数
        self.MAX_FAILED_ATTEMPTS = 5  # 最大失败次数
        self.BLOCK_DURATION = 12 * 3600  # 黑名单持续时间（秒，默认12小时）
        self.ATTEMPT_WINDOW = 3600  # 失败尝试时间窗口（秒，1小时内）
        self.CLEANUP_INTERVAL = 3600  # 清理间隔（秒）
        
        # 启动清理线程
        self._start_cleanup_thread()
    
    def _start_cleanup_thread(self):
        """启动清理线程，定期清理过期记录"""
        def cleanup():
            while True:
                try:
                    time.sleep(self.CLEANUP_INTERVAL)
                    self._cleanup_expired_records()
                except Exception as e:
                    logger.error(f"清理过期安全记录失败: {e}", exc_info=True)
        
        thread = threading.Thread(target=cleanup, daemon=True)
        thread.start()
        logger.info("安全管理器清理线程已启动")
    
    def _cleanup_expired_records(self):
        """清理过期的失败记录和黑名单"""
        current_time = time.time()
        
        with self._cleanup_lock:
            # 清理过期的失败记录
            for ip in list(self._failed_attempts.keys()):
                attempts = self._failed_attempts[ip]
                # 只保留时间窗口内的记录
                self._failed_attempts[ip] = [
                    (ts, username) for ts, username in attempts
                    if current_time - ts < self.ATTEMPT_WINDOW
                ]
                # 如果没有有效记录，删除该IP
                if not self._failed_attempts[ip]:
                    del self._failed_attempts[ip]
            
            # 清理过期的黑名单
            for ip in list(self._ip_blacklist.keys()):
                block_until, _ = self._ip_blacklist[ip]
                if current_time > block_until:
                    del self._ip_blacklist[ip]
                    logger.info(f"IP {ip} 已从黑名单中移除（过期）")
    
    def _table_exists(self, table_name: str) -> bool:
        try:
            pool = get_connection_pool()
            with pool.get_cursor() as cursor:
                cursor.execute('''
                    SELECT COUNT(*) as count
                    FROM information_schema.tables
                    WHERE table_schema = DATABASE()
                    AND table_name = %s
                ''', (table_name,))
                row = cursor.fetchone()
                if isinstance(row, dict):
                    return int(row.get('count', 0)) > 0
                return bool(row and int(row[0]) > 0)
        except Exception:
            return False

    def _save_login_attempt_db(self, ip: str, username: str, success: bool) -> None:
        if not self._table_exists('login_attempts'):
            return

        def _write():
            try:
                pool = get_connection_pool()
                with pool.get_cursor() as cursor:
                    cursor.execute(
                        'INSERT INTO login_attempts (ip_address, username, success) VALUES (%s, %s, %s)',
                        (ip, username or None, 1 if success else 0),
                    )
            except Exception as e:
                logger.warning(f"保存登录尝试记录失败: {e}")

        try:
            threading.Thread(target=_write, daemon=True, name='login-attempt-db').start()
        except Exception as e:
            logger.warning(f"异步保存登录尝试记录失败: {e}")

    def _count_failed_attempts_db(self, ip: str) -> Optional[int]:
        if not self._table_exists('login_attempts'):
            return None
        try:
            since = datetime.now() - timedelta(seconds=self.ATTEMPT_WINDOW)
            pool = get_connection_pool()
            with pool.get_cursor() as cursor:
                cursor.execute(
                    '''
                    SELECT COUNT(*) AS c FROM login_attempts
                    WHERE ip_address = %s AND success = 0 AND created_time >= %s
                    ''',
                    (ip, since),
                )
                row = cursor.fetchone()
                if isinstance(row, dict):
                    return int(row.get('c', 0))
                return int(row[0]) if row else 0
        except Exception as e:
            logger.warning(f"查询登录失败次数失败: {e}")
            return None

    def record_failed_login(self, ip: str, username: str = "") -> Tuple[bool, Optional[str]]:
        """
        记录登录失败
        
        Args:
            ip: IP地址
            username: 用户名（可选）
            
        Returns:
            (是否应该阻止, 阻止原因)
        """
        current_time = time.time()
        # DB 审计异步，不阻塞登录热路径
        self._save_login_attempt_db(ip, username, success=False)

        with self._cleanup_lock:
            self._failed_attempts[ip].append((current_time, username))
            attempts = [
                (ts, u) for ts, u in self._failed_attempts[ip]
                if current_time - ts < self.ATTEMPT_WINDOW
            ]
            self._failed_attempts[ip] = attempts
            attempt_count = len(attempts)

        logger.debug(f"记录登录失败: IP={ip}, 用户名={username}, 失败次数={attempt_count}")

        if attempt_count >= self.MAX_FAILED_ATTEMPTS:
            block_until = current_time + self.BLOCK_DURATION
            with self._cleanup_lock:
                self._ip_blacklist[ip] = (block_until, "暴力破解检测")
            logger.warning(
                f"IP {ip} 因多次登录失败被加入黑名单，解封时间: "
                f"{datetime.fromtimestamp(block_until).strftime('%Y-%m-%d %H:%M:%S')}"
            )
            try:
                threading.Thread(
                    target=self._save_blacklist_to_db,
                    args=(ip, block_until, "暴力破解检测"),
                    daemon=True,
                ).start()
            except Exception:
                self._save_blacklist_to_db(ip, block_until, "暴力破解检测")
            return True, f"IP已被封禁，解封时间: {datetime.fromtimestamp(block_until).strftime('%Y-%m-%d %H:%M:%S')}"

        remaining = self.MAX_FAILED_ATTEMPTS - attempt_count
        if remaining <= 2:
            return False, f"登录失败次数过多，剩余尝试次数: {remaining}"

        return False, None

    def record_failed_login_async(self, ip: str, username: str = "") -> None:
        """后台记录失败，避免 login_attempts 表锁阻塞登录响应。"""
        try:
            threading.Thread(
                target=self.record_failed_login,
                args=(ip, username),
                daemon=True,
                name='record-failed-login',
            ).start()
        except Exception as e:
            logger.warning(f"异步记录登录失败跳过: {e}")
    
    def record_successful_login(self, ip: str):
        """记录成功登录，清除该IP的失败记录"""
        self._save_login_attempt_db(ip, "", success=True)
        with self._cleanup_lock:
            if ip in self._failed_attempts:
                del self._failed_attempts[ip]
                logger.debug(f"IP {ip} 登录成功，已清除失败记录")
    
    def is_ip_blocked(self, ip: str) -> Tuple[bool, Optional[str]]:
        """
        检查IP是否被阻止
        
        Args:
            ip: IP地址
            
        Returns:
            (是否被阻止, 阻止原因)
        """
        current_time = time.time()
        
        with self._cleanup_lock:
            if ip in self._ip_blacklist:
                block_until, reason = self._ip_blacklist[ip]
                if current_time < block_until:
                    return True, f"IP已被封禁，解封时间: {datetime.fromtimestamp(block_until).strftime('%Y-%m-%d %H:%M:%S')}"
                else:
                    # 已过期，移除
                    del self._ip_blacklist[ip]
                    return False, None
            
            # 从数据库加载黑名单
            db_blocked = self._load_blacklist_from_db(ip)
            if db_blocked:
                block_until, reason = db_blocked
                if current_time < block_until:
                    self._ip_blacklist[ip] = (block_until, reason)
                    return True, f"IP已被封禁，解封时间: {datetime.fromtimestamp(block_until).strftime('%Y-%m-%d %H:%M:%S')}"
                else:
                    # 已过期，从数据库删除
                    self._remove_blacklist_from_db(ip)
        
        return False, None
    
    def get_failed_attempts_count(self, ip: str) -> int:
        """获取IP的失败尝试次数（登录热路径仅用内存计数）。"""
        current_time = time.time()
        with self._cleanup_lock:
            if ip not in self._failed_attempts:
                return 0
            attempts = self._failed_attempts[ip]
            valid_attempts = [
                (ts, u) for ts, u in attempts
                if current_time - ts < self.ATTEMPT_WINDOW
            ]
            self._failed_attempts[ip] = valid_attempts
            return len(valid_attempts)
    
    def requires_captcha(self, ip: str) -> bool:
        """检查是否需要显示验证码（失败2次以上）。"""
        count = self.get_failed_attempts_count(ip)
        result = count >= 2
        logger.debug(f"检查验证码需求: IP={ip}, 失败次数={count}, 需要验证码={result}")
        return result
    
    def add_to_blacklist(self, ip: str, duration: Optional[float] = None, reason: str = "手动添加"):
        """
        手动将IP添加到黑名单
        
        Args:
            ip: IP地址
            duration: 封禁时长（秒），默认使用配置的时长
            reason: 封禁原因
        """
        current_time = time.time()
        block_until = current_time + (duration or self.BLOCK_DURATION)
        
        with self._cleanup_lock:
            self._ip_blacklist[ip] = (block_until, reason)
            logger.info(f"IP {ip} 已手动添加到黑名单，原因: {reason}，解封时间: {datetime.fromtimestamp(block_until).strftime('%Y-%m-%d %H:%M:%S')}")
        
        # 保存到数据库
        self._save_blacklist_to_db(ip, block_until, reason)
    
    def remove_from_blacklist(self, ip: str):
        """从黑名单中移除IP"""
        with self._cleanup_lock:
            if ip in self._ip_blacklist:
                del self._ip_blacklist[ip]
                logger.info(f"IP {ip} 已从黑名单中移除")
        
        # 从数据库删除
        self._remove_blacklist_from_db(ip)

    def clear_all_restrictions(self):
        """清除所有登录限制（内存 + 数据库），用于解除误封禁"""
        with self._cleanup_lock:
            self._failed_attempts.clear()
            self._ip_blacklist.clear()
        try:
            pool = get_connection_pool()
            with pool.get_cursor() as cursor:
                for table in ('login_attempts', 'ip_blacklist'):
                    try:
                        cursor.execute(f'DELETE FROM {table}')
                    except Exception as e:
                        logger.debug(f"清除 {table} 跳过: {e}")
            logger.info("已清除全部登录限制（内存与数据库）")
        except Exception as e:
            logger.warning(f"清除数据库登录限制失败: {e}")
    
    def _save_blacklist_to_db(self, ip: str, block_until: float, reason: str):
        """保存黑名单到数据库"""
        try:
            pool = get_connection_pool()
            with pool.get_cursor() as cursor:
                # 检查表是否存在，如果不存在则跳过
                cursor.execute('''
                    SELECT COUNT(*) as count 
                    FROM information_schema.tables 
                    WHERE table_schema = DATABASE() 
                    AND table_name = 'ip_blacklist'
                ''')
                table_exists = cursor.fetchone()
                if not table_exists or (isinstance(table_exists, dict) and table_exists.get('count', 0) == 0) or (isinstance(table_exists, tuple) and table_exists[0] == 0):
                    logger.debug("ip_blacklist表不存在，跳过数据库保存（黑名单仅在内存中）")
                    return
                
                # 检查是否已存在
                cursor.execute('SELECT id FROM ip_blacklist WHERE ip_address = %s', (ip,))
                existing = cursor.fetchone()
                
                if existing:
                    # 更新
                    cursor.execute('''
                        UPDATE ip_blacklist 
                        SET block_until = FROM_UNIXTIME(%s), reason = %s, updated_time = NOW()
                        WHERE ip_address = %s
                    ''', (block_until, reason, ip))
                else:
                    # 插入
                    cursor.execute('''
                        INSERT INTO ip_blacklist (ip_address, block_until, reason, created_time, updated_time)
                        VALUES (%s, FROM_UNIXTIME(%s), %s, NOW(), NOW())
                    ''', (ip, block_until, reason))
        except Exception as e:
            logger.error(f"保存黑名单到数据库失败: {e}", exc_info=True)
    
    def _load_blacklist_from_db(self, ip: str) -> Optional[Tuple[float, str]]:
        """从数据库加载黑名单"""
        try:
            pool = get_connection_pool()
            with pool.get_cursor() as cursor:
                # 检查表是否存在，如果不存在则跳过
                cursor.execute('''
                    SELECT COUNT(*) as count 
                    FROM information_schema.tables 
                    WHERE table_schema = DATABASE() 
                    AND table_name = 'ip_blacklist'
                ''')
                table_exists = cursor.fetchone()
                if not table_exists or (isinstance(table_exists, dict) and table_exists.get('count', 0) == 0) or (isinstance(table_exists, tuple) and table_exists[0] == 0):
                    logger.debug("ip_blacklist表不存在，跳过数据库查询")
                    return None
                
                cursor.execute('''
                    SELECT block_until, reason 
                    FROM ip_blacklist 
                    WHERE ip_address = %s AND block_until > NOW()
                ''', (ip,))
                row = cursor.fetchone()
                
                if row:
                    if isinstance(row, dict):
                        block_until = row['block_until']
                        reason = row['reason']
                    else:
                        block_until = row[0]
                        reason = row[1]
                    
                    # 转换为时间戳
                    if isinstance(block_until, datetime):
                        block_until_ts = block_until.timestamp()
                    else:
                        block_until_ts = time.mktime(block_until.timetuple())
                    
                    return (block_until_ts, reason)
        except Exception as e:
            logger.error(f"从数据库加载黑名单失败: {e}", exc_info=True)
        
        return None
    
    def _remove_blacklist_from_db(self, ip: str):
        """从数据库删除黑名单"""
        try:
            pool = get_connection_pool()
            with pool.get_cursor() as cursor:
                # 检查表是否存在
                cursor.execute('''
                    SELECT COUNT(*) as count 
                    FROM information_schema.tables 
                    WHERE table_schema = DATABASE() 
                    AND table_name = 'ip_blacklist'
                ''')
                table_exists = cursor.fetchone()
                if not table_exists or (isinstance(table_exists, dict) and table_exists.get('count', 0) == 0) or (isinstance(table_exists, tuple) and table_exists[0] == 0):
                    return
                
                cursor.execute('DELETE FROM ip_blacklist WHERE ip_address = %s', (ip,))
        except Exception as e:
            logger.error(f"从数据库删除黑名单失败: {e}", exc_info=True)


# 全局单例实例
_security_manager = None
_security_manager_lock = threading.Lock()


def get_security_manager() -> SecurityManager:
    """获取安全管理器单例"""
    global _security_manager
    if _security_manager is None:
        with _security_manager_lock:
            if _security_manager is None:
                _security_manager = SecurityManager()
    return _security_manager

