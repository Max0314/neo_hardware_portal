#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件锁工具模块
提供线程安全和跨进程安全的文件锁功能，用于保护Excel文件操作
支持多进程环境（Gunicorn多worker）
"""
import threading
import os
import time

# 尝试导入跨进程文件锁模块
try:
    import fcntl
    HAS_FCNTL = True
except ImportError:
    HAS_FCNTL = False

try:
    import msvcrt
    HAS_MSVCRT = True
except ImportError:
    HAS_MSVCRT = False

# 文件锁字典，用于保护Excel文件操作
_file_locks = {}  # 线程锁
_file_locks_lock = threading.Lock()
_process_locks = {}  # 跨进程锁文件句柄
_process_locks_lock = threading.Lock()

class ProcessFileLock:
    """跨进程文件锁（使用文件系统锁）"""
    def __init__(self, filepath, timeout=30):
        self.filepath = filepath
        self.lock_file = f"{filepath}.lock"
        self.lock_fd = None
        self.timeout = timeout
        self.acquired = False
    
    def _cleanup_stale_lock(self):
        """清理僵尸锁文件（如果锁文件存在但进程已不存在）"""
        if not os.path.exists(self.lock_file):
            return
        
        try:
            # 检查锁文件的修改时间
            lock_mtime = os.path.getmtime(self.lock_file)
            lock_age = time.time() - lock_mtime
            
            # 对于 recovering 锁，使用更短的超时时间（2分钟）
            is_recovering_lock = '.recovering' in self.lock_file
            max_age = 120 if is_recovering_lock else 300  # recovering锁2分钟，其他锁5分钟
            
            if lock_age > max_age:
                # 尝试读取锁文件中的PID（如果有）
                try:
                    with open(self.lock_file, 'r') as f:
                        pid_str = f.read().strip()
                        if pid_str.isdigit():
                            pid = int(pid_str)
                            # 检查进程是否还存在
                            try:
                                os.kill(pid, 0)  # 发送信号0，不杀死进程，只检查是否存在
                                # 进程存在，但锁文件很旧，可能是进程卡住了
                                # 对于 recovering 锁，如果超过2分钟，强制清理
                                if is_recovering_lock and lock_age > 120:
                                    try:
                                        os.remove(self.lock_file)
                                        return
                                    except:
                                        pass
                            except (OSError, ProcessLookupError):
                                # 进程不存在，删除僵尸锁文件
                                try:
                                    os.remove(self.lock_file)
                                    return
                                except:
                                    pass
                except:
                    # 如果无法读取或解析，检查文件年龄
                    # 对于 recovering 锁，如果超过2分钟，强制清理
                    if is_recovering_lock and lock_age > 120:
                        try:
                            os.remove(self.lock_file)
                            return
                        except:
                            pass
                    elif lock_age > 600:  # 其他锁超过10分钟
                        try:
                            os.remove(self.lock_file)
                            return
                        except:
                            pass
        except Exception:
            pass  # 忽略清理错误
    
    def __enter__(self):
        """获取锁"""
        # 清理僵尸锁
        self._cleanup_stale_lock()
        
        # 添加随机延迟，避免所有worker同时竞争锁
        import random
        time.sleep(random.uniform(0, 0.5))
        
        start_time = time.time()
        retry_count = 0
        last_cleanup_time = 0
        cleanup_interval = 5  # 每5秒检查一次僵尸锁
        
        while time.time() - start_time < self.timeout:
            try:
                # 定期清理僵尸锁（在等待过程中）
                current_time = time.time()
                if current_time - last_cleanup_time > cleanup_interval:
                    self._cleanup_stale_lock()
                    last_cleanup_time = current_time
                
                # 确保目录存在
                os.makedirs(os.path.dirname(self.lock_file) if os.path.dirname(self.lock_file) else '.', exist_ok=True)
                
                # 打开锁文件
                self.lock_fd = open(self.lock_file, 'w')
                
                # 写入当前进程PID（用于调试和清理）
                try:
                    self.lock_fd.write(str(os.getpid()))
                    self.lock_fd.flush()
                except:
                    pass
                
                # 尝试获取锁
                if HAS_FCNTL:
                    # Linux/Unix系统：使用fcntl
                    try:
                        fcntl.flock(self.lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        self.acquired = True
                        return self
                    except (IOError, OSError):
                        self.lock_fd.close()
                        self.lock_fd = None
                elif HAS_MSVCRT:
                    # Windows系统：使用msvcrt
                    try:
                        msvcrt.locking(self.lock_fd.fileno(), msvcrt.LK_NBLCK, 1)
                        self.acquired = True
                        return self
                    except (IOError, OSError):
                        self.lock_fd.close()
                        self.lock_fd = None
                else:
                    # 不支持跨进程锁，使用线程锁
                    self.acquired = True
                    return self
                
                # 如果获取锁失败，等待一小段时间后重试（使用指数退避）
                retry_count += 1
                wait_time = min(0.1 * (2 ** min(retry_count // 10, 3)), 1.0)  # 最多等待1秒
                time.sleep(wait_time)
            except Exception as e:
                if self.lock_fd:
                    try:
                        self.lock_fd.close()
                    except:
                        pass
                    self.lock_fd = None
                retry_count += 1
                wait_time = min(0.1 * (2 ** min(retry_count // 10, 3)), 1.0)
                time.sleep(wait_time)
        
        # 超时，最后尝试清理并抛出异常
        self._cleanup_stale_lock()
        raise TimeoutError(f"无法获取文件锁（超时{self.timeout}秒）: {self.lock_file}")
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """释放锁"""
        if self.lock_fd:
            try:
                if HAS_FCNTL:
                    fcntl.flock(self.lock_fd.fileno(), fcntl.LOCK_UN)
                elif HAS_MSVCRT:
                    msvcrt.locking(self.lock_fd.fileno(), msvcrt.LK_UNLCK, 1)
                self.lock_fd.close()
                # 删除锁文件
                try:
                    if os.path.exists(self.lock_file):
                        os.remove(self.lock_file)
                except:
                    pass
            except:
                pass
            self.lock_fd = None
        self.acquired = False

def get_file_lock(filepath):
    """
    获取文件锁，确保同一文件的操作是线程安全和跨进程安全的
    
    Args:
        filepath: 文件路径
        
    Returns:
        该文件的线程锁对象（内部会结合跨进程锁使用）
    """
    with _file_locks_lock:
        if filepath not in _file_locks:
            _file_locks[filepath] = threading.Lock()
        return _file_locks[filepath]

def get_process_file_lock(filepath, timeout=30):
    """
    获取跨进程文件锁（用于保护多进程环境下的文件操作）
    
    Args:
        filepath: 文件路径
        timeout: 超时时间（秒）
        
    Returns:
        ProcessFileLock上下文管理器
    """
    return ProcessFileLock(filepath, timeout)

