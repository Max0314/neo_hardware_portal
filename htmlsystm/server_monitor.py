#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
服务器监控和自动重启脚本
功能：
1. 监控服务器进程是否运行
2. 服务器崩溃时自动重启
3. 记录重启次数和原因
4. 防止无限重启循环（最大重启次数和冷却时间）
5. 支持Windows和Linux
"""

import os
import sys
import subprocess
import time
import json
import platform
from datetime import datetime
from pathlib import Path

# 配置
MAX_RESTART_COUNT = 10  # 最大重启次数（在时间窗口内）
RESTART_WINDOW = 3600  # 时间窗口（秒，1小时）
COOLDOWN_TIME = 60  # 冷却时间（秒，连续重启后等待）
HEALTH_CHECK_INTERVAL = 30  # 健康检查间隔（秒）
MAX_RESTART_INTERVAL = 300  # 最大重启间隔（秒，如果超过这个时间，重置计数）

# 状态文件路径
DATA_DIR = os.path.join('data')
STATUS_FILE = os.path.join(DATA_DIR, '.server_monitor_status.json')
LOG_DIR = os.path.join('logs')
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)
MONITOR_LOG_FILE = os.path.join(LOG_DIR, 'monitor.log')

def log_message(level, message):
    """记录日志消息"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_entry = f"[{timestamp}] [{level}] {message}\n"
    
    # 输出到控制台
    print(log_entry.rstrip())
    
    # 写入日志文件
    try:
        with open(MONITOR_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(log_entry)
    except Exception:
        pass

def load_status():
    """加载监控状态"""
    if os.path.exists(STATUS_FILE):
        try:
            with open(STATUS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    
    # 默认状态
    return {
        'restart_count': 0,
        'last_restart_time': None,
        'first_restart_time': None,
        'total_restarts': 0,
        'last_exit_code': None,
        'last_crash_time': None
    }

def save_status(status):
    """保存监控状态"""
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(STATUS_FILE, 'w', encoding='utf-8') as f:
            json.dump(status, f, indent=2, ensure_ascii=False)
    except Exception as e:
        log_message('ERROR', f"保存状态失败: {e}")

def reset_restart_count_if_needed(status):
    """如果超过时间窗口，重置重启计数"""
    current_time = time.time()
    
    # 如果第一次重启时间存在且超过时间窗口，重置计数
    if status['first_restart_time']:
        elapsed = current_time - status['first_restart_time']
        if elapsed > RESTART_WINDOW:
            log_message('INFO', f"重启计数窗口已过期（{elapsed:.0f}秒），重置计数")
            status['restart_count'] = 0
            status['first_restart_time'] = None
    
    # 如果距离上次重启超过最大间隔，重置计数
    if status['last_restart_time']:
        elapsed = current_time - status['last_restart_time']
        if elapsed > MAX_RESTART_INTERVAL:
            log_message('INFO', f"距离上次重启已超过{MAX_RESTART_INTERVAL}秒，重置计数")
            status['restart_count'] = 0
            status['first_restart_time'] = None

def can_restart(status):
    """检查是否可以重启"""
    reset_restart_count_if_needed(status)
    
    # 如果重启次数超过限制
    if status['restart_count'] >= MAX_RESTART_COUNT:
        log_message('ERROR', f"重启次数已达到上限（{MAX_RESTART_COUNT}次），停止自动重启")
        log_message('ERROR', "请检查服务器日志并手动修复问题后，删除状态文件重新启动")
        return False
    
    return True

def record_restart(status, exit_code=None):
    """记录重启"""
    current_time = time.time()
    
    # 如果是第一次重启，记录时间
    if status['restart_count'] == 0:
        status['first_restart_time'] = current_time
    
    status['restart_count'] += 1
    status['total_restarts'] += 1
    status['last_restart_time'] = current_time
    status['last_exit_code'] = exit_code
    status['last_crash_time'] = current_time
    
    save_status(status)
    
    log_message('WARNING', f"记录重启 #{status['restart_count']}/{MAX_RESTART_COUNT} (总重启次数: {status['total_restarts']})")

def check_server_health(port=None):
    """检查服务器健康状态（通过HTTP请求）"""
    try:
        # 获取端口配置
        if port is None:
            if os.getenv('SERVER_PORT'):
                port = int(os.getenv('SERVER_PORT'))
            elif os.getenv('PORT'):
                port = int(os.getenv('PORT'))
            else:
                try:
                    from server.config import PORT
                    port = PORT
                except (ImportError, ValueError):
                    port = 8000  # 默认端口
        
        import urllib.request
        import urllib.error
        
        url = f'http://localhost:{port}/'
        req = urllib.request.Request(url)
        req.add_header('User-Agent', 'ServerMonitor/1.0')
        
        # 设置超时时间
        response = urllib.request.urlopen(req, timeout=5)
        return response.getcode() == 200
    except Exception:
        return False

def is_process_running(process):
    """检查进程是否还在运行"""
    if process is None:
        return False
    
    try:
        # 检查进程是否还在运行
        return_code = process.poll()
        # poll() 返回 None 表示进程还在运行
        if return_code is None:
            return True
        
        # 如果使用gunicorn，检查gunicorn master进程是否还在运行
        use_gunicorn = os.getenv('USE_GUNICORN', '').lower() in ('1', 'true', 'yes')
        if use_gunicorn:
            # 检查gunicorn master进程
            return is_gunicorn_running()
        
        return False
    except Exception:
        return False

def is_gunicorn_running():
    """检查gunicorn master进程是否在运行"""
    try:
        import subprocess
        # 查找gunicorn master进程（进程名包含htmlsystm_gunicorn或gunicorn master）
        result = subprocess.run(
            ['pgrep', '-f', 'gunicorn.*htmlsystm_gunicorn|gunicorn.*master'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=2
        )
        if result.returncode == 0 and result.stdout.strip():
            return True
        
        # 备用方法：检查gunicorn进程
        result = subprocess.run(
            ['pgrep', '-f', 'gunicorn.*server.wsgi_app'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=2
        )
        return result.returncode == 0 and result.stdout.strip() != b''
    except Exception:
        # 如果pgrep不可用，尝试使用ps
        try:
            result = subprocess.run(
                ['ps', 'aux'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=2
            )
            if result.returncode == 0:
                output = result.stdout.decode('utf-8', errors='ignore')
                # 检查是否有gunicorn master进程
                if 'gunicorn' in output.lower() and ('master' in output.lower() or 'htmlsystm_gunicorn' in output.lower()):
                    return True
        except Exception:
            pass
        return False

def stop_old_processes():
    """停止旧的服务器进程（gunicorn和占用端口的进程）"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 获取端口配置
    try:
        # 端口优先级：环境变量 > 配置文件 > 默认值
        if os.getenv('SERVER_PORT'):
            port = int(os.getenv('SERVER_PORT'))
        elif os.getenv('PORT'):
            port = int(os.getenv('PORT'))
        else:
            from server.config import PORT
            port = PORT
    except (ImportError, ValueError):
        port = 8000  # 默认端口
    
    log_message('INFO', f"停止旧的服务器进程（端口: {port}）...")
    
    killed_count = 0
    
    # 方法1: 使用pkill停止gunicorn进程
    try:
        if platform.system() != 'Windows':
            # Linux/Mac系统
            import subprocess as sp
            # 停止所有gunicorn master进程
            try:
                sp.run(['pkill', '-f', 'gunicorn.*htmlsystm_gunicorn'], 
                      stdout=sp.DEVNULL, stderr=sp.DEVNULL, timeout=5)
                sp.run(['pkill', '-f', 'gunicorn.*server.wsgi_app'], 
                      stdout=sp.DEVNULL, stderr=sp.DEVNULL, timeout=5)
                time.sleep(1)
                # 检查是否还有进程，强制终止
                result = sp.run(['pgrep', '-f', 'gunicorn.*htmlsystm_gunicorn|gunicorn.*server.wsgi_app'],
                              stdout=sp.PIPE, stderr=sp.DEVNULL, timeout=5)
                if result.returncode == 0 and result.stdout.strip():
                    sp.run(['pkill', '-9', '-f', 'gunicorn.*htmlsystm_gunicorn'],
                          stdout=sp.DEVNULL, stderr=sp.DEVNULL, timeout=5)
                    sp.run(['pkill', '-9', '-f', 'gunicorn.*server.wsgi_app'],
                          stdout=sp.DEVNULL, stderr=sp.DEVNULL, timeout=5)
                    time.sleep(1)
                killed_count = 1
                log_message('INFO', "已停止gunicorn进程")
            except (FileNotFoundError, sp.TimeoutExpired):
                pass
    except Exception as e:
        log_message('WARNING', f"停止gunicorn进程时出错: {e}")
    
    # 方法2: 使用lsof停止占用端口的进程
    if killed_count == 0:
        try:
            if platform.system() != 'Windows':
                import subprocess as sp
                try:
                    # 查找占用端口的进程
                    result = sp.run(['lsof', '-ti', f':{port}'],
                                  stdout=sp.PIPE, stderr=sp.DEVNULL, timeout=5)
                    if result.returncode == 0 and result.stdout.strip():
                        pids = result.stdout.strip().decode('utf-8').split('\n')
                        for pid in pids:
                            if pid.strip().isdigit():
                                try:
                                    sp.run(['kill', '-15', pid.strip()],
                                          stdout=sp.DEVNULL, stderr=sp.DEVNULL, timeout=2)
                                    time.sleep(0.5)
                                    # 检查进程是否还在运行
                                    check_result = sp.run(['ps', '-p', pid.strip()],
                                                         stdout=sp.DEVNULL, stderr=sp.DEVNULL, timeout=2)
                                    if check_result.returncode == 0:
                                        # 进程还在，强制终止
                                        sp.run(['kill', '-9', pid.strip()],
                                              stdout=sp.DEVNULL, stderr=sp.DEVNULL, timeout=2)
                                    killed_count += 1
                                except Exception:
                                    pass
                        if killed_count > 0:
                            log_message('INFO', f"已停止占用端口 {port} 的进程")
                except (FileNotFoundError, sp.TimeoutExpired):
                    pass
        except Exception as e:
            log_message('WARNING', f"停止占用端口的进程时出错: {e}")
    
    # 方法3: 使用fuser停止占用端口的进程（备用）
    if killed_count == 0:
        try:
            if platform.system() != 'Windows':
                import subprocess as sp
                try:
                    result = sp.run(['fuser', f'{port}/tcp'],
                                  stdout=sp.DEVNULL, stderr=sp.DEVNULL, timeout=5)
                    if result.returncode == 0:
                        sp.run(['fuser', '-k', f'{port}/tcp'],
                              stdout=sp.DEVNULL, stderr=sp.DEVNULL, timeout=5)
                        time.sleep(1)
                        killed_count = 1
                        log_message('INFO', f"已停止占用端口 {port} 的进程")
                except (FileNotFoundError, sp.TimeoutExpired):
                    pass
        except Exception as e:
            log_message('WARNING', f"使用fuser停止进程时出错: {e}")
    
    # 等待进程完全停止
    if killed_count > 0:
        time.sleep(2)
        log_message('INFO', "等待进程完全停止...")
    
    # 验证端口是否已释放
    try:
        if platform.system() != 'Windows':
            import subprocess as sp
            try:
                result = sp.run(['lsof', '-i', f':{port}'],
                              stdout=sp.DEVNULL, stderr=sp.DEVNULL, timeout=5)
                if result.returncode == 0:
                    log_message('WARNING', f"端口 {port} 仍被占用，尝试强制停止...")
                    # 最后尝试：强制停止所有占用端口的进程
                    result = sp.run(['lsof', '-ti', f':{port}'],
                                  stdout=sp.PIPE, stderr=sp.DEVNULL, timeout=5)
                    if result.returncode == 0 and result.stdout.strip():
                        pids = result.stdout.strip().decode('utf-8').split('\n')
                        for pid in pids:
                            if pid.strip().isdigit():
                                try:
                                    sp.run(['kill', '-9', pid.strip()],
                                          stdout=sp.DEVNULL, stderr=sp.DEVNULL, timeout=2)
                                except Exception:
                                    pass
                    time.sleep(1)
                else:
                    log_message('INFO', f"端口 {port} 已释放")
            except (FileNotFoundError, sp.TimeoutExpired):
                pass
    except Exception as e:
        log_message('WARNING', f"验证端口时出错: {e}")

def start_server():
    """启动服务器进程"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 在启动服务器之前，先停止旧的进程
    stop_old_processes()
    
    # 检查是否使用gunicorn（通过环境变量或配置文件）
    use_gunicorn = os.getenv('USE_GUNICORN', '').lower() in ('1', 'true', 'yes')
    gunicorn_mode = os.getenv('GUNICORN_MODE', 'prod')
    
    if use_gunicorn:
        # 使用gunicorn启动
        gunicorn_script = os.path.join(script_dir, 'start_gunicorn.sh')
        if os.path.exists(gunicorn_script):
            try:
                # 使用bash执行gunicorn启动脚本
                # 不使用PIPE，让输出直接显示到控制台
                process = subprocess.Popen(
                    ['bash', gunicorn_script, gunicorn_mode],
                    stdout=None,  # 直接输出到控制台
                    stderr=None,  # 直接输出到控制台
                    cwd=script_dir,
                    env=os.environ.copy()
                )
                log_message('INFO', f"Gunicorn启动脚本已执行 (PID: {process.pid}, 模式: {gunicorn_mode})")
                log_message('INFO', "Gunicorn输出将直接显示在控制台")
                # 等待一小段时间，让gunicorn启动
                time.sleep(3)
                # 检查gunicorn master进程是否启动成功
                if is_gunicorn_running():
                    log_message('INFO', "Gunicorn master进程已启动")
                else:
                    log_message('WARNING', "Gunicorn master进程可能未启动，继续监控...")
                return process
            except Exception as e:
                log_message('ERROR', f"启动Gunicorn服务器失败: {e}")
                return None
        else:
            log_message('WARNING', f"Gunicorn启动脚本不存在: {gunicorn_script}，回退到直接启动模式")
    
    # 直接启动server/main.py
    server_path = os.path.join(script_dir, 'server', 'main.py')
    
    if not os.path.exists(server_path):
        log_message('ERROR', f"服务器文件不存在: {server_path}")
        return None
    
    try:
        # 使用subprocess启动服务器
        # 不使用PIPE，让输出直接显示到控制台
        process = subprocess.Popen(
            [sys.executable, server_path],
            stdout=None,  # 直接输出到控制台
            stderr=None,  # 直接输出到控制台
            cwd=script_dir
        )
        log_message('INFO', f"服务器进程已启动 (PID: {process.pid})")
        log_message('INFO', "服务器输出将直接显示在控制台")
        return process
    except Exception as e:
        log_message('ERROR', f"启动服务器失败: {e}")
        return None

def main():
    """主监控循环"""
    log_message('INFO', "=" * 60)
    log_message('INFO', "服务器监控程序启动")
    log_message('INFO', f"最大重启次数: {MAX_RESTART_COUNT} (时间窗口: {RESTART_WINDOW}秒)")
    log_message('INFO', f"健康检查间隔: {HEALTH_CHECK_INTERVAL}秒")
    log_message('INFO', f"冷却时间: {COOLDOWN_TIME}秒")
    log_message('INFO', "=" * 60)
    
    status = load_status()
    
    # 显示当前状态
    if status['total_restarts'] > 0:
        log_message('INFO', f"历史总重启次数: {status['total_restarts']}")
        if status['last_crash_time']:
            last_crash = datetime.fromtimestamp(status['last_crash_time'])
            log_message('INFO', f"上次崩溃时间: {last_crash.strftime('%Y-%m-%d %H:%M:%S')}")
    
    process = None
    last_health_check = 0
    
    try:
        while True:
            # 检查进程是否还在运行
            if not is_process_running(process):
                # 如果进程不存在，尝试启动
                if process is not None:
                    # 检查退出码（如果进程已退出）
                    exit_code = process.returncode if process.returncode is not None else -1
                    
                    # 如果使用gunicorn，检查gunicorn是否真的退出了
                    use_gunicorn = os.getenv('USE_GUNICORN', '').lower() in ('1', 'true', 'yes')
                    if use_gunicorn:
                        if is_gunicorn_running():
                            # Gunicorn还在运行，只是bash进程退出了，这是正常的
                            log_message('DEBUG', "Bash进程已退出，但Gunicorn master进程仍在运行（正常）")
                            # 重置健康检查时间，继续监控
                            last_health_check = time.time()
                            time.sleep(5)
                            continue
                        else:
                            log_message('WARNING', f"Gunicorn master进程已退出，退出码: {exit_code}")
                    else:
                        log_message('WARNING', f"服务器进程已退出，退出码: {exit_code}")
                    
                    # 检查是否可以重启
                    if not can_restart(status):
                        log_message('ERROR', "已达到最大重启次数，停止监控")
                        log_message('ERROR', f"状态文件位置: {STATUS_FILE}")
                        log_message('ERROR', "请检查服务器日志并手动修复问题")
                        break
                    
                    # 记录重启
                    record_restart(status, exit_code)
                    
                    # 如果连续重启，等待冷却时间
                    if status['restart_count'] > 1:
                        log_message('INFO', f"等待冷却时间 {COOLDOWN_TIME} 秒...")
                        time.sleep(COOLDOWN_TIME)
                
                # 启动服务器
                log_message('INFO', "正在启动服务器...")
                process = start_server()
                
                if process is None:
                    log_message('ERROR', "无法启动服务器，等待后重试...")
                    time.sleep(COOLDOWN_TIME)
                    continue
                
                # 等待服务器启动
                log_message('INFO', "等待服务器启动...")
                time.sleep(5)
                
                # 重置健康检查时间
                last_health_check = time.time()
            
            # 定期健康检查
            current_time = time.time()
            if current_time - last_health_check >= HEALTH_CHECK_INTERVAL:
                try:
                    # 端口优先级：环境变量 > 配置文件 > 默认值
                    if os.getenv('SERVER_PORT'):
                        server_port = int(os.getenv('SERVER_PORT'))
                    elif os.getenv('PORT'):
                        server_port = int(os.getenv('PORT'))
                    else:
                        from server.config import PORT
                        server_port = PORT
                except (ImportError, ValueError):
                    server_port = 8080  # 默认端口已改为8080
                
                if check_server_health(server_port):
                    log_message('DEBUG', "服务器健康检查通过")
                else:
                    log_message('WARNING', "服务器健康检查失败，但进程仍在运行")
                
                last_health_check = current_time
            
            # 等待一段时间后再次检查
            time.sleep(5)
            
    except KeyboardInterrupt:
        log_message('INFO', "收到停止信号，正在关闭监控...")
        
        # 如果使用gunicorn，需要停止gunicorn master进程
        use_gunicorn = os.getenv('USE_GUNICORN', '').lower() in ('1', 'true', 'yes')
        if use_gunicorn:
            log_message('INFO', "正在停止Gunicorn服务器...")
            try:
                import subprocess
                # 查找并停止gunicorn master进程
                result = subprocess.run(
                    ['pkill', '-f', 'gunicorn.*htmlsystm_gunicorn|gunicorn.*master'],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=5
                )
                if result.returncode == 0:
                    log_message('INFO', "已发送停止信号给Gunicorn进程")
                    # 等待进程结束
                    time.sleep(2)
                    # 如果还在运行，强制终止
                    if is_gunicorn_running():
                        log_message('WARNING', "Gunicorn进程未在2秒内结束，强制终止...")
                        subprocess.run(['pkill', '-9', '-f', 'gunicorn'], timeout=5)
                else:
                    # 备用方法：直接使用pkill强制停止
                    log_message('INFO', "使用备用方法停止Gunicorn进程...")
                    subprocess.run(['pkill', '-9', '-f', 'gunicorn.*htmlsystm_gunicorn'], timeout=5)
                    subprocess.run(['pkill', '-9', '-f', 'gunicorn.*server.wsgi_app'], timeout=5)
            except Exception as e:
                log_message('ERROR', f"停止Gunicorn进程失败: {e}")
        
        # 停止启动脚本进程（如果还在运行）
        if process:
            try:
                if is_process_running(process):
                    log_message('INFO', "正在停止启动脚本进程...")
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        log_message('WARNING', "进程未在5秒内结束，强制终止...")
                        process.kill()
                        process.wait()
            except Exception as e:
                log_message('ERROR', f"停止启动脚本进程失败: {e}")
        
        log_message('INFO', "监控程序已停止")
    except Exception as e:
        log_message('ERROR', f"监控程序异常: {e}")
        import traceback
        log_message('ERROR', traceback.format_exc())
    finally:
        # 保存最终状态
        save_status(status)

if __name__ == '__main__':
    main()

