#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试MySQL连接脚本
用于验证MySQL配置是否正确
"""
import os
import sys

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

try:
    from server.config import MYSQL_CONFIG
    print("MySQL配置:")
    print(f"  主机: {MYSQL_CONFIG['host']}")
    print(f"  端口: {MYSQL_CONFIG['port']}")
    print(f"  用户: {MYSQL_CONFIG['user']}")
    print(f"  数据库: {MYSQL_CONFIG['database']}")
    print(f"  字符集: {MYSQL_CONFIG['charset']}")
    password_set = bool(MYSQL_CONFIG['password'])
    print(f"  密码: {'已设置' if password_set else '❌ 未设置（请设置MYSQL_PASSWORD环境变量）'}")
    print()
    
    if not password_set:
        print("⚠️  警告: 密码未设置！")
        print("请运行以下命令设置密码:")
        print("  export MYSQL_PASSWORD='your_password'")
        print("或修改 server/config.py 中的 MYSQL_CONFIG['password']")
        print()
        sys.exit(1)
except Exception as e:
    print(f"读取配置失败: {e}")
    sys.exit(1)

# 测试pymysql
try:
    import pymysql
    print("✅ pymysql已安装")
    
    print("\n测试连接...")
    conn = pymysql.connect(
        host=MYSQL_CONFIG['host'],
        port=MYSQL_CONFIG['port'],
        user=MYSQL_CONFIG['user'],
        password=MYSQL_CONFIG['password'],
        database=MYSQL_CONFIG['database'],
        charset=MYSQL_CONFIG['charset']
    )
    
    print("✅ MySQL连接成功！")
    
    # 测试查询
    cursor = conn.cursor()
    cursor.execute("SELECT VERSION()")
    version = cursor.fetchone()
    print(f"✅ MySQL版本: {version[0]}")
    
    # 测试字符集
    cursor.execute("SHOW VARIABLES LIKE 'character_set_database'")
    charset = cursor.fetchone()
    print(f"✅ 数据库字符集: {charset[1]}")
    
    cursor.close()
    conn.close()
    print("\n✅ 所有测试通过！")
    
except ImportError:
    print("❌ pymysql未安装，请运行: pip install pymysql")
    sys.exit(1)
except Exception as e:
    print(f"❌ 连接失败: {e}")
    print("\n请检查:")
    print("1. MySQL服务是否运行")
    print("2. 用户名和密码是否正确")
    print("3. 数据库是否存在")
    print("4. 用户是否有权限访问数据库")
    sys.exit(1)

