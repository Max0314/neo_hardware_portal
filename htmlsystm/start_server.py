#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
硬件研发部管理系统启动脚本（Python版本）
功能：检查依赖、初始化系统、启动服务器
优势：无需设置执行权限，直接运行 python start_server.py 即可
"""

import os
import sys
import subprocess
import platform
import argparse
from datetime import datetime

# 颜色定义（Windows和Linux兼容）
if platform.system() == 'Windows':
    # Windows不支持ANSI颜色，使用简单输出
    class Colors:
        RED = ''
        GREEN = ''
        YELLOW = ''
        BLUE = ''
        NC = ''
else:
    class Colors:
        RED = '\033[0;31m'
        GREEN = '\033[0;32m'
        YELLOW = '\033[1;33m'
        BLUE = '\033[0;34m'
        NC = '\033[0m'

def print_info(msg):
    print(f"{Colors.BLUE}ℹ️  {msg}{Colors.NC}")

def print_success(msg):
    print(f"{Colors.GREEN}✅ {msg}{Colors.NC}")

def print_warning(msg):
    print(f"{Colors.YELLOW}⚠️  {msg}{Colors.NC}")

def print_error(msg):
    print(f"{Colors.RED}❌ {msg}{Colors.NC}")

def print_step(msg):
    print(f"\n{Colors.BLUE}{'━' * 80}{Colors.NC}")
    print(f"{Colors.BLUE}📌 {msg}{Colors.NC}")
    print(f"{Colors.BLUE}{'━' * 80}{Colors.NC}\n")

def check_command(cmd):
    """检查命令是否存在"""
    try:
        subprocess.run([cmd, '--version'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

def run_command(cmd, check=True, shell=False):
    """运行命令"""
    try:
        if isinstance(cmd, str):
            result = subprocess.run(cmd, shell=True, check=check, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        else:
            result = subprocess.run(cmd, check=check, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, shell=shell)
        return result.returncode == 0, result.stdout, result.stderr
    except Exception as e:
        return False, '', str(e)

def kill_process_on_port(port):
    """检查并结束占用指定端口的进程"""
    is_windows = platform.system() == 'Windows'
    
    try:
        if is_windows:
            # Windows系统使用netstat和taskkill
            # 查找占用端口的进程
            netstat_cmd = f'netstat -ano | findstr :{port}'
            result = subprocess.run(netstat_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
            if result.returncode == 0 and result.stdout.strip():
                # 提取PID
                lines = result.stdout.strip().split('\n')
                pids = set()
                for line in lines:
                    parts = line.split()
                    if len(parts) >= 5:
                        pid = parts[-1]
                        if pid.isdigit():
                            pids.add(pid)
                
                # 结束进程
                for pid in pids:
                    try:
                        subprocess.run(f'taskkill /F /PID {pid}', shell=True, 
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
                        print_warning(f"已结束占用端口 {port} 的进程 (PID: {pid})")
                    except subprocess.CalledProcessError:
                        pass
                return len(pids) > 0
        else:
            # Linux系统使用lsof或fuser
            # 先尝试使用lsof
            lsof_cmd = ['lsof', '-ti', f':{port}']
            result = subprocess.run(lsof_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
            
            if result.returncode == 0 and result.stdout.strip():
                pids = result.stdout.strip().split('\n')
                for pid in pids:
                    if pid.isdigit():
                        try:
                            subprocess.run(['kill', '-9', pid], 
                                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
                            print_warning(f"已结束占用端口 {port} 的进程 (PID: {pid})")
                        except subprocess.CalledProcessError:
                            pass
                return True
            else:
                # 如果lsof不可用，尝试使用fuser
                fuser_cmd = ['fuser', '-k', f'{port}/tcp']
                result = subprocess.run(fuser_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
                if result.returncode == 0:
                    print_warning(f"已结束占用端口 {port} 的进程")
                    return True
    except FileNotFoundError:
        # 如果命令不存在，忽略
        pass
    except Exception as e:
        print_warning(f"检查端口 {port} 时出错: {e}")
    
    return False

def main():
    # 获取脚本所在目录（项目根目录）
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    os.chdir(SCRIPT_DIR)
    
    print_step("启动硬件研发部管理系统")
    
    # 检查Python版本
    print_info("检查Python环境...")
    python_cmd = 'python3' if platform.system() != 'Windows' else 'python'
    
    if not check_command(python_cmd):
        print_error(f"未找到 {python_cmd}，请先安装 Python 3.6 或更高版本")
        sys.exit(1)
    
    version_output = subprocess.run([python_cmd, '--version'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    python_version = version_output.stdout.strip()
    print_success(f"Python 版本: {python_version}")
    
    # 检查Python依赖
    print_info("检查Python依赖...")
    missing_deps = []
    
    try:
        import openpyxl
    except ImportError:
        missing_deps.append('openpyxl')
    
    if missing_deps:
        print_warning(f"缺少以下依赖: {', '.join(missing_deps)}")
        print_info("正在安装依赖...")
        success, _, error = run_command([sys.executable, '-m', 'pip', 'install'] + missing_deps)
        if not success:
            print_error(f"依赖安装失败，请手动执行: pip install {' '.join(missing_deps)}")
            print_error(f"错误信息: {error}")
            sys.exit(1)
        print_success("依赖安装完成")
    else:
        print_success("所有依赖已安装")
    
    # 初始化数据库模式（如果数据库不存在）
    print_info("检查数据库...")
    db_path = os.path.join('data', 'material.db')
    if not os.path.exists(db_path):
        print_warning("数据库不存在，正在初始化数据库模式...")
        try:
            from server.db_schema import initialize_db_schema
            initialize_db_schema()
            print_success("数据库模式初始化完成")
        except Exception as e:
            print_warning(f"数据库模式初始化失败，将在首次运行时自动初始化: {e}")
    else:
        # 确保数据库模式是最新的
        try:
            from server.db_schema import initialize_db_schema
            initialize_db_schema()
            print_info("数据库模式已是最新版本")
        except Exception as e:
            print_warning(f"数据库模式检查失败: {e}")
    
    # 初始化系统（如果第一次运行）
    if not os.path.exists(db_path):
        print_step("首次运行，初始化系统...")
        success, _, error = run_command([sys.executable, 'init_system.py'])
        if not success:
            print_error("系统初始化失败")
            print_error(f"错误信息: {error}")
            sys.exit(1)
        print_success("系统初始化完成")
    else:
        print_info("系统已初始化，跳过初始化步骤")
        
        # 检查部门Excel文件完整性
        print_info("检查部门Excel文件...")
        try:
            from server.department_manager import DepartmentManager
            dept_mgr = DepartmentManager()
            is_valid, error_msg = dept_mgr.check_file_integrity()
            if is_valid:
                print_success("部门Excel文件检查通过")
            else:
                print_warning(f"部门Excel文件检查失败: {error_msg}")
                print_info("系统将自动修复文件格式...")
                # 重新初始化会修复文件
                dept_mgr._ensure_departments_file()
                print_success("部门Excel文件已修复")
        except Exception as e:
            print_warning(f"检查部门Excel文件时出错: {e}")
            print_info("系统将在首次使用时自动创建文件")
        
        # 如果存在旧的Excel用户文件且未迁移，静默自动迁移（不询问）
        excel_users_file = os.path.join('data', 'users.xlsx')
        migrated_flag = os.path.join('data', '.migrated')
        if os.path.exists(excel_users_file) and not os.path.exists(migrated_flag):
            print_info("检测到Excel用户文件，自动迁移到SQLite...")
            success, _, error = run_command([sys.executable, 'migrate_to_sqlite.py'], check=False)
            if success:
                try:
                    with open(migrated_flag, 'w') as f:
                        f.write('migrated')
                    print_success("数据迁移完成")
                    # 迁移成功后删除Excel文件
                    if os.path.exists(excel_users_file):
                        os.remove(excel_users_file)
                        print_info("已删除旧的Excel用户文件")
                except Exception as e:
                    print_warning(f"无法创建迁移标志文件: {e}")
            else:
                print_warning("数据迁移失败，但继续启动服务器（如需迁移，请手动运行: python migrate_to_sqlite.py）")
    
    # 创建日志目录
    print_info("检查日志目录...")
    parent_dir = os.path.dirname(SCRIPT_DIR)
    log_dir = os.path.join(parent_dir, 'htmlsystm_LOG')
    try:
        os.makedirs(log_dir, exist_ok=True)
        print_success(f"日志目录: {log_dir}")
    except Exception as e:
        print_warning(f"创建日志目录失败: {e}")
        log_dir = None
    
    # 启动备份服务（后台线程）
    print_info("启动自动备份服务...")
    backup_script = os.path.join(SCRIPT_DIR, 'backup_system.py')
    if os.path.exists(backup_script):
        try:
            import threading
            def run_backup():
                try:
                    subprocess.run([sys.executable, backup_script], 
                                 stdout=subprocess.DEVNULL, 
                                 stderr=subprocess.DEVNULL)
                except Exception as e:
                    print_warning(f"备份服务异常: {e}")
            
            backup_thread = threading.Thread(target=run_backup, daemon=True)
            backup_thread.start()
            print_success("自动备份服务已启动（每30分钟备份一次）")
        except Exception as e:
            print_warning(f"启动备份服务失败: {e}")
    else:
        print_warning("备份脚本不存在，跳过备份服务")
    
    # 启动服务器（使用监控模式）
    print_step("启动服务器（监控模式）")
    
    # 解析命令行参数
    import argparse
    parser = argparse.ArgumentParser(description='启动硬件研发部管理系统服务器')
    parser.add_argument('--port', '-p', type=int, 
                       help='服务器端口（优先级：命令行参数 > 环境变量 SERVER_PORT/PORT > 配置文件 > 默认8000）')
    parser.add_argument('--no-monitor', action='store_true',
                       help='不使用监控模式，直接启动服务器')
    args = parser.parse_args()
    
    # 检查并结束占用端口的进程
    # 端口优先级：命令行参数 > 环境变量 SERVER_PORT > 环境变量 PORT > 配置文件 > 默认值
    try:
        if args.port:
            server_port = args.port
            print_info(f"使用命令行指定的端口: {server_port}")
        elif os.getenv('SERVER_PORT'):
            server_port = int(os.getenv('SERVER_PORT'))
            print_info(f"使用环境变量 SERVER_PORT: {server_port}")
        elif os.getenv('PORT'):
            server_port = int(os.getenv('PORT'))
            print_info(f"使用环境变量 PORT: {server_port}")
        else:
            from server.config import PORT
            server_port = PORT
            print_info(f"使用配置文件中的端口: {server_port}")
    except (ImportError, ValueError) as e:
        server_port = 8000  # 默认端口
        print_warning(f"无法读取端口配置，使用默认端口: {server_port} ({e})")
    
    # 如果通过命令行或环境变量设置了端口，更新环境变量，让服务器进程也能读取到
    if args.port or os.getenv('SERVER_PORT') or os.getenv('PORT'):
        os.environ['SERVER_PORT'] = str(server_port)
    
    print_info(f"检查端口 {server_port} 是否被占用...")
    if kill_process_on_port(server_port):
        print_info("等待端口释放...")
        import time
        time.sleep(2)  # 等待2秒确保端口释放
    else:
        print_info("端口未被占用")
    
    print_info(f"当前工作目录: {os.getcwd()}")
    print_info(f"服务器将监听: http://0.0.0.0:{server_port}")
    print_info("🚀 使用高并发优化版服务器（支持200+并发用户）")
    
    # 检查是否使用监控模式
    if args.no_monitor:
        print_info("⚠️  使用普通模式启动（无自动重启）")
        monitor_mode = False
    else:
        print_info("🛡️  启用自动监控和重启功能")
        monitor_mode = True
    
    print_info("按 Ctrl+C 停止服务器")
    print()
    
    # 如果使用监控模式，检查监控脚本是否存在
    if monitor_mode:
        monitor_path = os.path.join('server_monitor.py')
        if not os.path.exists(monitor_path):
            print_warning("监控脚本不存在，回退到普通模式")
            monitor_mode = False
    
    # 根据模式启动
    if monitor_mode:
        # 使用监控模式启动
        print_info("正在启动服务器监控程序...")
        print_info("监控程序将自动重启崩溃的服务器")
        print()
        
        try:
            # 启动监控程序
            process = subprocess.Popen([sys.executable, monitor_path])
            process.wait()
            
            if process.returncode == 0:
                print_success("监控程序已正常退出")
            else:
                print_error(f"监控程序异常退出，退出码: {process.returncode}")
                sys.exit(1)
        except KeyboardInterrupt:
            print()
            print_info("正在停止监控程序...")
            if 'process' in locals():
                process.terminate()
                process.wait()
            print_success("监控程序已停止")
        except Exception as e:
            print_error(f"启动监控程序失败: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)
    else:
        # 普通模式启动
        # 准备日志文件路径
        if log_dir:
            log_file = os.path.join(log_dir, f'server_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
            error_log_file = os.path.join(log_dir, f'error_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
        else:
            log_file = None
            error_log_file = None
        
        # 启动服务器
        try:
            server_path = os.path.join('server', 'main.py')
            # 通过subprocess运行服务器，这样可以更好地处理信号和输出
            print_info("正在启动服务器进程...")
            
            # 如果指定了日志目录，同时输出到控制台和日志文件
            if log_file:
                import threading
                import queue
                
                # 打开日志文件
                log_f = open(log_file, 'w', encoding='utf-8')
                err_f = open(error_log_file, 'w', encoding='utf-8')
                
                print_info(f"服务器日志同时保存到: {log_file}")
                print_info(f"错误日志同时保存到: {error_log_file}")
                print()
                
                # 启动服务器进程，使用管道捕获输出
                process = subprocess.Popen(
                    [sys.executable, server_path],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    bufsize=1,
                    universal_newlines=True
                )
                
                # 定义读取输出的函数
                def read_and_tee(pipe, file_obj, is_stderr=False):
                    """读取进程输出并同时显示和写入文件"""
                    try:
                        for line in iter(pipe.readline, ''):
                            if line:
                                # 显示到控制台
                                if is_stderr:
                                    print(line.rstrip(), file=sys.stderr, flush=True)
                                else:
                                    print(line.rstrip(), flush=True)
                                # 写入文件
                                file_obj.write(line)
                                file_obj.flush()
                    except Exception as e:
                        print_warning(f"读取输出时出错: {e}")
                    finally:
                        file_obj.close()
                
                # 启动输出读取线程
                stdout_thread = threading.Thread(
                    target=read_and_tee,
                    args=(process.stdout, log_f, False),
                    daemon=True
                )
                stderr_thread = threading.Thread(
                    target=read_and_tee,
                    args=(process.stderr, err_f, True),
                    daemon=True
                )
                stdout_thread.start()
                stderr_thread.start()
            else:
                process = subprocess.Popen([sys.executable, server_path])
            
            process.wait()
            if process.returncode == 0:
                print_success("服务器已正常退出")
            else:
                print_error(f"服务器异常退出，退出码: {process.returncode}")
                sys.exit(1)
        except KeyboardInterrupt:
            print()
            print_info("正在停止服务器...")
            if 'process' in locals():
                process.terminate()
                process.wait()
            print_success("服务器已正常退出")
        except Exception as e:
            print_error(f"服务器启动失败: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)

if __name__ == '__main__':
    main()

