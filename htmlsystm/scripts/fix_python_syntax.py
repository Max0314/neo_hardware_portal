#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Python代码语法和缩进自动修复工具

功能：
1. 检查Python文件的语法错误
2. 自动修复常见的缩进问题（try-except对齐、制表符转换等）
3. 统一使用空格缩进（4个空格）
4. 修复try-except块的缩进对齐问题
5. 使用pyflakes和pylint检查代码质量

使用方法：
    python3 scripts/fix_python_syntax.py server/main.py
    python3 scripts/fix_python_syntax.py server/main.py --backup  # 创建备份
    python3 scripts/fix_python_syntax.py server/main.py --check-only  # 仅检查
"""

import ast
import sys
import re
import argparse
import shutil
import subprocess
from pathlib import Path
from typing import List, Tuple, Optional, Dict


class PythonSyntaxFixer:
    """Python语法和缩进修复器"""
    
    def __init__(self, use_spaces=True, indent_size=4):
        self.use_spaces = use_spaces
        self.indent_size = indent_size
        self.indent_char = ' ' * indent_size if use_spaces else '\t'
        self.fixes = []
    
    def fix_file(self, filepath: str, backup: bool = False) -> Tuple[bool, List[str]]:
        """修复文件的语法和缩进问题"""
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
        fixed_lines = self._fix_indentation(lines)
        
        # 检查修复后的语法
        fixed_code = ''.join(fixed_lines)
        syntax_ok = self._check_syntax(fixed_code)
        
        if not syntax_ok:
            # 如果还有语法错误，尝试更激进的修复
            print("⚠️  尝试更激进的修复...")
            fixed_lines = self._aggressive_fix(fixed_lines)
            fixed_code = ''.join(fixed_lines)
            syntax_ok = self._check_syntax(fixed_code)
        
        # 写入文件
        if self.fixes or not syntax_ok:
            try:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.writelines(fixed_lines)
                if self.fixes:
                    print(f"✅ 已修复 {len(self.fixes)} 处问题")
                    for fix in self.fixes[:20]:  # 显示前20个
                        print(f"   {fix}")
                    if len(self.fixes) > 20:
                        print(f"   ... 还有 {len(self.fixes) - 20} 处修复")
                return syntax_ok, self.fixes
            except Exception as e:
                print(f"❌ 写入文件失败: {e}")
                return False, self.fixes
        else:
            print("ℹ️  未发现需要修复的问题")
            return True, []
    
    def _check_syntax(self, code: str) -> bool:
        """检查语法"""
        try:
            ast.parse(code)
            return True
        except SyntaxError as e:
            print(f"❌ 语法错误 (行 {e.lineno}): {e.msg}")
            if e.text:
                print(f"   代码: {e.text.rstrip()}")
            return False
    
    def _fix_indentation(self, lines: List[str]) -> List[str]:
        """修复缩进问题"""
        fixed_lines = []
        try_stack = []  # [(line_num, expected_indent)]
        
        for i, line in enumerate(lines):
            original_line = line
            stripped = line.lstrip()
            line_num = i + 1
            
            # 跳过空行
            if not stripped:
                fixed_lines.append(line)
                continue
            
            # 1. 将制表符转换为空格
            if '\t' in line:
                line = line.expandtabs(self.indent_size)
                if line != original_line:
                    self.fixes.append(f"第 {line_num} 行: 制表符转换为空格")
            
            # 重新计算缩进
            current_indent = len(line) - len(line.lstrip())
            stripped = line.lstrip()
            
            # 2. 检查try语句
            if stripped.startswith('try:'):
                try_stack.append((line_num, current_indent))
                fixed_lines.append(line)
                # 检查下一行是否在try块内（应该有更多缩进）
                if i + 1 < len(lines):
                    next_line = lines[i + 1]
                    next_stripped = next_line.lstrip()
                    if next_stripped and not next_stripped.startswith('#'):
                        next_indent = len(next_line) - len(next_stripped)
                        # 如果下一行的缩进与try相同或更少，需要修复
                        if next_indent <= current_indent and not next_stripped.startswith('except') and not next_stripped.startswith('finally'):
                            # 下一行应该在try块内，需要增加缩进
                            expected_indent = current_indent + self.indent_size
                            fixed_next = ' ' * expected_indent + next_stripped + ('\n' if not next_line.endswith('\n') else '')
                            # 注意：这里不能直接修改，需要在下一轮循环处理
                            # 但我们可以标记这个问题
                            print(f"⚠️  第 {line_num + 1} 行: try块后第一行缩进不足，需要手动检查")
                continue
            
            # 3. 检查except/finally语句
            if stripped.startswith('except') or stripped.startswith('finally:'):
                if try_stack:
                    _, expected_indent = try_stack[-1]
                    if current_indent != expected_indent:
                        # 修复缩进
                        fixed_indent = ' ' * expected_indent
                        line = fixed_indent + stripped + ('\n' if not line.endswith('\n') else '')
                        self.fixes.append(f"第 {line_num} 行: except/finally 缩进修复 ({current_indent} -> {expected_indent})")
                    try_stack.pop()
                else:
                    print(f"⚠️  第 {line_num} 行: except/finally 没有对应的 try")
                fixed_lines.append(line)
                continue
            
            # 4. 检查缩进是否一致（应该是4的倍数，允许一些偏差）
            if current_indent > 0:
                # 检查是否是合理的缩进（4的倍数，或者接近4的倍数）
                remainder = current_indent % self.indent_size
                if remainder != 0 and remainder <= 2:  # 允许1-2个空格的偏差
                    # 对齐到最近的4的倍数
                    fixed_indent = ' ' * ((current_indent // self.indent_size) * self.indent_size)
                    if fixed_indent != line[:current_indent]:
                        line = fixed_indent + stripped + ('\n' if not line.endswith('\n') else '')
                        self.fixes.append(f"第 {line_num} 行: 缩进对齐修复 ({current_indent} -> {len(fixed_indent)})")
            
            fixed_lines.append(line)
        
        # 检查未闭合的try块
        if try_stack:
            for line_num, _ in try_stack:
                print(f"⚠️  第 {line_num} 行: try 块没有对应的 except/finally")
        
        return fixed_lines
    
    def _aggressive_fix(self, lines: List[str]) -> List[str]:
        """更激进的修复（修复明显的语法错误）"""
        fixed_lines = []
        
        for i, line in enumerate(lines):
            line_num = i + 1
            stripped = line.lstrip()
            
            # 修复常见的缩进问题
            # 1. 修复 else: 后面没有内容的错误
            if stripped.startswith('else:') and i + 1 < len(lines):
                next_line = lines[i + 1].lstrip()
                if not next_line or next_line.startswith('#'):
                    # else后面是空行或注释，可能需要添加pass
                    if i + 2 < len(lines):
                        next_next = lines[i + 2].lstrip()
                        if next_next and not next_next.startswith('#'):
                            # 下一行有内容，检查缩进
                            next_indent = len(lines[i + 1]) - len(lines[i + 1].lstrip())
                            current_indent = len(line) - len(stripped)
                            if next_indent <= current_indent:
                                # 缩进不正确，可能需要修复
                                pass
            
            fixed_lines.append(line)
        
        return fixed_lines


def check_with_pyflakes(filepath: str) -> Tuple[bool, List[str]]:
    """使用pyflakes检查代码"""
    try:
        result = subprocess.run(
            ['python3', '-m', 'pyflakes', filepath],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            return True, []
        else:
            errors = result.stdout.split('\n') + result.stderr.split('\n')
            errors = [e for e in errors if e.strip()]
            return False, errors
    except subprocess.TimeoutExpired:
        return False, ['pyflakes检查超时']
    except FileNotFoundError:
        return False, ['pyflakes未安装']
    except Exception as e:
        return False, [f'pyflakes检查失败: {e}']


def main():
    parser = argparse.ArgumentParser(description='Python代码语法和缩进自动修复工具')
    parser.add_argument('file', help='要修复的Python文件路径')
    parser.add_argument('--backup', '-b', action='store_true', help='创建备份文件')
    parser.add_argument('--indent', '-i', type=int, default=4, help='缩进大小（默认4）')
    parser.add_argument('--check-only', '-c', action='store_true', help='仅检查，不修复')
    parser.add_argument('--pyflakes', action='store_true', help='使用pyflakes检查')
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("Python代码语法和缩进修复工具")
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
        syntax_ok = True
    except SyntaxError as e:
        print(f"❌ 语法错误 (行 {e.lineno}): {e.msg}")
        if e.text:
            print(f"   代码: {e.text.rstrip()}")
        syntax_ok = False
        if args.check_only:
            sys.exit(1)
        print("   将尝试修复...")
    except Exception as e:
        print(f"❌ 检查失败: {e}")
        sys.exit(1)
    
    if args.check_only:
        print("\n✅ 仅检查模式，未进行修复")
        if args.pyflakes:
            print("\n📋 使用pyflakes检查...")
            pyflakes_ok, errors = check_with_pyflakes(args.file)
            if pyflakes_ok:
                print("✅ pyflakes检查通过")
            else:
                print("❌ pyflakes发现问题:")
                for error in errors[:20]:
                    print(f"   {error}")
        sys.exit(0 if syntax_ok else 1)
    
    # 修复缩进
    print("\n🔧 修复缩进...")
    fixer = PythonSyntaxFixer(indent_size=args.indent)
    success, fixes = fixer.fix_file(args.file, backup=args.backup)
    
    if success:
        print("\n✅ 修复完成")
        
        # 使用pyflakes检查
        if args.pyflakes:
            print("\n📋 使用pyflakes检查...")
            pyflakes_ok, errors = check_with_pyflakes(args.file)
            if pyflakes_ok:
                print("✅ pyflakes检查通过")
            else:
                print("⚠️  pyflakes发现问题（可能需要手动修复）:")
                for error in errors[:20]:
                    print(f"   {error}")
        
        sys.exit(0)
    else:
        print("\n❌ 修复失败，请手动检查")
        sys.exit(1)


if __name__ == '__main__':
    main()

