#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
查看用户密码信息并重置管理员密码
"""
import os
import sys

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.db_adapter import get_connection_pool
from server.security import PasswordHasher, SUPER_ADMIN_USERNAME
from server.admin_credentials import (
    CREDENTIALS_FILE,
    load_credentials,
    save_credentials,
    generate_random_password,
)
from server.user_manager import UserManager
import getpass


def _resolve_test_password(explicit: str = None) -> str:
    if explicit:
        return explicit
    cred = load_credentials()
    if cred and cred.get('password'):
        return cred['password']
    env_legacy = (os.getenv('SUPER_ADMIN_PASSWORD') or '').strip()
    if env_legacy:
        print('⚠️  检测到 .env 中 SUPER_ADMIN_PASSWORD，已不再用于登录；请用 --password 或 admin_credentials.json')
    return ''


def show_admin_credentials():
    cred = load_credentials()
    print("=" * 80)
    print("超级管理员凭据（data/admin_credentials.json）")
    print("=" * 80)
    if not cred:
        print("未找到凭据文件；若 zzw 已存在请用 --reset 设置密码并同步文件")
        print(f"路径: {CREDENTIALS_FILE}")
        return False
    print(f"用户名: {cred['username']}")
    print(f"密码:   {cred['password']}")
    print(f"文件:   {CREDENTIALS_FILE}")
    print("=" * 80)
    return True

def view_user_passwords():
    """查看所有用户的密码信息（不显示实际密码，只显示哈希状态）"""
    try:
        pool = get_connection_pool()
        with pool.get_cursor() as cursor:
            cursor.execute('SELECT id, username, name, password, status FROM users ORDER BY id')
            users = cursor.fetchall()
            
            print("=" * 80)
            print("用户密码信息（密码已哈希，无法查看原始密码）")
            print("=" * 80)
            print(f"{'ID':<6} {'用户名':<20} {'姓名':<15} {'密码状态':<20} {'账户状态':<10}")
            print("-" * 80)
            
            for user in users:
                if isinstance(user, dict):
                    user_id = user.get('id')
                    username = user.get('username', '')
                    name = user.get('name', '')
                    password = user.get('password', '')
                    status = user.get('status', '')
                else:
                    user_id = user[0]
                    username = user[1] if len(user) > 1 else ''
                    name = user[2] if len(user) > 2 else ''
                    password = user[3] if len(user) > 3 else ''
                    status = user[4] if len(user) > 4 else ''
                
                # 判断密码类型
                if not password:
                    pwd_status = "无密码"
                elif password.startswith('$2b$') or password.startswith('$2a$'):
                    pwd_status = "bcrypt哈希"
                elif password.startswith('sha512:'):
                    pwd_status = "SHA-512哈希"
                elif ':' in password:
                    pwd_status = "SHA-256哈希"
                else:
                    pwd_status = "⚠️ 明文密码"
                
                print(f"{user_id:<6} {username:<20} {name:<15} {pwd_status:<20} {status:<10}")
            
            print("=" * 80)
            return users
    except Exception as e:
        print(f"❌ 查看用户密码失败: {e}")
        import traceback
        traceback.print_exc()
        return []

def clear_login_blocks():
    """清除登录失败记录与 IP 封禁（内存 + 数据库，需配合 restart 或本函数）"""
    from server.security_manager import get_security_manager
    get_security_manager().clear_all_restrictions()
    print("已清除全部登录限制（Gunicorn 内存黑名单 + 数据库记录）")
    print("建议执行: docker compose restart htmlsystm")


def compare_login_paths(username='zzw', password=None):
    """对比直接认证 vs HTTP 登录，并检查 fork 修复是否已部署"""
    import importlib.util
    import pathlib

    password = _resolve_test_password(password)
    if not password:
        print("❌ 请指定 --password 或先执行 --show-admin / --reset")
        return
    print("=" * 80)
    print("登录路径对比")
    print("=" * 80)
    print(f"用户名: {username!r}")
    print(f"密码长度: {len(password or '')}")

    mgr = UserManager()
    direct = mgr.authenticate_user(username, password)
    login_only = mgr.authenticate_user_for_login(username, password)
    print(f"1a) authenticate_user: {'✅ OK' if direct else '❌ FAIL'}")
    print(f"1b) authenticate_user_for_login: {'✅ OK' if login_only else '❌ FAIL'}")

    import threading
    thread_result = {'ok': False, 'error': None}
    def _thread_auth():
        try:
            thread_result['ok'] = bool(UserManager().authenticate_user_for_login(username, password))
        except Exception as exc:
            thread_result['error'] = str(exc)
    t = threading.Thread(target=_thread_auth)
    t.start()
    t.join(timeout=15)
    thread_label = '✅ OK' if thread_result['ok'] else '❌ FAIL'
    if thread_result['error']:
        thread_label += f" ({thread_result['error']})"
    print(f"1c) 子线程 authenticate_user_for_login（模拟 gthread）: {thread_label}")

    fork_fix = importlib.util.find_spec('server.gunicorn_fork') is not None
    print(f"2) server.gunicorn_fork 模块: {'✅ 已部署' if fork_fix else '❌ 未部署（需 rebuild）'}")

    cfg_path = pathlib.Path(__file__).resolve().parent.parent / 'gunicorn_config.py'
    preload_off = False
    if cfg_path.is_file():
        cfg_text = cfg_path.read_text(encoding='utf-8')
        preload_off = 'preload_app = False' in cfg_text
    print(f"3) preload_app = False: {'✅' if preload_off else '❌ 仍为 True 或未找到（需 rebuild）'}")

    print("4a) HTTP 登录 Form（Gunicorn worker 路径）:")
    form_result = test_http_login(username, password, use_json=False)
    print("4b) HTTP 登录 JSON（Gunicorn worker 路径）:")
    json_result = test_http_login(username, password, use_json=True)
    print("=" * 80)
    if not fork_fix or not preload_off:
        print("⚠️  镜像可能未更新。请在宿主机执行:")
        print("   docker compose build --no-cache htmlsystm && docker compose up -d htmlsystm")
    elif not thread_result['ok']:
        print("⚠️  子线程认证失败：多为 PyMySQL 连接被 gthread 共享，需 rebuild 最新 mysql_connection_pool 修复")
    print("若 HTTP 仍失败，查看 worker 日志中的 db_verify= 字段:")
    print("   docker compose logs htmlsystm --tail 80 | grep -E '登录认证失败|db_verify'")


def test_http_login(username='zzw', password=None, use_json=False):
    """在容器内模拟 HTTP 登录，复现 Web 登录路径"""
    import urllib.request
    import urllib.parse
    import json
    password = _resolve_test_password(password)
    if not password:
        print("❌ 请指定 --password 或先 --show-admin")
        return None
    if use_json:
        body = json.dumps({'username': username, 'password': password}).encode('utf-8')
        content_type = 'application/json'
        label = 'JSON'
    else:
        body = urllib.parse.urlencode({'username': username, 'password': password}).encode('utf-8')
        content_type = 'application/x-www-form-urlencoded'
        label = 'Form'
    req = urllib.request.Request(
        'http://127.0.0.1:8000/api/auth/login',
        data=body,
        headers={'Content-Type': content_type},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode('utf-8')
            print(f'HTTP {label}', resp.status)
            print(json.dumps(json.loads(raw), ensure_ascii=False, indent=2))
            return json.loads(raw)
    except Exception as e:
        print(f'HTTP {label} 登录失败:', e)
        if hasattr(e, 'read'):
            print(e.read().decode('utf-8', errors='replace'))
        return None


def reset_admin_password(username=None, new_password=None, use_env_password=False):
    """重置管理员密码"""
    try:
        if use_env_password:
            print("❌ --use-env 已废弃：请勿在 .env 配置 SUPER_ADMIN_PASSWORD，请使用 --password")
            return False

        pool = get_connection_pool()

        if not username:
            username = SUPER_ADMIN_USERNAME or None
        if not username:
            with pool.get_cursor() as cursor:
                cursor.execute("SELECT username FROM users WHERE roles LIKE '%admin%' OR roles LIKE '%super_admin%' LIMIT 1")
                result = cursor.fetchone()
                if result:
                    username = result.get('username') if isinstance(result, dict) else result[0]

        if not username:
            print("❌ 未找到管理员账号")
            return False

        if not new_password:
            new_password = generate_random_password()
            print(f"未指定 --password，已随机生成新密码（长度 {len(new_password)}）")

        if not new_password or len(new_password) < 12:
            print(f"❌ 密码无效：长度至少 12 位（当前 {len(new_password or '')}）")
            return False

        hashed_password = PasswordHasher.hash_password(new_password)

        from server.auth.password_service import get_password_service
        pwd_svc = get_password_service()
        user_row_id = None
        with pool.get_cursor() as cursor:
            cursor.execute('SELECT id FROM users WHERE username = %s', (username,))
            row = cursor.fetchone()
            if row:
                user_row_id = row['id'] if isinstance(row, dict) else row[0]

        if user_row_id is None:
            print(f"❌ 未找到用户: {username}")
            return False

        ok, msg, meta = pwd_svc.admin_reset_password(int(user_row_id), new_password, skip_strength=False)
        if not ok:
            print(f"❌ {msg}")
            return False

        with pool.get_cursor() as cursor:
            cursor.execute('UPDATE users SET status = %s, updated_time = NOW() WHERE username = %s', ('active', username))

        # 校验哈希是否可用
        if not PasswordHasher.verify_password(new_password, hashed_password):
            print("❌ 密码哈希校验失败，请检查 bcrypt 是否安装")
            return False

        with pool.get_cursor() as cursor:
            cursor.execute('SELECT password FROM users WHERE username = %s', (username,))
            row = cursor.fetchone()
            db_hash = row['password'] if isinstance(row, dict) else row[0]
        if not PasswordHasher.verify_password(new_password, db_hash):
            print("❌ 数据库中的哈希与明文不匹配，UPDATE 可能未提交")
            return False

        user = UserManager().authenticate_user_for_login(username, new_password)
        if not user:
            print("❌ 数据库哈希正确但登录认证仍失败，请 rebuild htmlsystm（password strip 修复）")
            return False

        if username == SUPER_ADMIN_USERNAME:
            save_credentials(username, new_password)

        print("=" * 80)
        print(f"✅ 成功重置用户 '{username}' 的密码")
        print("=" * 80)
        print(f"登录用户名: {username}")
        print(f"登录密码:   {new_password}")
        print("=" * 80)
        print("⚠️  请用以上密码登录；登录成功后建议立即修改密码")
        print("⚠️  已清除该用户全部会话；各客户端请关闭「自动登录」并使用新密码")
        print(f"   （sessions_removed={meta.get('sessionsRemoved', '?')}）")
        print("=" * 80)
        return True
    except Exception as e:
        print(f"❌ 重置密码失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def diagnose_login(username='zzw', test_password: str = None):
    """诊断登录环境：凭据文件、数据库哈希、bcrypt 校验"""
    print("=" * 80)
    print("登录诊断")
    print("=" * 80)
    print(f"SUPER_ADMIN_USERNAME (env): {SUPER_ADMIN_USERNAME!r}")
    cred = load_credentials()
    if cred:
        print(f"admin_credentials.json: 用户={cred['username']!r}, 密码长度={len(cred['password'])}")
    else:
        print(f"admin_credentials.json: ❌ 不存在 ({CREDENTIALS_FILE})")
    env_legacy = (os.getenv('SUPER_ADMIN_PASSWORD') or '').strip()
    if env_legacy:
        print(f"⚠️  .env 仍有 SUPER_ADMIN_PASSWORD（长度 {len(env_legacy)}），已不再用于 zzw 登录")
    try:
        import bcrypt
        print(f"bcrypt: 已安装 {getattr(bcrypt, '__version__', 'ok')}")
    except ImportError:
        print("bcrypt: ❌ 未安装 — $2b$ 哈希密码无法验证！")

    pool = get_connection_pool()
    with pool.get_cursor() as cursor:
        cursor.execute('SELECT username, status, password FROM users WHERE username = %s', (username,))
        row = cursor.fetchone()
    if not row:
        print(f"用户 {username} 不存在")
        return
    stored = row['password'] if isinstance(row, dict) else row[2]
    status = row['status'] if isinstance(row, dict) else row[1]
    print(f"DB status: {status}")
    print(f"DB password prefix: {str(stored)[:20]}...")

    if cred and cred.get('password'):
        ok = PasswordHasher.verify_password(cred['password'], stored)
        print(f"  verify 凭据文件密码: {'✅' if ok else '❌ 与数据库不一致，请 --reset 同步'}")
    if test_password:
        ok = PasswordHasher.verify_password(test_password, stored)
        print(f"  verify --password 参数: {'✅' if ok else '❌'}")
        login_ok = UserManager().authenticate_user_for_login(username, test_password)
        print(f"  authenticate_user_for_login: {'✅' if login_ok else '❌'}")
    print("=" * 80)

def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='查看用户密码信息并重置管理员密码')
    parser.add_argument('--view', action='store_true', help='查看所有用户的密码信息')
    parser.add_argument('--diagnose', type=str, nargs='?', const='zzw', help='诊断指定用户登录环境')
    parser.add_argument('--reset', type=str, nargs='?', const='', help='重置指定用户的密码（不指定则重置 SUPER_ADMIN_USERNAME）')
    parser.add_argument('--password', type=str, help='指定新密码（至少12位）；不指定则随机生成')
    parser.add_argument('--show-admin', action='store_true', help='显示 admin_credentials.json 中的 zzw 密码')
    parser.add_argument('--use-env', action='store_true', help='(已废弃)')
    parser.add_argument('--clear-blocks', action='store_true', help='清除登录失败记录与 IP 封禁')
    parser.add_argument('--test-login', type=str, nargs='?', const='zzw', help='在容器内模拟 HTTP 登录测试')
    parser.add_argument('--compare', type=str, nargs='?', const='zzw', help='对比直接认证与 HTTP 登录，检查修复是否已部署')
    
    args = parser.parse_args()
    
    if args.show_admin:
        show_admin_credentials()
    if args.clear_blocks:
        clear_login_blocks()
        print("⚠️  清除封禁后必须 restart htmlsystm，否则 Gunicorn worker 内存里仍有旧记录")
    if args.compare is not None:
        compare_login_paths(args.compare or 'zzw', args.password)
    elif args.test_login is not None:
        test_http_login(args.test_login or 'zzw', args.password)
    if args.view:
        view_user_passwords()
    elif args.diagnose is not None:
        diagnose_login(args.diagnose or 'zzw', test_password=args.password)
    elif args.test_login is not None or args.compare is not None:
        pass
    elif args.reset is not None:
        username = args.reset if args.reset else None
        reset_admin_password(username, new_password=args.password, use_env_password=args.use_env)
    elif not args.clear_blocks and args.test_login is None and not args.show_admin:
        view_user_passwords()
        print("\n")
        print("使用方法:")
        print("  python scripts/view_and_reset_admin_password.py --show-admin")
        print("  python scripts/view_and_reset_admin_password.py --diagnose zzw")
        print("  python scripts/view_and_reset_admin_password.py --clear-blocks")
        print("  docker compose restart htmlsystm   # clear-blocks 后必须执行")
        print("  python scripts/view_and_reset_admin_password.py --compare zzw --password '...'")
        print("  python scripts/view_and_reset_admin_password.py --reset zzw --password 'YourPass123!'")
        print("  bash migration/check-db-config.sh")

if __name__ == '__main__':
    main()

