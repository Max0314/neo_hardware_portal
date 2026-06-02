#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""检查环境变量是否正确加载"""

import os
from pathlib import Path
from dotenv import load_dotenv

# 加载.env文件
env_path = Path(__file__).parent / '.env'
print(f"检查.env文件路径: {env_path}")
print(f".env文件是否存在: {env_path.exists()}")

if env_path.exists():
    print(f"\n.env文件内容:")
    with open(env_path, 'r', encoding='utf-8-sig') as f:  # 使用utf-8-sig自动去除BOM
        content = f.read()
        print(content)
        # 检查是否有BOM
        if content.startswith('\ufeff'):
            print("\n⚠️  检测到BOM标记，正在修复...")
            # 重新写入，去除BOM
            with open(env_path, 'w', encoding='utf-8') as fw:
                fw.write(content.lstrip('\ufeff'))
            print("✓ 已修复BOM问题")
else:
    print("\n❌ .env文件不存在！")
    print(f"请创建文件: {env_path}")

# 加载环境变量（尝试多种方式）
load_dotenv(dotenv_path=env_path, override=True)
# 也尝试从当前目录加载
load_dotenv(override=True)

# 检查环境变量
print("\n" + "="*50)
print("环境变量检查:")
print("="*50)

deepseek_key = os.getenv('DEEPSEEK_API_KEY')
print(f"DEEPSEEK_API_KEY: {'已设置' if deepseek_key else '❌ 未设置'}")
if deepseek_key:
    print(f"  值: {deepseek_key[:20]}...{deepseek_key[-10:]}")

openai_key = os.getenv('OPENAI_API_KEY')
print(f"OPENAI_API_KEY: {'已设置' if openai_key else '未设置'}")

anthropic_key = os.getenv('ANTHROPIC_API_KEY')
print(f"ANTHROPIC_API_KEY: {'已设置' if anthropic_key else '未设置'}")

google_key = os.getenv('GOOGLE_API_KEY')
print(f"GOOGLE_API_KEY: {'已设置' if google_key else '未设置'}")

print("\n" + "="*50)

