#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
服务器压力测试脚本
模拟多用户并发访问，测试服务器性能和稳定性

测试项：
1. 并发登录并查看公告栏测试 - 500用户同时登录网页并查看公告栏
2. 性能指标收集 - 响应时间、成功率、错误率等
"""

import requests
import time
import json
import random
import string
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from collections import defaultdict
import statistics
import sys

# 服务器配置
BASE_URL = "http://10.70.33.26:8000"

# 测试配置
CONCURRENT_USERS = 500  # 并发用户数（登录并查看公告栏）
USERS_PER_SECOND = 10  # 每秒启动的用户数（控制启动速度，避免文件锁竞争，降低服务器压力）

# 测试用户列表（用于并发测试）
# 注意：从钉钉同步的用户默认密码是 CHXW_HW_123456
# 如果某些用户密码不同，请修改对应的密码
TEST_USERS = [
    {"username": "20510283", "password": "CHXW_HW_123456"},
    {"username": "20510280", "password": "CHXW_HW_123456"},
    {"username": "20468589", "password": "CHXW_HW_123456"},
    {"username": "20461989", "password": "CHXW_HW_123456"},
    {"username": "20429710", "password": "CHXW_HW_123456"},
    {"username": "20425826", "password": "CHXW_HW_123456"},
    {"username": "20425819", "password": "CHXW_HW_123456"},
    {"username": "11021950", "password": "CHXW_HW_123456"},
    {"username": "20462244", "password": "CHXW_HW_123456"},
    {"username": "20461992", "password": "123456"},  # 如果该用户密码不同，请修改
]

# 主测试账号（用于需要管理员权限的操作和工作通知发送）
TEST_USERNAME = "20461992"  # 测试账号用户名（张志伟）
TEST_PASSWORD = "123456"  # 测试账号密码
TARGET_USER_FOR_NOTIFICATION = "20461992"  # 工作通知目标用户（张志伟）

# 测试结果统计
test_results = {
    'login_and_view_announcement': {
        'total': 0,
        'success': 0,
        'failed': 0,
        'response_times': [],
        'errors': [],
        'login_times': [],
        'page_load_times': [],
        'api_load_times': []
    }
}

# 会话管理
sessions = {}  # {username: session}


def generate_random_string(length=8):
    """生成随机字符串"""
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))


def login_user(username, password):
    """用户登录"""
    start_time = time.time()
    try:
        url = f"{BASE_URL}/api/auth/login"
        data = {
            'username': username,
            'password': password
        }
        response = requests.post(url, json=data, timeout=10)
        login_time = (time.time() - start_time) * 1000  # 转换为毫秒
        
        if response.status_code == 200:
            try:
                result = response.json()
                if result.get('success'):
                    # 从响应头获取session_id
                    session_id = response.cookies.get('session_id')
                    if session_id:
                        sessions[username] = {
                            'session_id': session_id,
                            'cookies': response.cookies
                        }
                        return True, session_id, login_time
                else:
                    # 登录失败，返回错误信息
                    error_msg = result.get('error', result.get('message', '登录失败'))
                    return False, f"登录失败: {error_msg}", login_time
            except json.JSONDecodeError:
                return False, f"登录失败: 服务器返回非JSON响应 (HTTP {response.status_code})", login_time
        else:
            # HTTP状态码不是200
            try:
                error_data = response.json()
                error_msg = error_data.get('error', error_data.get('message', f'HTTP {response.status_code}'))
            except:
                error_msg = f'HTTP {response.status_code}: {response.text[:100]}'
            return False, error_msg, login_time
    except requests.exceptions.Timeout:
        login_time = (time.time() - start_time) * 1000
        return False, "登录超时", login_time
    except requests.exceptions.ConnectionError:
        login_time = (time.time() - start_time) * 1000
        return False, "连接失败", login_time
    except Exception as e:
        login_time = (time.time() - start_time) * 1000
        return False, f"登录异常: {str(e)}", login_time


def view_announcement_page(session_cookies):
    """访问公告栏页面（HTML页面）"""
    start_time = time.time()
    try:
        url = f"{BASE_URL}/announcement"
        response = requests.get(url, cookies=session_cookies, timeout=10)
        response_time = (time.time() - start_time) * 1000  # 转换为毫秒
        
        if response.status_code == 200 and 'text/html' in response.headers.get('Content-Type', ''):
            return True, response_time, None
        else:
            error_msg = f"HTTP {response.status_code}: 页面加载失败"
            return False, response_time, error_msg
    except Exception as e:
        response_time = (time.time() - start_time) * 1000
        error_msg = str(e)
        return False, response_time, error_msg


def load_announcement_list(session_cookies):
    """加载公告列表API（模拟浏览器加载公告数据）"""
    start_time = time.time()
    try:
        url = f"{BASE_URL}/api/announcement/list"
        params = {
            'status': 'approved',
            'page': 1,
            'page_size': 20
        }
        response = requests.get(url, cookies=session_cookies, params=params, timeout=10)
        response_time = (time.time() - start_time) * 1000  # 转换为毫秒
        
        if response.status_code == 200:
            try:
                result = response.json()
                # 检查返回的是数组或包含announcements的对象
                if isinstance(result, list) or (isinstance(result, dict) and 'announcements' in result):
                    return True, response_time, None
                else:
                    error_msg = "API返回格式不正确"
                    return False, response_time, error_msg
            except json.JSONDecodeError as e:
                # JSON解析失败，可能是返回了HTML错误页面
                error_msg = f"JSON解析失败 (可能是未登录或权限不足): {str(e)}"
                if len(response.text) > 0:
                    error_msg += f", 响应前100字符: {response.text[:100]}"
                return False, response_time, error_msg
        elif response.status_code == 401 or response.status_code == 403:
            error_msg = f"HTTP {response.status_code}: 未授权或权限不足"
            return False, response_time, error_msg
        else:
            try:
                error_data = response.json()
                error_msg = f"HTTP {response.status_code}: {error_data.get('error', error_data.get('message', response.text[:100]))}"
            except:
                error_msg = f"HTTP {response.status_code}: {response.text[:100]}"
            return False, response_time, error_msg
    except requests.exceptions.Timeout:
        response_time = (time.time() - start_time) * 1000
        return False, response_time, "API请求超时"
    except requests.exceptions.ConnectionError:
        response_time = (time.time() - start_time) * 1000
        return False, response_time, "连接失败"
    except Exception as e:
        response_time = (time.time() - start_time) * 1000
        error_msg = f"API请求异常: {str(e)}"
        return False, response_time, error_msg


def test_login_and_view_announcement(user_id):
    """测试登录并查看公告栏（单个用户）"""
    # 从测试用户列表中循环选择用户
    user = TEST_USERS[user_id % len(TEST_USERS)]
    username = user["username"]
    password = user["password"]
    
    total_start_time = time.time()
    
    # 步骤1: 登录
    success, session_id, login_time = login_user(username, password)
    if not success:
        test_results['login_and_view_announcement']['total'] += 1
        test_results['login_and_view_announcement']['failed'] += 1
        total_time = (time.time() - total_start_time) * 1000
        test_results['login_and_view_announcement']['response_times'].append(total_time)
        test_results['login_and_view_announcement']['errors'].append(f"用户{username}登录失败: {session_id}")
        return False, f"登录失败: {session_id}"
    
    test_results['login_and_view_announcement']['login_times'].append(login_time)
    session_cookies = {'session_id': session_id}
    
    # 步骤2: 访问公告栏页面
    success, page_time, error = view_announcement_page(session_cookies)
    if not success:
        test_results['login_and_view_announcement']['total'] += 1
        test_results['login_and_view_announcement']['failed'] += 1
        total_time = (time.time() - total_start_time) * 1000
        test_results['login_and_view_announcement']['response_times'].append(total_time)
        test_results['login_and_view_announcement']['errors'].append(f"用户{username}页面加载失败: {error}")
        return False, f"页面加载失败: {error}"
    
    test_results['login_and_view_announcement']['page_load_times'].append(page_time)
    
    # 步骤3: 加载公告列表API（模拟浏览器获取公告数据）
    success, api_time, error = load_announcement_list(session_cookies)
    if not success:
        test_results['login_and_view_announcement']['total'] += 1
        test_results['login_and_view_announcement']['failed'] += 1
        total_time = (time.time() - total_start_time) * 1000
        test_results['login_and_view_announcement']['response_times'].append(total_time)
        test_results['login_and_view_announcement']['errors'].append(f"用户{username}API加载失败: {error}")
        return False, f"API加载失败: {error}"
    
    test_results['login_and_view_announcement']['api_load_times'].append(api_time)
    
    # 全部成功
    total_time = (time.time() - total_start_time) * 1000
    test_results['login_and_view_announcement']['total'] += 1
    test_results['login_and_view_announcement']['success'] += 1
    test_results['login_and_view_announcement']['response_times'].append(total_time)
    
    return True, f"总耗时: {total_time:.2f}ms (登录: {login_time:.2f}ms, 页面: {page_time:.2f}ms, API: {api_time:.2f}ms)"


def print_statistics(test_name, results):
    """打印测试统计信息"""
    print(f"\n{'='*60}")
    print(f"测试项: {test_name}")
    print(f"{'='*60}")
    print(f"总请求数: {results['total']}")
    print(f"成功数: {results['success']}")
    print(f"失败数: {results['failed']}")
    
    if results['total'] > 0:
        success_rate = (results['success'] / results['total']) * 100
        print(f"成功率: {success_rate:.2f}%")
    
    # 总响应时间统计
    if results['response_times']:
        avg_time = statistics.mean(results['response_times'])
        median_time = statistics.median(results['response_times'])
        min_time = min(results['response_times'])
        max_time = max(results['response_times'])
        
        print(f"\n总响应时间统计 (ms):")
        print(f"  平均: {avg_time:.2f}")
        print(f"  中位数: {median_time:.2f}")
        print(f"  最小: {min_time:.2f}")
        print(f"  最大: {max_time:.2f}")
        
        if len(results['response_times']) > 1:
            std_dev = statistics.stdev(results['response_times'])
            print(f"  标准差: {std_dev:.2f}")
    
    # 登录时间统计
    if results.get('login_times'):
        avg_login = statistics.mean(results['login_times'])
        print(f"\n登录时间统计 (ms):")
        print(f"  平均: {avg_login:.2f}")
        print(f"  最小: {min(results['login_times']):.2f}")
        print(f"  最大: {max(results['login_times']):.2f}")
    
    # 页面加载时间统计
    if results.get('page_load_times'):
        avg_page = statistics.mean(results['page_load_times'])
        print(f"\n页面加载时间统计 (ms):")
        print(f"  平均: {avg_page:.2f}")
        print(f"  最小: {min(results['page_load_times']):.2f}")
        print(f"  最大: {max(results['page_load_times']):.2f}")
    
    # API加载时间统计
    if results.get('api_load_times'):
        avg_api = statistics.mean(results['api_load_times'])
        print(f"\nAPI加载时间统计 (ms):")
        print(f"  平均: {avg_api:.2f}")
        print(f"  最小: {min(results['api_load_times']):.2f}")
        print(f"  最大: {max(results['api_load_times']):.2f}")
    
    if results['errors']:
        print(f"\n错误信息 (前10条):")
        for i, error in enumerate(results['errors'][:10], 1):
            print(f"  {i}. {error}")
        if len(results['errors']) > 10:
            print(f"  ... 还有 {len(results['errors']) - 10} 条错误")


def main():
    """主测试函数"""
    print("="*60)
    print("服务器压力测试开始")
    print("="*60)
    print(f"服务器地址: {BASE_URL}")
    print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"并发用户数: {CONCURRENT_USERS}")
    print(f"测试用户数: {len(TEST_USERS)} 个")
    print("="*60)
    print("\n测试项说明:")
    print(f"  并发登录并查看公告栏测试 - {CONCURRENT_USERS}个用户登录网页并查看公告栏")
    print(f"  启动速度: 每秒 {USERS_PER_SECOND} 个用户（共需约 {CONCURRENT_USERS / USERS_PER_SECOND:.0f} 秒启动完成）")
    print("    每个用户的操作流程:")
    print("      1. 登录系统")
    print("      2. 访问公告栏页面 (/announcement)")
    print("      3. 加载公告列表API (/api/announcement/list)")
    print("="*60)
    
    start_time = time.time()
    
    # 并发登录并查看公告栏测试（按每秒20个用户的速度启动，避免文件锁竞争）
    print(f"\n[测试] 并发登录并查看公告栏测试...")
    print(f"模拟 {CONCURRENT_USERS} 个用户登录网页并查看公告栏")
    print(f"启动速度: 每秒 {USERS_PER_SECOND} 个用户（降低速度以避免文件锁竞争）")
    
    with ThreadPoolExecutor(max_workers=CONCURRENT_USERS) as executor:
        futures = []
        start_interval = 1.0 / USERS_PER_SECOND  # 每个用户启动间隔（秒）
        
        # 按时间间隔启动用户，每秒启动USERS_PER_SECOND个
        for i in range(CONCURRENT_USERS):
            future = executor.submit(test_login_and_view_announcement, i)
            futures.append(future)
            
            # 每启动USERS_PER_SECOND个用户后，等待1秒（除了最后一个）
            if (i + 1) % USERS_PER_SECOND == 0:
                if i + 1 < CONCURRENT_USERS:  # 最后一个用户不需要等待
                    print(f"  已启动: {i + 1}/{CONCURRENT_USERS} 个用户")
                    time.sleep(1.0)
            elif (i + 1) < CONCURRENT_USERS:  # 其他用户按间隔启动（最后一个除外）
                time.sleep(start_interval)
        
        print(f"  已启动: {CONCURRENT_USERS}/{CONCURRENT_USERS} 个用户，等待所有任务完成...")
        
        # 等待所有任务完成
        completed = 0
        for future in as_completed(futures):
            completed += 1
            if completed % 50 == 0:
                print(f"  已完成: {completed}/{CONCURRENT_USERS}")
    
    # 打印测试结果
    total_time = time.time() - start_time
    print("\n" + "="*60)
    print("测试完成")
    print("="*60)
    print(f"总耗时: {total_time:.2f} 秒")
    
    # 打印测试统计
    print_statistics("并发登录并查看公告栏", test_results['login_and_view_announcement'])
    
    # 生成测试报告
    report = {
        'test_time': datetime.now().isoformat(),
        'total_duration': total_time,
        'server_url': BASE_URL,
        'concurrent_users': CONCURRENT_USERS,
        'results': {}
    }
    
    results = test_results['login_and_view_announcement']
    report['results']['login_and_view_announcement'] = {
        'total': results['total'],
        'success': results['success'],
        'failed': results['failed'],
        'success_rate': (results['success'] / results['total'] * 100) if results['total'] > 0 else 0,
        'avg_response_time': statistics.mean(results['response_times']) if results['response_times'] else 0,
        'min_response_time': min(results['response_times']) if results['response_times'] else 0,
        'max_response_time': max(results['response_times']) if results['response_times'] else 0,
        'avg_login_time': statistics.mean(results['login_times']) if results['login_times'] else 0,
        'avg_page_load_time': statistics.mean(results['page_load_times']) if results['page_load_times'] else 0,
        'avg_api_load_time': statistics.mean(results['api_load_times']) if results['api_load_times'] else 0
    }
    
    # 保存测试报告
    report_file = f"stress_test_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(report_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    print(f"\n测试报告已保存到: {report_file}")
    print("="*60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n测试被用户中断")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n测试过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

