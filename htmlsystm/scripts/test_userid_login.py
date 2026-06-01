#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试通过userid登录功能
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.user_manager import UserManager
from server.mysql_connection_pool import get_mysql_connection_pool
from server.logger import logger

def test_userid_login(userid: str):
    """测试通过userid查找用户"""
    print(f"\n{'='*60}")
    print(f"测试通过userid登录: {userid}")
    print(f"{'='*60}\n")
    
    # 1. 检查MySQL中是否存在该userid
    print("1. 检查MySQL数据库...")
    try:
        pool = get_mysql_connection_pool()
        with pool.get_cursor() as cursor:
            # 查询所有包含userid的记录
            cursor.execute("""
                SELECT id, username, name, dingtalk_data 
                FROM users 
                WHERE dingtalk_data IS NOT NULL
                LIMIT 10
            """)
            rows = cursor.fetchall()
            print(f"   找到 {len(rows)} 条包含dingtalk_data的记录")
            
            # 检查是否有匹配的userid
            found = False
            for row in rows:
                dingtalk_data = row.get('dingtalk_data') if isinstance(row, dict) else row[3]
                if dingtalk_data:
                    import json
                    try:
                        data = json.loads(dingtalk_data) if isinstance(dingtalk_data, str) else dingtalk_data
                        if isinstance(data, dict) and data.get('userid') == userid:
                            found = True
                            print(f"   ✅ 找到匹配的用户: ID={row.get('id') if isinstance(row, dict) else row[0]}, 姓名={row.get('name') if isinstance(row, dict) else row[2]}")
                            break
                    except Exception as e:
                        pass
            
            if not found:
                print(f"   ❌ 未在MySQL中找到userid={userid}")
                print(f"   尝试使用JSON_EXTRACT查询...")
                cursor.execute("""
                    SELECT id, username, name, dingtalk_data 
                    FROM users 
                    WHERE JSON_EXTRACT(dingtalk_data, '$.userid') = %s
                       AND dingtalk_data IS NOT NULL
                """, (userid,))
                row = cursor.fetchone()
                if row:
                    print(f"   ✅ JSON_EXTRACT查询成功: ID={row.get('id') if isinstance(row, dict) else row[0]}")
                else:
                    print(f"   ❌ JSON_EXTRACT查询也失败")
    except Exception as e:
        print(f"   ❌ MySQL查询失败: {e}")
    
    # 2. 使用UserManager查找
    print("\n2. 使用UserManager查找...")
    try:
        user_manager = UserManager()
        user = user_manager.get_user_by_userid(userid)
        if user:
            print(f"   ✅ 找到用户:")
            print(f"      ID: {user.get('id')}")
            print(f"      用户名: {user.get('username')}")
            print(f"      姓名: {user.get('name')}")
            print(f"      状态: {user.get('status')}")
            print(f"      userid: {user.get('userid')}")
            print(f"      unionid: {user.get('unionid')}")
        else:
            print(f"   ❌ 未找到用户")
    except Exception as e:
        print(f"   ❌ UserManager查找失败: {e}")
        import traceback
        traceback.print_exc()
    
    print(f"\n{'='*60}\n")

if __name__ == '__main__':
    # 测试userid
    test_userid = '533918221524183112'
    if len(sys.argv) > 1:
        test_userid = sys.argv[1]
    
    test_userid_login(test_userid)

