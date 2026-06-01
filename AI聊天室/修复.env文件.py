#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""修复.env文件的编码和格式问题"""

from pathlib import Path

env_path = Path(__file__).parent / '.env'

if not env_path.exists():
    print("❌ .env文件不存在！")
    exit(1)

print(f"读取.env文件: {env_path}")

# 读取文件（自动处理BOM）
with open(env_path, 'r', encoding='utf-8-sig') as f:
    content = f.read()

print(f"\n原始内容:")
print(repr(content))

# 清理内容
lines = []
for line in content.split('\n'):
    line = line.strip()
    if line and not line.startswith('#'):
        # 确保格式正确
        if '=' in line:
            key, value = line.split('=', 1)
            lines.append(f"{key.strip()}={value.strip()}")
        else:
            lines.append(line)

# 重新写入（UTF-8无BOM）
new_content = '\n'.join(lines)
print(f"\n修复后内容:")
print(new_content)

with open(env_path, 'w', encoding='utf-8') as f:
    f.write(new_content)

print("\n✓ .env文件已修复！")
print("请重新运行: python 检查环境变量.py")
