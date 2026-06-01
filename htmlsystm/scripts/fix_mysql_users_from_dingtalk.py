#!/usr/bin/env python3
"""
从钉钉重新同步所有用户并修复MySQL数据库
- 从钉钉API获取所有用户
- 保存到MySQL和Excel
- 修复数据不一致问题
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
    print("   或者手动设置: export MYSQL_PASSWORD='your_password'")
    sys.exit(1)

from server.config import DATA_DIR, USE_MYSQL
from server.logger import logger
from server.user_manager import UserManager
from server.mysql_connection_pool import get_mysql_connection_pool

def get_access_token():
    """获取钉钉access_token"""
    import urllib.request
    import urllib.error
    import ssl
    from server.config import DINGTALK_CONFIG
    
    client_id = DINGTALK_CONFIG.get('client_id', '')
    client_secret = DINGTALK_CONFIG.get('client_secret', '')
    corp_id = DINGTALK_CONFIG.get('corp_id', '')
    
    if not client_id or not client_secret or not corp_id:
        raise Exception("钉钉配置不完整，请检查 server/config.py 中的 DINGTALK_CONFIG")
    
    url = f"https://api.dingtalk.com/v1.0/oauth2/{corp_id}/token"
    payload = {
        'client_id': client_id,
        'client_secret': client_secret,
        'grant_type': 'client_credentials'
    }
    
    headers = {
        'Content-Type': 'application/json',
        'Host': 'api.dingtalk.com'
    }
    
    request_data_bytes = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=request_data_bytes, headers=headers, method='POST')
    
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    
    try:
        with urllib.request.urlopen(req, timeout=30, context=ssl_context) as response:
            response_text = response.read().decode('utf-8')
            result = json.loads(response_text)
            
            if 'access_token' in result:
                return result['access_token']
            else:
                error_msg = result.get('error_description', result.get('error', '未知错误'))
                raise Exception(f"获取access_token失败: {error_msg}")
    except urllib.error.HTTPError as e:
        error_body = ''
        try:
            if e.fp:
                error_body = e.read().decode('utf-8')
        except:
            pass
        raise Exception(f"HTTP错误 {e.code}: {error_body[:200] if error_body else str(e)}")
    except urllib.error.URLError as e:
        raise Exception(f"网络错误: {str(e)}")

def get_department_list(access_token, dept_id=1):
    """获取部门列表"""
    import urllib.request
    import urllib.error
    import ssl
    import urllib.parse
    
    url = "https://oapi.dingtalk.com/topapi/v2/department/listsub"
    params = {
        'language': 'zh_CN',
        'dept_id': dept_id
    }
    
    url_with_params = f"{url}?access_token={urllib.parse.quote(access_token)}"
    request_data = json.dumps(params).encode('utf-8')
    
    req = urllib.request.Request(
        url_with_params,
        data=request_data,
        headers={'Content-Type': 'application/json'},
        method='POST'
    )
    
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    
    try:
        with urllib.request.urlopen(req, timeout=30, context=ssl_context) as response:
            response_text = response.read().decode('utf-8')
            result = json.loads(response_text)
            
            if result.get('errcode') == 0:
                return result.get('result', [])
            else:
                raise Exception(f"获取部门列表失败: {result.get('errmsg', '未知错误')}")
    except urllib.error.HTTPError as e:
        error_body = ''
        try:
            if e.fp:
                error_body = e.read().decode('utf-8')
        except:
            pass
        raise Exception(f"HTTP错误 {e.code}: {error_body[:200] if error_body else str(e)}")
    except urllib.error.URLError as e:
        raise Exception(f"网络错误: {str(e)}")

def get_department_users(access_token, dept_id, cursor="0", size=100):
    """获取部门用户列表"""
    import urllib.request
    import urllib.error
    import ssl
    import urllib.parse
    
    url = "https://oapi.dingtalk.com/topapi/v2/user/list"
    params = {
        'cursor': int(cursor) if isinstance(cursor, str) and cursor.isdigit() else cursor,
        'contain_access_limit': False,
        'size': int(size) if isinstance(size, (str, int)) else 100,
        'order_field': 'modify_desc',
        'language': 'zh_CN',
        'dept_id': int(dept_id) if isinstance(dept_id, str) and dept_id.isdigit() else dept_id
    }
    
    url_with_params = f"{url}?access_token={urllib.parse.quote(access_token)}"
    request_data = json.dumps(params).encode('utf-8')
    
    req = urllib.request.Request(
        url_with_params,
        data=request_data,
        headers={'Content-Type': 'application/json'},
        method='POST'
    )
    
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    
    try:
        with urllib.request.urlopen(req, timeout=30, context=ssl_context) as response:
            response_text = response.read().decode('utf-8')
            result = json.loads(response_text)
            
            if result.get('errcode') == 0:
                result_data = result.get('result', {})
                return {
                    'list': result_data.get('list', []),
                    'has_more': result_data.get('has_more', False),
                    'next_cursor': result_data.get('next_cursor', '0')
                }
            else:
                raise Exception(f"获取部门用户列表失败: {result.get('errmsg', '未知错误')}")
    except urllib.error.HTTPError as e:
        error_body = ''
        try:
            if e.fp:
                error_body = e.read().decode('utf-8')
        except:
            pass
        raise Exception(f"HTTP错误 {e.code}: {error_body[:200] if error_body else str(e)}")
    except urllib.error.URLError as e:
        raise Exception(f"网络错误: {str(e)}")

def sync_all_users_from_dingtalk():
    """从钉钉同步所有用户"""
    print("\n" + "=" * 60)
    print("从钉钉同步所有用户")
    print("=" * 60)
    print()
    
    try:
        from server.config import DINGTALK_CONFIG
        
        # 检查配置
        if not DINGTALK_CONFIG.get('client_id') or not DINGTALK_CONFIG.get('client_secret'):
            print("❌ 钉钉配置不完整，无法同步用户")
            print("   请检查 server/config.py 中的 DINGTALK_CONFIG")
            return False
        
        # 获取access_token
        print("正在获取access_token...")
        access_token = get_access_token()
        if not access_token:
            print("❌ 获取access_token失败")
            return False
        print(f"✅ 获取access_token成功")
        
        # 获取部门列表
        print("\n正在获取部门列表...")
        departments = get_department_list(access_token)
        if not departments:
            print("❌ 获取部门列表失败")
            return False
        print(f"✅ 获取到 {len(departments)} 个部门")
        
        # 获取所有部门（不仅仅是硬件研发部）
        print("\n选择同步范围:")
        print("  1. 仅硬件研发部及其子部门（默认）")
        print("  2. 所有部门")
        choice = input("请选择 (1/2，直接回车默认选择1): ").strip()
        
        if choice == '2':
            # 同步所有部门
            all_dept_ids = [dept.get('dept_id') for dept in departments]
            print(f"\n✅ 将同步所有 {len(all_dept_ids)} 个部门的用户")
            hardware_rd_dept_ids = all_dept_ids
        else:
            # 仅硬件研发部
            hardware_rd_dept_ids = []
            for dept in departments:
                dept_name = dept.get('name', '')
                if '硬件研发' in dept_name or '硬件' in dept_name:
                    hardware_rd_dept_ids.append(dept.get('dept_id'))
                    print(f"   - 找到部门: {dept_name} (ID: {dept.get('dept_id')})")
            
            if not hardware_rd_dept_ids:
                print("⚠️  未找到硬件研发部，将同步所有部门的用户")
                hardware_rd_dept_ids = [dept.get('dept_id') for dept in departments]
        
        # 获取所有用户
        print(f"\n正在获取用户列表（部门数量: {len(hardware_rd_dept_ids)}）...")
        all_users = []
        
        for dept_id in hardware_rd_dept_ids:
            dept_name = next((d.get('name', '') for d in departments if d.get('dept_id') == dept_id), f"部门{dept_id}")
            print(f"  正在获取部门 '{dept_name}' (ID: {dept_id}) 的用户...")
            
            cursor = "0"
            page = 1
            while True:
                try:
                    result = get_department_users(access_token, dept_id, cursor=cursor, size=100)
                    users = result.get('list', [])
                    if not users:
                        break
                    
                    all_users.extend(users)
                    print(f"    第 {page} 页: 获取到 {len(users)} 个用户")
                    
                    has_more = result.get('has_more', False)
                    if has_more:
                        cursor = result.get('next_cursor', '0')
                        page += 1
                    else:
                        break
                except Exception as e:
                    logger.error(f"获取部门 {dept_id} 用户列表失败: {e}")
                    break
        
        if not all_users:
            print("❌ 未获取到任何用户")
            return False
        
        print(f"\n✅ 总共获取到 {len(all_users)} 个用户")
        
        # 保存用户到MySQL和Excel
        print("\n正在保存用户到MySQL和Excel...")
        user_manager = UserManager()
        success = user_manager.save_dingtalk_users(all_users, append=False, source_dept_ids=hardware_rd_dept_ids)
        
        if success:
            print(f"✅ 成功保存 {len(all_users)} 个用户到MySQL和Excel")
            
            # 验证保存结果
            print("\n正在验证保存结果...")
            verify_saved_users(all_users)
            
            return True
        else:
            print("❌ 保存用户失败")
            return False
            
    except Exception as e:
        logger.error(f"从钉钉同步用户失败: {e}", exc_info=True)
        print(f"❌ 同步失败: {e}")
        return False

def verify_saved_users(users):
    """验证用户是否已正确保存到MySQL"""
    if not USE_MYSQL:
        print("⚠️  MySQL未启用，跳过验证")
        return
    
    try:
        pool = get_mysql_connection_pool()
        with pool.get_cursor() as cursor:
            # 首先检查dingtalk_data字段是否存在
            from server.config import MYSQL_CONFIG
            cursor.execute("""
                SELECT COLUMN_NAME 
                FROM INFORMATION_SCHEMA.COLUMNS 
                WHERE TABLE_SCHEMA = %s 
                AND TABLE_NAME = 'users' 
                AND COLUMN_NAME = 'dingtalk_data'
            """, (MYSQL_CONFIG['database'],))
            
            has_dingtalk_data = cursor.fetchone() is not None
            
            if not has_dingtalk_data:
                print("   ⚠️  dingtalk_data字段不存在，无法验证")
                print("   建议运行: python3 scripts/add_dingtalk_fields_to_mysql.py")
                return
            
            found_count = 0
            missing_count = 0
            missing_userids = []
            
            for user in users:
                userid = str(user.get('userid', ''))
                if not userid:
                    continue
                
                # 查找用户（使用多种方法）
                found = False
                
                # 方法1: 通过dingtalk_data中的userid查找
                try:
                    cursor.execute("""
                        SELECT id FROM users 
                        WHERE JSON_UNQUOTE(JSON_EXTRACT(dingtalk_data, '$.userid')) = %s
                           AND dingtalk_data IS NOT NULL
                    """, (userid,))
                    if cursor.fetchone():
                        found = True
                except:
                    pass
                
                # 方法2: 如果方法1失败，通过username查找（向后兼容）
                if not found:
                    job_number = user.get('job_number', '')
                    username = str(job_number).strip() if job_number and str(job_number).strip() else str(userid)
                    cursor.execute('SELECT id FROM users WHERE username = %s', (username,))
                    if cursor.fetchone():
                        found = True
                
                if found:
                    found_count += 1
                else:
                    missing_count += 1
                    missing_userids.append(userid)
            
            print(f"   ✅ MySQL中找到 {found_count} 个用户")
            if missing_count > 0:
                print(f"   ⚠️  MySQL中缺失 {missing_count} 个用户")
                if len(missing_userids) <= 10:
                    print(f"   缺失的userid: {', '.join(missing_userids)}")
                else:
                    print(f"   缺失的userid（前10个）: {', '.join(missing_userids[:10])}...")
            else:
                print(f"   ✅ 所有用户都已正确保存到MySQL")
                
    except Exception as e:
        logger.error(f"验证保存结果失败: {e}", exc_info=True)
        print(f"   ⚠️  验证失败: {e}")

def ensure_mysql_table_structure():
    """确保MySQL表结构正确"""
    print("\n检查MySQL表结构...")
    
    if not USE_MYSQL:
        print("⚠️  MySQL未启用，跳过表结构检查")
        return True
    
    try:
        pool = get_mysql_connection_pool()
        with pool.get_cursor() as cursor:
            # 检查dingtalk_data字段是否存在
            from server.config import MYSQL_CONFIG
            cursor.execute("""
                SELECT COLUMN_NAME 
                FROM INFORMATION_SCHEMA.COLUMNS 
                WHERE TABLE_SCHEMA = %s 
                AND TABLE_NAME = 'users' 
                AND COLUMN_NAME = 'dingtalk_data'
            """, (MYSQL_CONFIG['database'],))
            
            if cursor.fetchone():
                print("✅ dingtalk_data字段已存在")
                return True
            
            # 字段不存在，尝试添加
            print("⚠️  dingtalk_data字段不存在，正在添加...")
            try:
                cursor.execute("""
                    ALTER TABLE users 
                    ADD COLUMN dingtalk_data JSON NULL 
                    COMMENT '钉钉用户完整数据（JSON格式）'
                    AFTER last_login_time
                """)
                print("✅ 成功添加dingtalk_data字段")
                return True
            except Exception as e:
                print(f"❌ 添加dingtalk_data字段失败: {e}")
                print("   请手动运行: python3 scripts/add_dingtalk_fields_to_mysql.py")
                return False
                
    except Exception as e:
        logger.error(f"检查MySQL表结构失败: {e}", exc_info=True)
        print(f"❌ 检查失败: {e}")
        return False

def main():
    """主函数"""
    print("=" * 60)
    print("从钉钉重新同步所有用户并修复MySQL数据库")
    print("=" * 60)
    print()
    print("此脚本将：")
    print("  1. 检查并修复MySQL表结构（添加dingtalk_data字段）")
    print("  2. 从钉钉API获取所有用户")
    print("  3. 保存到MySQL数据库")
    print("  4. 保存到Excel文件")
    print("  5. 验证保存结果")
    print()
    
    response = input("是否继续？(y/n): ")
    if response.lower() != 'y':
        print("已取消")
        return
    
    # 确保MySQL表结构正确
    if not ensure_mysql_table_structure():
        print("\n⚠️  MySQL表结构检查失败，但将继续尝试同步...")
    
    # 同步用户
    success = sync_all_users_from_dingtalk()
    
    print("\n" + "=" * 60)
    if success:
        print("✅ 同步完成！")
        print("\n建议运行检查脚本验证结果:")
        print("  python3 scripts/check_sync_and_excel.py")
    else:
        print("❌ 同步失败，请检查错误信息")
    print("=" * 60)

if __name__ == '__main__':
    main()

