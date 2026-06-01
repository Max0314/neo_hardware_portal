#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
检查MySQL数据存储位置
"""
import os
import sys

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.config import MYSQL_CONFIG
from server.mysql_connection_pool import get_connection_pool

def check_mysql_data_location():
    """检查MySQL数据存储位置"""
    try:
        pool = get_connection_pool()
        
        with pool.get_cursor() as cursor:
            # 获取MySQL数据目录
            cursor.execute("SHOW VARIABLES LIKE 'datadir'")
            result = cursor.fetchone()
            datadir = result[1] if result else None
            
            # 获取数据库名称
            database = MYSQL_CONFIG['database']
            
            print("=" * 60)
            print("MySQL数据存储位置信息")
            print("=" * 60)
            print(f"\n📁 MySQL数据目录: {datadir}")
            print(f"📊 数据库名称: {database}")
            
            if datadir:
                db_path = os.path.join(datadir, database)
                print(f"📂 数据库文件路径: {db_path}")
                print(f"\n💡 说明:")
                print(f"   - MySQL的所有数据文件存储在: {datadir}")
                print(f"   - 数据库 '{database}' 的文件在: {db_path}")
                print(f"   - 表数据文件格式: {database}/表名.ibd (InnoDB)")
                print(f"   - 表结构文件: {database}/表名.frm")
            
            # 获取所有表
            cursor.execute(f"SHOW TABLES FROM {database}")
            tables = cursor.fetchall()
            
            print(f"\n📋 数据库 '{database}' 中的表:")
            for table in tables:
                table_name = table[0] if isinstance(table, (list, tuple)) else table
                # 获取表大小
                cursor.execute(f"""
                    SELECT 
                        ROUND(SUM(data_length + index_length) / 1024 / 1024, 2) AS size_mb
                    FROM information_schema.tables 
                    WHERE table_schema = %s AND table_name = %s
                """, (database, table_name))
                size_result = cursor.fetchone()
                size_mb = size_result[0] if size_result and size_result[0] else 0
                
                # 获取记录数
                cursor.execute(f"SELECT COUNT(*) FROM `{table_name}`")
                count_result = cursor.fetchone()
                count = count_result[0] if count_result else 0
                
                print(f"   - {table_name}: {count} 条记录, {size_mb} MB")
            
            print("\n" + "=" * 60)
            return True
            
    except Exception as e:
        print(f"❌ 检查失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    check_mysql_data_location()

