#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
使用 pyflakes 和 pylint 检查所有 Python 文件的语法和代码问题
"""
import os
import sys
import subprocess

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def check_with_pyflakes(file_path):
    """使用 pyflakes 检查文件"""
    try:
        result = subprocess.run(
            [sys.executable, '-m', 'pyflakes', file_path],
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.stdout + result.stderr
    except Exception as e:
        return f"pyflakes检查失败: {str(e)}"

def check_with_pylint(file_path):
    """使用 pylint 检查文件（仅错误和致命错误）"""
    try:
        result = subprocess.run(
            [sys.executable, '-m', 'pylint', '--errors-only', '--disable=all', '--enable=E,F', file_path],
            capture_output=True,
            text=True,
            timeout=60
        )
        return result.stdout + result.stderr
    except Exception as e:
        return f"pylint检查失败: {str(e)}"

def find_python_files(directory):
    """查找所有Python文件"""
    python_files = []
    for root, dirs, files in os.walk(directory):
        if '__pycache__' in root:
            continue
        for file in files:
            if file.endswith('.py'):
                python_files.append(os.path.join(root, file))
    return python_files

def main():
    """主函数"""
    print("=" * 80)
    print("使用 pyflakes 和 pylint 检查 Python 代码")
    print("=" * 80)
    print()
    
    server_dir = os.path.join(BASE_DIR, 'server')
    if not os.path.exists(server_dir):
        print(f"❌ 目录不存在: {server_dir}")
        return 1
    
    python_files = find_python_files(server_dir)
    python_files.sort()
    
    print(f"找到 {len(python_files)} 个Python文件")
    print()
    
    all_errors = []
    
    for file_path in python_files:
        rel_path = os.path.relpath(file_path, BASE_DIR)
        print(f"检查: {rel_path}")
        
        # 使用 pyflakes 检查
        pyflakes_output = check_with_pyflakes(file_path)
        if pyflakes_output.strip():
            print(f"  ⚠️  pyflakes 发现问题:")
            for line in pyflakes_output.strip().split('\n'):
                if line.strip():
                    print(f"     {line}")
                    all_errors.append((rel_path, 'pyflakes', line))
        
        # 使用 pylint 检查
        pylint_output = check_with_pylint(file_path)
        if pylint_output.strip() and 'No config file found' not in pylint_output:
            # 过滤掉配置相关的消息
            relevant_lines = [line for line in pylint_output.strip().split('\n') 
                             if line.strip() and 'No config file' not in line 
                             and 'Using config file' not in line
                             and 'module' not in line.lower() or 'error' in line.lower()]
            if relevant_lines:
                print(f"  ⚠️  pylint 发现问题:")
                for line in relevant_lines:
                    if line.strip():
                        print(f"     {line}")
                        all_errors.append((rel_path, 'pylint', line))
        
        if not pyflakes_output.strip() and (not pylint_output.strip() or 'No config file' in pylint_output):
            print(f"  ✅ 通过检查")
        print()
    
    print("=" * 80)
    print(f"检查完成: 发现 {len(all_errors)} 个问题")
    print("=" * 80)
    
    if all_errors:
        print("\n详细问题列表:")
        for file_path, tool, error in all_errors:
            print(f"\n文件: {file_path}")
            print(f"工具: {tool}")
            print(f"错误: {error}")
        return 1
    else:
        print("\n✅ 所有文件通过 pyflakes 和 pylint 检查！")
        return 0

if __name__ == '__main__':
    sys.exit(main())

