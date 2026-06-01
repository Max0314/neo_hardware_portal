#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
弱密码修复脚本
自动检测弱密码用户，并生成符合要求的随机密码（12位，大小写+数字+特殊符号）
"""
import os
import sys
import re
import random
import string
import logging
import json
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.db_adapter import get_connection_pool
from server.security import InputValidator, PasswordHasher

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# 常见弱密码列表
COMMON_WEAK_PASSWORDS = [
    '123456', 'password', '123456789', '12345678', '12345',
    '1234567', '1234567890', 'qwerty', 'abc123', '111111',
    '123123', 'admin', 'letmein', 'welcome', 'monkey',
    '1234', '12345678910', 'password123', 'root', 'toor',
    'pass', 'test', 'guest', 'user', 'login'
]


def generate_strong_password(length=12):
    """
    生成符合要求的强密码
    
    要求：
    - 至少12位
    - 包含大写字母
    - 包含小写字母
    - 包含数字
    - 包含特殊符号
    
    Args:
        length: 密码长度（默认12）
        
    Returns:
        强密码字符串
    """
    if length < 12:
        length = 12
    
    # 确保至少包含每种类型的字符
    uppercase = random.choice(string.ascii_uppercase)
    lowercase = random.choice(string.ascii_lowercase)
    digit = random.choice(string.digits)
    special = random.choice('!@#$%^&*()_+-=[]{}|;\':",./<>?')
    
    # 生成剩余字符（从所有字符类型中随机选择）
    all_chars = string.ascii_letters + string.digits + '!@#$%^&*()_+-=[]{}|;\':",./<>?'
    remaining = ''.join(random.choices(all_chars, k=length - 4))
    
    # 组合并打乱顺序
    password_chars = list(uppercase + lowercase + digit + special + remaining)
    random.shuffle(password_chars)
    
    password = ''.join(password_chars)
    
    # 验证生成的密码是否符合要求
    is_valid, reason = InputValidator.validate_password(password, check_strength=True)
    if not is_valid:
        # 如果不符合要求，重新生成
        logger.warning(f"生成的密码不符合要求: {reason}，重新生成...")
        return generate_strong_password(length)
    
    return password


def check_password_strength(password: str) -> tuple:
    """
    检查密码强度
    
    Returns:
        (is_weak, reason, strength_score)
    """
    if not password:
        return True, "密码为空", 0
    
    # 检查是否是常见弱密码
    if password.lower() in COMMON_WEAK_PASSWORDS:
        return True, "常见弱密码", 0
    
    # 检查长度
    if len(password) < 12:
        return True, f"密码长度不足12位（当前{len(password)}位）", 1
    
    # 检查复杂度
    has_lower = bool(re.search(r'[a-z]', password))
    has_upper = bool(re.search(r'[A-Z]', password))
    has_digit = bool(re.search(r'\d', password))
    has_special = bool(re.search(r'[!@#$%^&*()_+\-=\[\]{};\':"\\|,.<>/?]', password))
    
    missing = []
    if not has_lower:
        missing.append("小写字母")
    if not has_upper:
        missing.append("大写字母")
    if not has_digit:
        missing.append("数字")
    if not has_special:
        missing.append("特殊符号")
    
    if missing:
        return True, f"缺少：{', '.join(missing)}", 2
    
    # 检查是否是简单模式
    if re.match(r'^(.)\1+$', password):  # 重复字符
        return True, "密码为重复字符", 1
    
    if re.match(r'^[0-9]+$', password):  # 纯数字
        return True, "密码为纯数字", 1
    
    if re.match(r'^[a-zA-Z]+$', password):  # 纯字母
        return True, "密码为纯字母", 1
    
    # 检查连续字符
    if re.search(r'(012|123|234|345|456|567|678|789|890)', password):
        return True, "包含连续数字", 1
    
    if re.search(r'(abc|bcd|cde|def|efg|fgh|ghi|hij|ijk|jkl|klm|lmn|mno|nop|opq|pqr|qrs|rst|stu|tuv|uvw|wxy|xyz)', password.lower()):
        return True, "包含连续字母", 1
    
    return False, "密码强度符合要求", 5


def is_password_hashed(password):
    """检查密码是否已哈希"""
    if not password:
        return False
    # bcrypt哈希以$2b$或$2a$开头
    if password.startswith('$2b$') or password.startswith('$2a$'):
        return True
    # SHA-512哈希格式：sha512:salt:hash
    if password.startswith('sha512:'):
        return True
    # SHA-256哈希格式：salt:hash
    if ':' in password and len(password.split(':')) >= 2:
        return True
    return False


def fix_mysql_passwords(dry_run=False):
    """修复MySQL数据库中的弱密码（只修复明文密码，已哈希的密码无法检查强度）"""
    fixed_users = []
    
    try:
        pool = get_connection_pool()
        with pool.get_cursor() as cursor:
            cursor.execute('SELECT id, username, password, name FROM users')
            users = cursor.fetchall()
            
            for user in users:
                if isinstance(user, dict):
                    user_id = user['id']
                    username = user['username']
                    password = user.get('password', '')
                    name = user.get('name', '')
                else:
                    user_id = user[0]
                    username = user[1]
                    password = user[2] if len(user) > 2 else ''
                    name = user[3] if len(user) > 3 else ''
                
                # 检查密码是否已哈希
                if is_password_hashed(password):
                    # 已哈希，无法检查强度，跳过
                    logger.debug(f"用户 {username} 的密码已哈希，跳过")
                    continue
                
                # 检查密码强度
                is_weak, reason, score = check_password_strength(password)
                if is_weak:
                    # 生成新密码
                    new_password = generate_strong_password(12)
                    # 哈希新密码
                    hashed_password = PasswordHasher.hash_password(new_password)
                    
                    if not dry_run:
                        # 更新数据库
                        try:
                            cursor.execute(
                                'UPDATE users SET password = %s WHERE id = %s',
                                (hashed_password, user_id)
                            )
                            logger.info(f"✅ 已修复用户 {username} (ID={user_id}, 姓名={name}) 的密码")
                        except Exception as e:
                            logger.error(f"❌ 更新用户 {username} (ID={user_id}) 的密码失败: {e}")
                            continue
                    
                    fixed_users.append({
                        'source': 'MySQL',
                        'user_id': user_id,
                        'username': username,
                        'name': name,
                        'old_reason': reason,
                        'new_password': new_password,
                        'hashed': True
                    })
    
    except Exception as e:
        logger.error(f"修复MySQL密码失败: {e}", exc_info=True)
    
    return fixed_users


# Excel文件修复已移除，现在只使用数据库


def generate_password_report(fixed_users, output_file=None):
    """生成密码修复报告"""
    if not output_file:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = os.path.join(DATA_DIR, f'password_fix_report_{timestamp}.json')
    
    os.makedirs(DATA_DIR, exist_ok=True)
    
    report = {
        'fix_time': datetime.now().isoformat(),
        'total_fixed': len(fixed_users),
        'users': fixed_users
    }
    
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        logger.info(f"密码修复报告已保存到: {output_file}")
        return output_file
    except Exception as e:
        logger.error(f"保存密码修复报告失败: {e}")
        return None


def print_summary(fixed_users, dry_run=False):
    """打印修复摘要"""
    logger.info("=" * 60)
    if dry_run:
        logger.info(f"🔍 模拟运行：发现 {len(fixed_users)} 个弱密码用户（未实际修复）")
    else:
        logger.info(f"✅ 已修复 {len(fixed_users)} 个弱密码用户")
    logger.info("=" * 60)
    
    if not fixed_users:
        logger.info("未发现弱密码用户")
        return
    
    logger.info(f"\n数据库中的修复用户 ({len(fixed_users)} 个):")
    logger.info("-" * 60)
    for user in fixed_users:
        logger.info(f"  用户ID: {user['user_id']}")
        logger.info(f"  用户名: {user['username']}")
        logger.info(f"  姓名: {user['name']}")
        logger.info(f"  原问题: {user['old_reason']}")
        if not dry_run:
            logger.info(f"  新密码: {user['new_password']}")
        logger.info("")
    
    logger.info("=" * 60)
    if not dry_run:
        logger.info("⚠️  重要提示：")
        logger.info("1. 请妥善保管密码修复报告文件")
        logger.info("2. 及时通知用户修改密码")
        logger.info("3. 建议用户首次登录后立即修改密码")
        logger.info("4. 所有密码已使用强哈希算法（bcrypt/SHA-512）存储")
    logger.info("=" * 60)


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='修复弱密码用户')
    parser.add_argument('--dry-run', action='store_true', help='模拟运行，不实际修改密码')
    parser.add_argument('--report', type=str, help='密码修复报告文件路径（可选）')
    
    args = parser.parse_args()
    
    logger.info("=" * 60)
    logger.info("弱密码修复脚本启动")
    if args.dry_run:
        logger.info("⚠️  模拟运行模式（不会实际修改密码）")
    logger.info("=" * 60)
    
    all_fixed_users = []
    
    # 修复MySQL数据库（现在只使用数据库）
    logger.info("\n检查数据库中的弱密码...")
    logger.info("注意：只检查明文密码，已哈希的密码无法检查强度")
    mysql_users = fix_mysql_passwords(dry_run=args.dry_run)
    all_fixed_users.extend(mysql_users)
    
    # 打印摘要
    print_summary(all_fixed_users, dry_run=args.dry_run)
    
    # 生成报告
    if all_fixed_users:
        report_file = generate_password_report(all_fixed_users, args.report)
        if report_file:
            logger.info(f"\n密码修复报告: {report_file}")
    
    return len(all_fixed_users)


if __name__ == '__main__':
    try:
        fixed_count = main()
        if fixed_count > 0:
            logger.info(f"\n✅ 修复完成，共修复 {fixed_count} 个弱密码用户")
        else:
            logger.info("\n✅ 未发现需要修复的弱密码用户")
        sys.exit(0)
    except KeyboardInterrupt:
        logger.info("\n\n用户中断操作")
        sys.exit(1)
    except Exception as e:
        logger.error(f"\n❌ 修复失败: {e}", exc_info=True)
        sys.exit(1)

