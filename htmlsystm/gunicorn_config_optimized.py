#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gunicorn配置文件 - 优化版本（进程翻倍）
支持单进程和多进程模式
"""
import multiprocessing
import os

# 服务器配置
# 端口配置：优先从环境变量读取，否则从配置文件读取，最后使用默认值8000
_port = int(os.getenv('SERVER_PORT') or os.getenv('PORT') or 0)
if _port == 0:
    # 尝试从配置文件读取
    try:
        from server.config import PORT
        _port = PORT
    except (ImportError, AttributeError):
        _port = 8000  # 默认端口
bind = f"0.0.0.0:{_port}"

# ==================== 进程配置（翻倍版本）====================
# 优化worker数量：进程翻倍配置
# 公式：workers = CPU核心数 * 2（最多32个worker，翻倍）
# 注意：增加worker数量会：
#   1. 增加内存占用（每个worker独立加载数据）
#   2. 增加数据库连接数（需要确保MySQL连接池足够大）
#   3. 提高并发处理能力（更多worker可以同时处理请求）
#   4. 可能增加文件锁竞争（但系统已实现跨进程同步机制）

# 获取CPU核心数
cpu_count = multiprocessing.cpu_count()
# 进程翻倍：从16增加到32（或CPU核心数*2，取较小值）
workers = min(cpu_count * 2, 32)  # 翻倍：16 -> 32

# 使用gthread worker class，支持多线程并发
worker_class = "gthread"

# 每个worker的线程数（可以适当减少，因为worker数量增加了）
# 总并发能力 = 32 workers * 50 threads = 1600个并发请求
threads = 50  # 保持50个线程，总并发能力翻倍

worker_connections = 50000  # 每个worker的最大并发连接数
timeout = 600  # worker超时时间（秒）
keepalive = 30  # Keep-alive连接保持时间（秒）
graceful_timeout = 120  # 优雅关闭超时时间（秒）

# 进程名称
proc_name = "htmlsystm_gunicorn"

# 日志配置
accesslog = "-"  # 输出到stdout
errorlog = "-"   # 输出到stderr
loglevel = "info"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# 性能优化
max_requests = 20000  # 每个worker处理的最大请求数
max_requests_jitter = 1000  # 随机抖动，避免所有worker同时重启

# 重要：预加载应用（节省内存，但需要注意数据同步）
# 当preload_app=True时：
#   - 应用代码只加载一次（节省内存）
#   - 但每个worker会独立加载数据到内存
#   - 系统已实现跨进程缓存同步机制（通过文件标记）
preload_app = True

# 高并发优化
limit_request_line = 8190  # 请求行最大长度（增加到8190，支持长URL）
limit_request_fields = 200  # 请求头最大数量（增加到200，支持更多Cookie）
limit_request_field_size = 16384  # 请求头字段最大大小（增加到16KB，支持较大的Cookie值）

# 进程管理
daemon = False  # 不以守护进程运行（使用systemd或supervisor管理）
pidfile = None  # PID文件路径（如果需要）
umask = 0  # 文件权限掩码
user = None  # 运行用户（如果需要）
group = None  # 运行组（如果需要）
tmp_upload_dir = None  # 临时上传目录

# SSL配置（如果需要HTTPS）
# keyfile = "/path/to/keyfile"
# certfile = "/path/to/certfile"

# 其他配置
forwarded_allow_ips = "*"  # 允许的代理IP（生产环境应设置为具体IP）

# Gunicorn钩子函数：在master进程启动时执行一次钉钉同步
def on_starting(server):
    """在master进程启动时执行（只执行一次）"""
    import sys
    import os
    # 添加项目根目录到Python路径
    script_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, script_dir)
    
    try:
        from server.logger import logger
        from server.config import BASE_DIR
        from server.main import sync_dingtalk_data
        
        # 检查标志文件是否存在（如果存在且时间在5小时内，说明刚同步过，跳过）
        sync_flag_file = os.path.join(BASE_DIR, 'data', '.sync_started')
        sync_lock_file = os.path.join(BASE_DIR, 'data', '.sync_lock')
        os.makedirs(os.path.dirname(sync_flag_file), exist_ok=True)
        
        should_sync = True
        if os.path.exists(sync_flag_file):
            try:
                import time
                file_mtime = os.path.getmtime(sync_flag_file)
                time_diff = time.time() - file_mtime
                if time_diff < 18000:  # 5小时内（5 * 60 * 60 = 18000秒）
                    hours = int(time_diff // 3600)
                    minutes = int((time_diff % 3600) // 60)
                    logger.info(f"ℹ️  钉钉同步任务在 {hours}小时{minutes}分钟前已执行，跳过（避免频繁同步）")
                    should_sync = False
            except Exception:
                pass
        
        if should_sync:
            # 使用文件锁确保只执行一次（跨进程安全）
            lock_acquired = False
            lock_fd = None
            
            try:
                import fcntl
                # Linux系统：使用文件锁
                lock_fd = open(sync_lock_file, 'w')
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    lock_acquired = True
                    logger.info("🔒 成功获取文件锁，开始执行同步任务")
                except (IOError, OSError) as e:
                    # 无法获取锁，说明其他进程已经启动了同步任务
                    logger.info(f"ℹ️  无法获取文件锁，同步任务已在其他进程启动，跳过: {e}")
                    lock_fd.close()
                    lock_fd = None
            except ImportError:
                # Windows系统或其他不支持fcntl的系统：使用文件标志
                if not os.path.exists(sync_flag_file):
                    lock_acquired = True
                else:
                    logger.info("ℹ️  同步任务已启动（检测到标志文件），跳过")
            
            if lock_acquired:
                try:
                    # 阻塞执行同步任务（确保成功）
                    logger.info("=" * 60)
                    logger.info("🔄 开始启动时同步钉钉用户数据（阻塞模式，确保成功）...")
                    logger.info("=" * 60)
                    sync_dingtalk_data()  # 阻塞执行，确保成功
                    logger.info("✅ 启动时同步钉钉用户数据完成")
                    
                    # 更新标志文件（记录执行时间和进程ID）
                    import time
                    with open(sync_flag_file, 'w') as f:
                        f.write(f"{os.getpid()}\n{time.time()}\n")
                    
                    # 同步完成后，清除预加载器缓存
                    from server.data_preloader import get_data_preloader
                    preloader = get_data_preloader()
                    if preloader:
                        preloader.invalidate_cache('users')
                        preloader.invalidate_cache('departments')
                        logger.info("✅ 已清除用户和部门缓存，将从数据库重新加载到内存")
                    
                    # 保持文件锁直到进程结束（Linux系统）
                    if lock_fd:
                        # 不关闭文件，保持锁直到进程结束
                        pass
                except Exception as e:
                    logger.error(f"执行同步任务失败: {e}", exc_info=True)
                    # 如果同步失败，删除标志文件，允许下次重试
                    try:
                        if os.path.exists(sync_flag_file):
                            os.remove(sync_flag_file)
                    except Exception:
                        pass
                    if lock_fd:
                        try:
                            lock_fd.close()
                        except Exception:
                            pass
    except Exception as e:
        logger.error(f"启动时同步钉钉数据失败: {e}", exc_info=True)
        logger.warning("服务器将继续启动，但数据可能不是最新的")

# 开发模式配置（单进程，便于调试）
if os.getenv('GUNICORN_DEV', '').lower() in ('1', 'true', 'yes'):
    workers = 1
    reload = True  # 代码变更时自动重载
    loglevel = "debug"

