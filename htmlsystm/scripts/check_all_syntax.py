#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全面检查所有Python文件的语法错误
"""
import os
import sys
import ast
from pathlib import Path

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def check_file(file_path):
    """检查单个文件"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            code = f.read()
        ast.parse(code, filename=file_path)
        return None
    except SyntaxError as e:
        return f"语法错误: 行 {e.lineno}, 列 {e.offset}: {e.msg}"
    except IndentationError as e:
        return f"缩进错误: 行 {e.lineno}, 列 {e.offset}: {e.msg}"
    except Exception as e:
        return f"错误: {type(e).__name__}: {str(e)}"

def main():
    """主函数"""
    print("=" * 80)
    print("Python语法全面检查")
    print("=" * 80)
    print()
    
    # 检查server目录
    server_dir = os.path.join(BASE_DIR, 'server')
    errors = []
    checked = 0
    
    if os.path.exists(server_dir):
        print(f"📁 检查目录: server/")
        for root, dirs, files in os.walk(server_dir):
            # 跳过__pycache__
            if '__pycache__' in root:
                continue
            
            for file in files:
                if file.endswith('.py'):
                    file_path = os.path.join(root, file)
                    rel_path = os.path.relpath(file_path, BASE_DIR)
                    error = check_file(file_path)
                    
                    if error:
                        errors.append((rel_path, error))
                        print(f"  ❌ {rel_path}")
                        print(f"     {error}")
                    else:
                        checked += 1
                        print(f"  ✅ {rel_path}")
    
    print()
    print("=" * 80)
    print(f"检查完成: 通过 {checked} 个文件, 发现 {len(errors)} 个错误")
    print("=" * 80)
    
    if errors:
        print("\n❌ 错误详情:")
        for file_path, error in errors:
            print(f"\n文件: {file_path}")
            print(f"  {error}")
        return 1
    else:
        print("\n✅ 所有文件语法检查通过！")
        return 0

if __name__ == '__main__':
    sys.exit(main())

