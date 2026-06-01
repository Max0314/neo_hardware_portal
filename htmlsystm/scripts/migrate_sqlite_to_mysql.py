#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SQLite到MySQL数据迁移脚本
将SQLite数据库中的所有数据迁移到MySQL数据库
"""
import os
import sys
import sqlite3
import json
from datetime import datetime

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

try:
    from server.config import DB_PATH, MYSQL_CONFIG
    from server.mysql_connection_pool import get_mysql_connection_pool
except ImportError as e:
    print(f"导入配置失败: {e}")
    print("请确保已配置MySQL连接信息")
    sys.exit(1)


def convert_timestamp(value):
    """转换时间戳格式"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        try:
            # 尝试解析ISO格式时间
            dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
            return dt.timestamp()
        except:
            return value
    return value


def migrate_table(sqlite_conn, mysql_pool, table_name, table_config):
    """
    迁移单个表的数据
    
    Args:
        sqlite_conn: SQLite连接
        mysql_pool: MySQL连接池
        table_name: 表名
        table_config: 表配置（包含字段映射和转换函数）
    """
    print(f"\n{'='*60}")
    print(f"迁移表: {table_name}")
    print(f"{'='*60}")
    
    sqlite_cursor = sqlite_conn.cursor()
    
    try:
        # 从SQLite读取数据
        sqlite_cursor.execute(f"SELECT * FROM {table_name}")
        rows = sqlite_cursor.fetchall()
        
        if not rows:
            print(f"  表 {table_name} 为空，跳过")
            return
        
        print(f"  找到 {len(rows)} 条记录")
        
        # 获取列名
        sqlite_columns = [description[0] for description in sqlite_cursor.description]
        
        # 字段映射（SQLite字段名 -> MySQL字段名）
        column_mapping = table_config.get('column_mapping', {})
        # 获取MySQL表的实际字段（排除SQLite有但MySQL没有的字段）
        excluded_columns = table_config.get('excluded_columns', [])
        
        # 构建MySQL字段列表
        mysql_columns = []
        sqlite_to_mysql_map = {}  # 用于值映射
        for sqlite_col in sqlite_columns:
            if sqlite_col in excluded_columns:
                continue  # 跳过MySQL表中不存在的字段
            mysql_col = column_mapping.get(sqlite_col, sqlite_col)
            mysql_columns.append(mysql_col)
            sqlite_to_mysql_map[sqlite_col] = mysql_col
        
        # 处理特殊字段（如sessions表的user_data）
        special_fields = table_config.get('special_fields', {})
        for mysql_col, default_value in special_fields.items():
            if mysql_col not in mysql_columns:
                mysql_columns.append(mysql_col)
        
        # 准备MySQL插入语句
        placeholders = ', '.join(['%s'] * len(mysql_columns))
        columns_str = ', '.join(mysql_columns)
        insert_sql = f"INSERT IGNORE INTO {table_name} ({columns_str}) VALUES ({placeholders})"
        
        # 批量插入到MySQL
        mysql_pool = get_mysql_connection_pool()
        batch_size = 100
        inserted_count = 0
        
        with mysql_pool.get_cursor() as mysql_cursor:
            for i in range(0, len(rows), batch_size):
                batch = rows[i:i+batch_size]
                values_list = []
                
                for row in batch:
                    values = []
                    # 按MySQL字段顺序构建值
                    for mysql_col in mysql_columns:
                        # 查找对应的SQLite字段
                        sqlite_col = None
                        for sk, mv in sqlite_to_mysql_map.items():
                            if mv == mysql_col:
                                sqlite_col = sk
                                break
                        
                        if sqlite_col and sqlite_col in sqlite_columns:
                            # 从SQLite行中获取值
                            val = row[sqlite_columns.index(sqlite_col)]
                            # 应用字段转换
                            if sqlite_col in table_config.get('converters', {}):
                                val = table_config['converters'][sqlite_col](val)
                        elif mysql_col in special_fields:
                            # 使用特殊字段的默认值
                            val = special_fields[mysql_col]
                        else:
                            val = None
                        values.append(val)
                    values_list.append(tuple(values))
                
                try:
                    mysql_cursor.executemany(insert_sql, values_list)
                    inserted_count += len(values_list)
                    print(f"  已插入 {inserted_count}/{len(rows)} 条记录", end='\r')
                except Exception as e:
                    print(f"\n  插入失败: {e}")
                    # 尝试逐条插入，找出问题记录
                    for values in values_list:
                        try:
                            mysql_cursor.execute(insert_sql, values)
                            inserted_count += 1
                        except Exception as e2:
                            print(f"  跳过问题记录: {e2}")
                            print(f"  数据: {values}")
        
        print(f"\n  ✅ 完成: 成功插入 {inserted_count} 条记录")
        
    except sqlite3.Error as e:
        print(f"  ❌ SQLite读取失败: {e}")
    except Exception as e:
        print(f"  ❌ 迁移失败: {e}")
        import traceback
        traceback.print_exc()


def verify_data(sqlite_conn, mysql_pool):
    """验证数据一致性"""
    print(f"\n{'='*60}")
    print("验证数据一致性")
    print(f"{'='*60}")
    
    tables = [
        'users',
        'sessions',
        'audit_logs',
        'primary_boards',
        'sub_boards',
        'system_config'
    ]
    
    sqlite_cursor = sqlite_conn.cursor()
    mysql_pool = get_mysql_connection_pool()
    
    for table in tables:
        try:
            # SQLite计数
            sqlite_cursor.execute(f"SELECT COUNT(*) FROM {table}")
            sqlite_count = sqlite_cursor.fetchone()[0]
            
            # MySQL计数
            with mysql_pool.get_cursor() as mysql_cursor:
                mysql_cursor.execute(f"SELECT COUNT(*) as cnt FROM {table}")
                result = mysql_cursor.fetchone()
                # 处理不同的返回格式（dict或tuple）
                if isinstance(result, dict):
                    mysql_count = result.get('cnt') or result.get('COUNT(*)', 0)
                elif isinstance(result, (list, tuple)):
                    mysql_count = result[0] if result else 0
                else:
                    mysql_count = 0
            
            status = "✅" if sqlite_count == mysql_count else "⚠️"
            print(f"{status} {table}: SQLite={sqlite_count}, MySQL={mysql_count}")
            
        except Exception as e:
            print(f"❌ {table}: 验证失败 - {e}")


def main():
    """主函数"""
    print("="*60)
    print("SQLite到MySQL数据迁移工具")
    print("="*60)
    
    # 检查SQLite数据库是否存在
    if not os.path.exists(DB_PATH):
        print(f"❌ SQLite数据库不存在: {DB_PATH}")
        sys.exit(1)
    
    print(f"SQLite数据库: {DB_PATH}")
    print(f"MySQL数据库: {MYSQL_CONFIG['host']}:{MYSQL_CONFIG['port']}/{MYSQL_CONFIG['database']}")
    
    # 确认
    response = input("\n是否开始迁移？(yes/no): ")
    if response.lower() != 'yes':
        print("取消迁移")
        sys.exit(0)
    
    # 连接SQLite
    print("\n连接SQLite数据库...")
    sqlite_conn = sqlite3.connect(DB_PATH)
    sqlite_conn.row_factory = sqlite3.Row
    
    # 连接MySQL（会初始化连接池）
    print("连接MySQL数据库...")
    try:
        mysql_pool = get_mysql_connection_pool()
        print("✅ MySQL连接成功")
    except Exception as e:
        print(f"❌ MySQL连接失败: {e}")
        print("请检查MySQL配置和连接信息")
        sys.exit(1)
    
    # 表配置（字段转换规则和字段映射）
    table_configs = {
        'users': {
            'converters': {
                'created_time': convert_timestamp,
                'updated_time': convert_timestamp,
                'last_login_time': convert_timestamp,
            }
        },
        'sessions': {
            'column_mapping': {
                'created_time': 'created_at',  # SQLite使用created_time，MySQL使用created_at
                'last_access_time': 'last_access',  # SQLite使用last_access_time，MySQL使用last_access
            },
            'excluded_columns': ['ip_address', 'user_agent'],  # MySQL表中没有这些字段
            'special_fields': {
                'user_data': '{}'  # MySQL需要user_data字段，SQLite没有，使用空JSON
            },
            'converters': {
                'created_time': convert_timestamp,
                'last_access_time': convert_timestamp,
                'expires_at': convert_timestamp,
            }
        },
        'audit_logs': {
            'converters': {
                'created_time': convert_timestamp,
            }
        },
        'primary_boards': {
            'converters': {
                'created_time': convert_timestamp,
                'updated_time': convert_timestamp,
            }
        },
        'sub_boards': {
            'converters': {
                'created_time': convert_timestamp,
                'updated_time': convert_timestamp,
            }
        },
        'system_config': {
            'column_mapping': {
                'key': 'config_key',  # SQLite使用key，MySQL使用config_key
                'value': 'config_value',  # SQLite使用value，MySQL使用config_value
            }
        },
    }
    
    # 迁移顺序（考虑外键依赖）
    migration_order = [
        'users',
        'sessions',
        'audit_logs',
        'primary_boards',
        'sub_boards',
        'system_config',
    ]
    
    # 执行迁移
    start_time = datetime.now()
    print(f"\n开始迁移: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    for table in migration_order:
        config = table_configs.get(table, {})
        migrate_table(sqlite_conn, mysql_pool, table, config)
    
    end_time = datetime.now()
    elapsed = (end_time - start_time).total_seconds()
    print(f"\n迁移完成: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"总耗时: {elapsed:.2f} 秒")
    
    # 验证数据
    verify_data(sqlite_conn, mysql_pool)
    
    # 关闭连接
    sqlite_conn.close()
    print("\n✅ 迁移完成！")
    print("\n下一步：")
    print("1. 验证数据完整性")
    print("2. 更新server/config.py，设置USE_MYSQL=True")
    print("3. 重启服务器")


if __name__ == '__main__':
    main()

