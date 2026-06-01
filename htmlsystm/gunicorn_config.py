#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gunicorn配置文件
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
# ==================== 高性能优化配置（16GB内存 + 2500Mb带宽）====================
# 基于服务器资源优化：
#   - 内存：16GB（可用约14GB，每个worker约300MB）
#   - 带宽：2500Mb（约312.5MB/s，理论可支持4500+请求/秒）
#   - CPU：假设8核（可根据实际调整）
#
# 推荐配置（平衡方案）：
#   - Workers: 24个（平衡内存和CPU，占用约7.2GB内存）
#   - Threads per Worker: 100个（充分利用内存和带宽）
#   - 总线程数: 24 × 100 = 2400个线程
#   - 理论并发能力: 2400个并发请求
#   - 预期在线用户: 3000-4000个
#
# 如需更高性能，可调整为：
#   - Workers: 32个，Threads: 120个（总3840线程，支持5000-6000在线用户）
#   注意：需要确保MySQL max_connections ≥ 200

# 获取CPU核心数
cpu_count = multiprocessing.cpu_count()

# 高性能配置：根据系统资源动态调整
# 优化策略：降低内存占用，防止OOM Kill
# 每个worker约占用300-400MB内存，需要预留系统内存
import psutil
try:
    # 获取总内存和可用内存（GB）
    mem = psutil.virtual_memory()
    total_memory_gb = mem.total / (1024**3)
    available_memory_gb = mem.available / (1024**3)
    
    # 每个worker约占用350MB，预留更多系统内存（3GB）
    # 保守估计：每个worker 400MB（包含线程开销）
    worker_memory_mb = 400
    reserved_memory_gb = 3  # 预留3GB给系统和其他进程
    
    max_workers_by_memory = int((available_memory_gb - reserved_memory_gb) * 1024 / worker_memory_mb)
    
    # 更保守的限制：最多12个worker（进一步降低内存占用）
    max_workers = min(max_workers_by_memory, 12)  # 从16降到12
    if max_workers < 2:
        max_workers = 2  # 至少2个worker（从4降到2）
    
    # 如果总内存小于8GB，使用更保守的配置
    if total_memory_gb < 8:
        max_workers = min(max_workers, 6)  # 小内存系统最多6个worker
        worker_memory_mb = 300  # 小内存系统每个worker约300MB
except Exception:
    # 如果无法获取内存信息，使用非常保守的配置
    max_workers = 4  # 从8降到4
    worker_memory_mb = 350

workers = min(cpu_count * 2, max_workers)  # 基于CPU和内存限制

worker_class = "gthread"  # 使用gthread worker，支持多线程并发
# 进一步降低线程数，减少内存占用（从60降到40）
threads = 40  # 每个worker 40个线程（从60降到40，减少内存占用）
worker_connections = 100000  # 每个worker的最大并发连接数（充分利用带宽）
timeout = 600  # worker超时时间（秒）- 增加到600秒，支持长时间运行的请求
keepalive = 30  # Keep-alive连接保持时间（秒）- 增加到30秒，减少连接建立开销
graceful_timeout = 120  # 优雅关闭超时时间（秒）

# 进程名称
proc_name = "htmlsystm_gunicorn"

# 日志配置
accesslog = "-"  # 输出到stdout
errorlog = "-"   # 输出到stderr
loglevel = "info"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# 性能优化（降低内存占用）
max_requests = 10000  # 每个worker处理的最大请求数（从20000降到10000，更频繁重启以释放内存）
max_requests_jitter = 500  # 随机抖动（从1000降到500），避免所有worker同时重启
# 必须为 False：preload 时 master/on_starting 会初始化 MySQL 连接池，fork 后 worker 继承失效连接会导致 HTTP 登录失败
preload_app = False

# 高并发优化
# 注意：sync worker class不支持threads参数
# 如果需要多线程，可以使用gthread worker class，但sync更适合I/O密集型应用

# 内存和性能优化
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

# 加载MySQL环境变量的辅助函数
def _load_mysql_env():
    """从 .mysql.env 补全环境变量（不覆盖已有值，Docker Compose 注入的 MYSQL_HOST=mysql 优先）"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    mysql_env_file = os.path.join(script_dir, '.mysql.env')
    if os.path.exists(mysql_env_file):
        with open(mysql_env_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and 'export ' in line:
                    key_value = line.replace('export ', '').strip()
                    if '=' in key_value:
                        key, value = key_value.split('=', 1)
                        value = value.strip("'\"")
                        # 仅当容器/Shell 未设置时才使用文件值，避免 localhost 覆盖 mysql 服务名
                        if os.environ.get(key):
                            continue
                        os.environ[key] = value

# 确保环境变量传递到worker进程
def when_ready(server):
    """在 worker 就绪后执行，确保环境变量被传递（勿在此阻塞网络 IO，否则网关 502）。"""
    _load_mysql_env()
    print("[htmlsystm] Gunicorn when_ready: 服务已监听，可接受请求", flush=True)

def pre_fork(server, worker):
    """在每个worker进程fork之前执行（关键：确保环境变量传递到worker进程）"""
    _load_mysql_env()


def post_fork(server, worker):
    """fork 后重置 MySQL 连接池等单例，避免 preload_app 导致 worker 继承失效连接"""
    _load_mysql_env()
    try:
        from server.gunicorn_fork import reset_worker_state
        reset_worker_state(worker.pid)
    except Exception as e:
        import logging
        logging.getLogger("gunicorn.error").warning(f"post_fork 重置单例失败: {e}")

# Gunicorn钩子函数：在master进程启动时执行一次钉钉同步
def _start_quick_link_icon_refresh_background():
    """master 启动后在后台刷新快捷链接站点图标（不阻塞健康检查）。"""
    if os.getenv('SKIP_QUICK_LINK_ICON_FETCH_ON_START', '').lower() in ('1', 'true', 'yes'):
        import logging
        logging.getLogger('gunicorn.error').info(
            'SKIP_QUICK_LINK_ICON_FETCH_ON_START=1，跳过启动时快捷链接图标抓取'
        )
        return

    import threading
    import logging

    interval = os.getenv('QUICK_LINK_ICON_FETCH_INTERVAL_SEC', '1.5')
    delay_sec = max(0, float(os.getenv('QUICK_LINK_ICON_FETCH_DELAY_SEC', '15')))

    def worker():
        try:
            if delay_sec > 0:
                import time
                time.sleep(delay_sec)
            from server.quick_link_manager import QuickLinkManager

            QuickLinkManager.ensure_default_icon_in_static()
            QuickLinkManager().refresh_all_icons_on_startup()
        except Exception as e:
            logging.getLogger('gunicorn.error').warning(
                '快捷链接图标启动刷新失败: %s', e, exc_info=True
            )

    logging.getLogger('gunicorn.error').info(
        '已安排启动后快捷链接图标抓取（后台线程，延迟 %ss，间隔 %ss）',
        delay_sec,
        interval,
    )
    threading.Thread(
        target=worker,
        daemon=True,
        name='quick-link-icon-refresh',
    ).start()


def on_starting(server):
    """在master进程启动时执行（只执行一次）"""
    import sys
    import os
    # 添加项目根目录到Python路径
    script_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, script_dir)
    
    # 确保环境变量被设置（从.mysql.env文件）
    _load_mysql_env()
    print("[htmlsystm] Gunicorn master on_starting", flush=True)

    _start_quick_link_icon_refresh_background()

    if os.getenv('SKIP_DINGTALK_SYNC_ON_START', '').lower() in ('1', 'true', 'yes'):
        import logging
        logging.getLogger('gunicorn.error').info(
            'SKIP_DINGTALK_SYNC_ON_START=1，跳过启动时阻塞钉钉同步（Docker/弱网推荐）'
        )
        return
    
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
    finally:
        # master 中 sync 会初始化 MySQL 连接池；fork 前必须清掉，避免 worker 继承失效连接
        try:
            from server.gunicorn_fork import reset_worker_state
            reset_worker_state(0)
        except Exception as reset_err:
            import logging
            logging.getLogger("gunicorn.error").warning(f"on_starting 重置单例失败: {reset_err}")

# 开发模式配置（单进程，便于调试）
if os.getenv('GUNICORN_DEV', '').lower() in ('1', 'true', 'yes'):
    workers = 1
    reload = True  # 代码变更时自动重载
    loglevel = "debug"

