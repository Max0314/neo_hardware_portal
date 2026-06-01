#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
代码缩进自动修复工具

功能：
1. 检查Python文件的语法错误
2. 自动修复常见的缩进问题
3. 统一使用空格缩进（4个空格）
4. 修复try-except块的缩进对齐问题

使用方法：
    python3 scripts/fix_indentation.py server/main.py
    python3 scripts/fix_indentation.py server/main.py --backup  # 创建备份
"""

import ast
import sys
import re
import argparse
import shutil
from pathlib import Path
from typing import List, Tuple, Optional


class IndentationFixer:
    """缩进修复器"""
    
    def __init__(self, use_spaces=True, indent_size=4):
        self.use_spaces = use_spaces
        self.indent_size = indent_size
        self.indent_char = ' ' * indent_size if use_spaces else '\t'
    
    def fix_file(self, filepath: str, backup: bool = False) -> Tuple[bool, List[str]]:
        """修复文件的缩进问题"""
        filepath = Path(filepath)
        if not filepath.exists():
            print(f"❌ 文件不存在: {filepath}")
            return False, []
        
        # 创建备份
        if backup:
            backup_path = filepath.with_suffix(filepath.suffix + '.bak')
            shutil.copy2(filepath, backup_path)
            print(f"📦 已创建备份: {backup_path}")
        
        # 读取文件
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        except Exception as e:
            print(f"❌ 读取文件失败: {e}")
            return False, []
        
        # 修复缩进
        fixed_lines, fixes = self._fix_lines(lines)
        
        # 检查修复后的语法
        fixed_code = ''.join(fixed_lines)
        try:
            ast.parse(fixed_code)
            print("✅ 修复后语法检查通过")
        except SyntaxError as e:
            print(f"⚠️  修复后仍有语法错误 (行 {e.lineno}): {e.msg}")
            print(f"   可能需要手动检查")
        
        # 写入文件
        if fixes:
            try:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.writelines(fixed_lines)
                print(f"✅ 已修复 {len(fixes)} 处缩进问题")
                for fix in fixes[:10]:  # 只显示前10个
                    print(f"   {fix}")
                if len(fixes) > 10:
                    print(f"   ... 还有 {len(fixes) - 10} 处修复")
                return True, fixes
            except Exception as e:
                print(f"❌ 写入文件失败: {e}")
                return False, fixes
        else:
            print("ℹ️  未发现需要修复的缩进问题")
            return True, []
    
    def _fix_lines(self, lines: List[str]) -> Tuple[List[str], List[str]]:
        """修复行的缩进"""
        fixed_lines = []
        fixes = []
        
        # 跟踪try-except块
        try_stack = []  # [(line_num, expected_indent)]
        
        for i, line in enumerate(lines):
            original_line = line
            stripped = line.lstrip()
            
            # 跳过空行和注释
            if not stripped or stripped.startswith('#'):
                fixed_lines.append(line)
                continue
            
            # 计算当前缩进
            current_indent = len(line) - len(stripped)
            
            # 检查try语句
            if stripped.startswith('try:'):
                # 记录try的缩进
                try_stack.append((i + 1, current_indent))
                fixed_lines.append(line)
                continue
            
            # 检查except/finally语句
            if stripped.startswith('except') or stripped.startswith('finally:'):
                if try_stack:
                    # 获取对应的try的缩进
                    _, expected_indent = try_stack[-1]
                    if current_indent != expected_indent:
                        # 修复缩进
                        fixed_indent = ' ' * expected_indent
                        fixed_line = fixed_indent + stripped + '\n'
                        fixed_lines.append(fixed_line)
                        fixes.append(f"第 {i+1} 行: except/finally 缩进修复 ({current_indent} -> {expected_indent})")
                        try_stack.pop()
                        continue
                    else:
                        try_stack.pop()
                else:
                    # 没有对应的try，可能是语法错误
                    print(f"⚠️  第 {i+1} 行: except/finally 没有对应的 try")
                fixed_lines.append(line)
                continue
            
            # 检查其他常见的缩进问题
            # 1. 检查是否使用了制表符
            if '\t' in line:
                # 将制表符转换为空格
                fixed_line = line.expandtabs(self.indent_size)
                if fixed_line != line:
                    fixed_lines.append(fixed_line)
                    fixes.append(f"第 {i+1} 行: 制表符转换为空格")
                    continue
            
            # 2. 检查缩进是否一致（应该是4的倍数）
            if current_indent > 0 and current_indent % self.indent_size != 0:
                # 四舍五入到最近的4的倍数
                fixed_indent = ' ' * ((current_indent + self.indent_size // 2) // self.indent_size * self.indent_size)
                fixed_line = fixed_indent + stripped + '\n'
                if fixed_line != line:
                    fixed_lines.append(fixed_line)
                    fixes.append(f"第 {i+1} 行: 缩进对齐修复 ({current_indent} -> {len(fixed_indent)})")
                    continue
            
            fixed_lines.append(line)
        
        # 检查未闭合的try块
        if try_stack:
            for line_num, _ in try_stack:
                print(f"⚠️  第 {line_num} 行: try 块没有对应的 except/finally")
        
        return fixed_lines, fixes


def main():
    parser = argparse.ArgumentParser(description='Python代码缩进自动修复工具')
    parser.add_argument('file', help='要修复的Python文件路径')
    parser.add_argument('--backup', '-b', action='store_true', help='创建备份文件')
    parser.add_argument('--indent', '-i', type=int, default=4, help='缩进大小（默认4）')
    parser.add_argument('--check-only', '-c', action='store_true', help='仅检查，不修复')
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("Python代码缩进修复工具")
    print("=" * 60)
    print(f"文件: {args.file}")
    print(f"缩进大小: {args.indent} 空格")
    print("=" * 60)
    
    # 先检查语法
    print("\n📋 检查语法...")
    try:
        with open(args.file, 'r', encoding='utf-8') as f:
            code = f.read()
        ast.parse(code)
        print("✅ 语法检查通过")
    except SyntaxError as e:
        print(f"❌ 语法错误 (行 {e.lineno}): {e.msg}")
        if e.text:
            print(f"   代码: {e.text.rstrip()}")
        if args.check_only:
            sys.exit(1)
        print("   将尝试修复...")
    except Exception as e:
        print(f"❌ 检查失败: {e}")
        sys.exit(1)
    
    if args.check_only:
        print("\n✅ 仅检查模式，未进行修复")
        sys.exit(0)
    
    # 修复缩进
    print("\n🔧 修复缩进...")
    fixer = IndentationFixer(indent_size=args.indent)
    success, fixes = fixer.fix_file(args.file, backup=args.backup)
    
    if success:
        print("\n✅ 修复完成")
        sys.exit(0)
    else:
        print("\n❌ 修复失败")
        sys.exit(1)


if __name__ == '__main__':
    main()

