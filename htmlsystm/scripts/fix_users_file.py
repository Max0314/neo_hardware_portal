#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
修复损坏的users.xlsx文件
从MySQL数据库恢复用户数据到Excel文件
"""
import os
import sys
import openpyxl
from datetime import datetime

# 添加项目根目录到Python路径
_current_file_dir = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(_current_file_dir)
sys.path.insert(0, BASE_DIR)

from server.config import DATA_DIR
from server.db_adapter import get_connection_pool
from server.logger import logger

def fix_users_file():
    """修复users.xlsx文件"""
    users_file = os.path.join(DATA_DIR, 'users.xlsx')
    
    # 检查文件是否存在
    if os.path.exists(users_file):
        # 备份损坏的文件
        backup_file = f"{users_file}.backup.{int(datetime.now().timestamp())}"
        try:
            import shutil
            shutil.copy2(users_file, backup_file)
            logger.info(f"已备份原文件到: {backup_file}")
        except Exception as e:
            logger.warning(f"备份文件失败: {e}")
    
    # 从MySQL数据库读取用户数据
    try:
        pool = get_connection_pool()
        with pool.get_cursor() as cursor:
            cursor.execute('SELECT * FROM users ORDER BY id')
            rows = cursor.fetchall()
            
            if not rows:
                logger.warning("数据库中没有用户数据，创建空文件")
                # 创建空的Excel文件
                wb = openpyxl.Workbook()
                ws = wb.active
                ws.title = "Users"
                # 添加表头
                headers = ['id', 'username', 'password', 'name', 'department', 'role', 'status', 'userid', 'unionid', 'created_time', 'updated_time']
                ws.append(headers)
                wb.save(users_file)
                logger.info(f"已创建空的users.xlsx文件: {users_file}")
                return True
            
            # 创建新的Excel文件
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Users"
            
            # 获取列名
            columns = [desc[0] for desc in cursor.description] if hasattr(cursor, 'description') else []
            if not columns:
                # 如果无法获取列名，使用默认列名
                columns = ['id', 'username', 'password', 'name', 'department', 'role', 'status', 'userid', 'unionid', 'created_time', 'updated_time']
            
            # 添加表头
            ws.append(columns)
            
            # 添加数据行
            for row in rows:
                if isinstance(row, dict):
                    values = [row.get(col, '') for col in columns]
                else:
                    values = list(row) if row else []
                ws.append(values)
            
            # 保存文件
            wb.save(users_file)
            logger.info(f"已从数据库恢复 {len(rows)} 条用户数据到: {users_file}")
            return True
            
    except Exception as e:
        logger.error(f"从数据库恢复用户数据失败: {e}", exc_info=True)
        return False

if __name__ == '__main__':
    print("=" * 60)
    print("修复users.xlsx文件")
    print("=" * 60)
    
    success = fix_users_file()
    
    if success:
        print("✅ 文件修复成功！")
        sys.exit(0)
    else:
        print("❌ 文件修复失败，请检查日志")
        sys.exit(1)

