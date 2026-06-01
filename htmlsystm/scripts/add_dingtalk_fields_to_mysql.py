#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
为MySQL users表添加钉钉用户字段
方案：添加一个JSON字段存储所有钉钉用户额外信息
"""
import os
import sys
import json

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

# 加载MySQL环境变量（从.mysql.env文件）- 必须在导入server模块之前
mysql_env_file = os.path.join(project_root, '.mysql.env')
if os.path.exists(mysql_env_file):
    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=mysql_env_file, override=True)
        print(f"✅ 已从 {mysql_env_file} 加载MySQL环境变量")
    except ImportError:
        # 如果没有dotenv，手动解析.env文件
        with open(mysql_env_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    # 处理 export KEY='VALUE' 格式
                    if line.startswith('export '):
                        line = line[7:]  # 移除 'export '
                    if '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip().strip("'\"")
                        os.environ[key] = value
        print(f"✅ 已从 {mysql_env_file} 加载MySQL环境变量（手动解析）")
elif not os.environ.get('MYSQL_PASSWORD'):
    print(f"⚠️  警告: 未找到 {mysql_env_file} 文件，且 MYSQL_PASSWORD 环境变量未设置")
    print("   请先运行 fix_mysql_password.sh 或设置 MYSQL_PASSWORD 环境变量")

from server.config import MYSQL_CONFIG
from server.mysql_connection_pool import get_mysql_connection_pool

def add_dingtalk_fields():
    """为users表添加dingtalk_data JSON字段"""
    try:
        pool = get_mysql_connection_pool()
        
        with pool.get_cursor() as cursor:
            # 检查字段是否已存在
            cursor.execute("""
                SELECT COLUMN_NAME 
                FROM INFORMATION_SCHEMA.COLUMNS 
                WHERE TABLE_SCHEMA = %s 
                AND TABLE_NAME = 'users' 
                AND COLUMN_NAME = 'dingtalk_data'
            """, (MYSQL_CONFIG['database'],))
            
            if cursor.fetchone():
                print("✅ dingtalk_data字段已存在，跳过添加")
                return True
            
            # 添加dingtalk_data JSON字段
            cursor.execute("""
                ALTER TABLE users 
                ADD COLUMN dingtalk_data JSON NULL 
                COMMENT '钉钉用户完整数据（JSON格式）'
                AFTER last_login_time
            """)
            
            print("✅ 成功添加dingtalk_data字段到users表")
            return True
            
    except Exception as e:
        print(f"❌ 添加字段失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    print("=" * 60)
    print("为MySQL users表添加钉钉用户字段")
    print("=" * 60)
    
    if add_dingtalk_fields():
        print("\n✅ 完成！")
        print("\n说明：")
        print("- dingtalk_data字段用于存储所有钉钉用户额外信息（JSON格式）")
        print("- 包括：unionid, login_id, nickname, avatar, dept_id, dept_id_list等")
        print("- Excel仍然是主要数据源，MySQL的dingtalk_data字段作为补充")
    else:
        print("\n❌ 失败！请检查错误信息")
        sys.exit(1)

