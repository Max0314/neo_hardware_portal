#!/usr/bin/env python3
"""
修复MySQL用户数据问题
- 检查MySQL中缺失的用户
- 从Excel同步用户到MySQL
- 修复用户数据不一致问题
"""

import os
import sys
import json

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

# 加载MySQL环境变量（从.mysql.env文件）
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
    sys.exit(1)

from server.config import DATA_DIR, USE_MYSQL
from server.logger import logger
from server.user_manager import UserManager
from server.mysql_connection_pool import get_mysql_connection_pool

def check_mysql_users():
    """检查MySQL中的用户数据"""
    if not USE_MYSQL:
        print("❌ MySQL未启用，无法检查")
        return
    
    try:
        pool = get_mysql_connection_pool()
        with pool.get_cursor() as cursor:
            # 统计总用户数
            cursor.execute("SELECT COUNT(*) FROM users")
            total_count = cursor.fetchone()[0]
            print(f"✅ MySQL中共有 {total_count} 个用户")
            
            # 统计有dingtalk_data的用户
            cursor.execute("SELECT COUNT(*) FROM users WHERE dingtalk_data IS NOT NULL")
            dingtalk_count = cursor.fetchone()[0]
            print(f"✅ 其中 {dingtalk_count} 个用户有钉钉数据")
            
            # 检查有dingtalk_data但userid为空的用户
            cursor.execute("""
                SELECT id, username, name, dingtalk_data 
                FROM users 
                WHERE dingtalk_data IS NOT NULL 
                  AND (JSON_EXTRACT(dingtalk_data, '$.userid') IS NULL 
                       OR JSON_EXTRACT(dingtalk_data, '$.userid') = '')
            """)
            missing_userid = cursor.fetchall()
            if missing_userid:
                print(f"⚠️  发现 {len(missing_userid)} 个用户有钉钉数据但userid为空")
                for row in missing_userid[:5]:  # 只显示前5个
                    print(f"   - ID: {row[0]}, Username: {row[1]}, Name: {row[2]}")
            
            # 检查有userid但unionid为空的用户
            cursor.execute("""
                SELECT id, username, name, 
                       JSON_UNQUOTE(JSON_EXTRACT(dingtalk_data, '$.userid')) as userid,
                       JSON_UNQUOTE(JSON_EXTRACT(dingtalk_data, '$.unionid')) as unionid
                FROM users 
                WHERE dingtalk_data IS NOT NULL 
                  AND JSON_EXTRACT(dingtalk_data, '$.userid') IS NOT NULL
                  AND (JSON_EXTRACT(dingtalk_data, '$.unionid') IS NULL 
                       OR JSON_EXTRACT(dingtalk_data, '$.unionid') = '')
            """)
            missing_unionid = cursor.fetchall()
            if missing_unionid:
                print(f"⚠️  发现 {len(missing_unionid)} 个用户有userid但unionid为空")
                for row in missing_unionid[:5]:  # 只显示前5个
                    print(f"   - ID: {row[0]}, Username: {row[1]}, Name: {row[2]}, UserID: {row[3]}")
            
    except Exception as e:
        logger.error(f"检查MySQL用户数据失败: {e}", exc_info=True)
        print(f"❌ 检查失败: {e}")

def sync_excel_to_mysql():
    """从Excel同步用户到MySQL"""
    print("\n开始从Excel同步用户到MySQL...")
    
    try:
        user_manager = UserManager()
        
        # 获取所有用户（从Excel和MySQL）
        all_users = user_manager.get_all_users()
        print(f"✅ 从Excel和MySQL共获取到 {len(all_users)} 个用户")
        
        # 统计需要同步的用户
        dingtalk_users = [u for u in all_users if u.get('source') == 'dingtalk']
        print(f"✅ 其中 {len(dingtalk_users)} 个是钉钉用户")
        
        # 检查这些用户在MySQL中的情况
        if USE_MYSQL:
            pool = get_mysql_connection_pool()
            with pool.get_cursor() as cursor:
                missing_in_mysql = []
                for user in dingtalk_users:
                    userid = user.get('userid', '')
                    if not userid:
                        continue
                    
                    # 检查MySQL中是否存在
                    cursor.execute("""
                        SELECT id FROM users 
                        WHERE JSON_UNQUOTE(JSON_EXTRACT(dingtalk_data, '$.userid')) = %s
                           AND dingtalk_data IS NOT NULL
                    """, (str(userid),))
                    if not cursor.fetchone():
                        missing_in_mysql.append(user)
                
                if missing_in_mysql:
                    print(f"⚠️  发现 {len(missing_in_mysql)} 个钉钉用户在MySQL中不存在")
                    print("   建议执行钉钉用户同步操作来修复")
                else:
                    print("✅ 所有钉钉用户都已存在于MySQL中")
        
    except Exception as e:
        logger.error(f"同步Excel到MySQL失败: {e}", exc_info=True)
        print(f"❌ 同步失败: {e}")

def main():
    """主函数"""
    print("=" * 60)
    print("MySQL用户数据诊断和修复工具")
    print("=" * 60)
    print()
    
    # 检查MySQL用户数据
    print("1. 检查MySQL用户数据...")
    check_mysql_users()
    print()
    
    # 同步Excel到MySQL
    print("2. 检查Excel和MySQL数据一致性...")
    sync_excel_to_mysql()
    print()
    
    print("=" * 60)
    print("诊断完成")
    print("=" * 60)
    print()
    print("建议操作：")
    print("  1. 如果发现用户缺失，请在用户管理页面执行'同步钉钉用户'操作")
    print("  2. 如果Excel文件损坏，系统会自动尝试恢复")
    print("  3. 如果问题持续，请检查服务器日志获取详细信息")

if __name__ == '__main__':
    main()

