#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
完整的代码检查脚本 - 使用 pyflakes 和 pylint
"""
import os
import sys
import subprocess

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def check_file_with_tools(file_path):
    """使用多种工具检查文件"""
    errors = []
    rel_path = os.path.relpath(file_path, BASE_DIR)
    
    # 1. 使用 Python 编译检查
    try:
        result = subprocess.run(
            [sys.executable, '-m', 'py_compile', file_path],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode != 0:
            errors.append(('py_compile', result.stderr))
    except Exception as e:
        errors.append(('py_compile', f"检查失败: {str(e)}"))
    
    # 2. 使用 pyflakes 检查
    try:
        result = subprocess.run(
            [sys.executable, '-m', 'pyflakes', file_path],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.stdout.strip() or result.stderr.strip():
            output = result.stdout + result.stderr
            if output.strip():
                errors.append(('pyflakes', output))
    except FileNotFoundError:
        pass  # pyflakes 未安装
    except Exception as e:
        errors.append(('pyflakes', f"检查失败: {str(e)}"))
    
    # 3. 使用 pylint 检查（仅错误）
    try:
        result = subprocess.run(
            [sys.executable, '-m', 'pylint', '--errors-only', '--disable=all', '--enable=E,F', file_path],
            capture_output=True,
            text=True,
            timeout=60
        )
        output = result.stdout + result.stderr
        # 过滤掉配置相关的消息
        relevant_lines = [line for line in output.split('\n') 
                         if line.strip() 
                         and 'No config file' not in line 
                         and 'Using config file' not in line
                         and ('error' in line.lower() or 'E' in line or 'F' in line)]
        if relevant_lines:
            errors.append(('pylint', '\n'.join(relevant_lines)))
    except FileNotFoundError:
        pass  # pylint 未安装
    except Exception as e:
        errors.append(('pylint', f"检查失败: {str(e)}"))
    
    return errors

def main():
    """主函数"""
    print("=" * 80)
    print("完整代码检查 - 使用 py_compile, pyflakes, pylint")
    print("=" * 80)
    print()
    
    server_dir = os.path.join(BASE_DIR, 'server')
    if not os.path.exists(server_dir):
        print(f"❌ 目录不存在: {server_dir}")
        return 1
    
    # 检查关键文件
    key_files = [
        'server/main.py',
        'server/user_manager.py',
        'server/wsgi_app.py',
        'server/announcement_manager.py',
        'server/data_preloader.py',
        'server/config.py',
    ]
    
    all_errors = []
    checked = 0
    
    for file_name in key_files:
        file_path = os.path.join(BASE_DIR, file_name)
        if not os.path.exists(file_path):
            print(f"⚠️  文件不存在: {file_name}")
            continue
        
        print(f"检查: {file_name}")
        errors = check_file_with_tools(file_path)
        
        if errors:
            all_errors.append((file_name, errors))
            print(f"  ❌ 发现 {len(errors)} 个问题:")
            for tool, error in errors:
                print(f"     [{tool}] {error[:100]}")
        else:
            checked += 1
            print(f"  ✅ 通过检查")
        print()
    
    print("=" * 80)
    print(f"检查完成: 通过 {checked} 个文件, 发现 {len(all_errors)} 个文件有问题")
    print("=" * 80)
    
    if all_errors:
        print("\n❌ 详细错误列表:")
        for file_name, errors in all_errors:
            print(f"\n文件: {file_name}")
            for tool, error in errors:
                print(f"  [{tool}]")
                for line in error.split('\n')[:10]:  # 只显示前10行
                    if line.strip():
                        print(f"    {line}")
        return 1
    else:
        print("\n✅ 所有文件通过检查！")
        return 0

if __name__ == '__main__':
    sys.exit(main())

