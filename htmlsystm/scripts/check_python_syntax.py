#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Python语法检查器 - 检查所有Python文件的语法错误和缩进问题
"""
import os
import sys
import ast
import traceback
from pathlib import Path

# 添加项目根目录到路径
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

# 需要检查的目录
CHECK_DIRS = [
    'server',
    'scripts',
]

# 需要排除的目录
EXCLUDE_DIRS = {
    '__pycache__',
    '.git',
    'venv',
    'env',
    'node_modules',
    'sdk',  # SDK文件可能包含自动生成的代码
}

# 需要排除的文件模式
EXCLUDE_PATTERNS = {
    'setup.py',  # 通常包含动态代码
}

def check_file_syntax(file_path):
    """检查单个Python文件的语法"""
    errors = []
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            code = f.read()
        
        # 使用AST解析检查语法
        try:
            ast.parse(code, filename=file_path)
        except SyntaxError as e:
            errors.append({
                'file': file_path,
                'line': e.lineno,
                'column': e.offset,
                'message': e.msg,
                'text': e.text,
                'type': 'SyntaxError'
            })
        except IndentationError as e:
            errors.append({
                'file': file_path,
                'line': e.lineno,
                'column': e.offset,
                'message': e.msg,
                'text': e.text,
                'type': 'IndentationError'
            })
        except Exception as e:
            errors.append({
                'file': file_path,
                'line': None,
                'column': None,
                'message': str(e),
                'text': None,
                'type': type(e).__name__
            })
    except Exception as e:
        errors.append({
            'file': file_path,
            'line': None,
            'column': None,
            'message': f'无法读取文件: {str(e)}',
            'text': None,
            'type': 'FileError'
        })
    
    return errors

def find_python_files(base_dir):
    """查找所有Python文件"""
    python_files = []
    base_path = Path(base_dir)
    
    for root, dirs, files in os.walk(base_dir):
        # 排除不需要的目录
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        
        for file in files:
            if file.endswith('.py'):
                file_path = os.path.join(root, file)
                # 排除不需要的文件
                if file not in EXCLUDE_PATTERNS:
                    python_files.append(file_path)
    
    return python_files

def main():
    """主函数"""
    print("=" * 80)
    print("Python语法检查器")
    print("=" * 80)
    print()
    
    all_errors = []
    total_files = 0
    checked_files = 0
    
    # 检查每个目录
    for check_dir in CHECK_DIRS:
        dir_path = os.path.join(BASE_DIR, check_dir)
        if not os.path.exists(dir_path):
            print(f"⚠️  目录不存在: {dir_path}")
            continue
        
        print(f"📁 检查目录: {check_dir}/")
        python_files = find_python_files(dir_path)
        total_files += len(python_files)
        
        for file_path in python_files:
            rel_path = os.path.relpath(file_path, BASE_DIR)
            errors = check_file_syntax(file_path)
            
            if errors:
                all_errors.extend(errors)
                print(f"  ❌ {rel_path}")
                for error in errors:
                    if error['line']:
                        print(f"     行 {error['line']}: {error['type']} - {error['message']}")
                        if error['text']:
                            print(f"     代码: {error['text'].strip()}")
                    else:
                        print(f"     {error['type']} - {error['message']}")
            else:
                checked_files += 1
                print(f"  ✅ {rel_path}")
    
    print()
    print("=" * 80)
    print("检查结果汇总")
    print("=" * 80)
    print(f"总文件数: {total_files}")
    print(f"通过检查: {checked_files}")
    print(f"发现错误: {len(all_errors)}")
    print()
    
    if all_errors:
        print("❌ 发现以下语法错误:")
        print()
        for error in all_errors:
            rel_path = os.path.relpath(error['file'], BASE_DIR)
            print(f"文件: {rel_path}")
            if error['line']:
                print(f"  行 {error['line']}, 列 {error['column']}: {error['type']}")
                print(f"  错误: {error['message']}")
                if error['text']:
                    print(f"  代码: {error['text'].strip()}")
            else:
                print(f"  {error['type']}: {error['message']}")
            print()
        
        return 1
    else:
        print("✅ 所有文件语法检查通过！")
        return 0

if __name__ == '__main__':
    sys.exit(main())

