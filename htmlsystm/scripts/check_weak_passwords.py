#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
弱密码检测脚本
检查系统中所有账号密码是否存在弱口令，并生成报告
"""
import os
import sys
import re
import logging

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
    
    # 检查是否是简单模式（如：12345678, abcdefgh等）
    if re.match(r'^(.)\1+$', password):  # 重复字符
        return True, "密码为重复字符", 1
    
    if re.match(r'^[0-9]+$', password):  # 纯数字
        return True, "密码为纯数字", 1
    
    if re.match(r'^[a-zA-Z]+$', password):  # 纯字母
        return True, "密码为纯字母", 1
    
    # 检查连续字符（如：123456, abcdef）
    if re.search(r'(012|123|234|345|456|567|678|789|890)', password):
        return True, "包含连续数字", 1
    
    if re.search(r'(abc|bcd|cde|def|efg|fgh|ghi|hij|ijk|jkl|klm|lmn|mno|nop|opq|pqr|qrs|rst|stu|tuv|uvw|vwx|wxy|xyz)', password.lower()):
        return True, "包含连续字母", 1
    
    return False, "密码强度符合要求", 5


def check_mysql_passwords():
    """检查MySQL数据库中的密码（只检查明文密码，已哈希的密码无法检查强度）"""
    weak_passwords = []
    
    try:
        pool = get_connection_pool()
        with pool.get_cursor() as cursor:
            cursor.execute('SELECT id, username, password FROM users')
            users = cursor.fetchall()
            
            for user in users:
                if isinstance(user, dict):
                    user_id = user['id']
                    username = user['username']
                    password = user.get('password', '')
                else:
                    user_id = user[0]
                    username = user[1]
                    password = user[2] if len(user) > 2 else ''
                
                # 检查密码是否已哈希
                is_hashed = (
                    password.startswith('$2b$') or 
                    password.startswith('$2a$') or
                    password.startswith('sha512:') or
                    (':' in password and len(password.split(':')) >= 2)
                )
                
                if not is_hashed:
                    # 明文密码，检查强度
                    is_weak, reason, score = check_password_strength(password)
                    if is_weak:
                        weak_passwords.append({
                            'source': 'MySQL',
                            'user_id': user_id,
                            'username': username,
                            'reason': reason,
                            'strength_score': score,
                            'is_hashed': False
                        })
                else:
                    # 已哈希，无法检查强度，但标记为已哈希
                    logger.debug(f"用户 {username} 的密码已哈希")
    
    except Exception as e:
        logger.error(f"检查MySQL密码失败: {e}", exc_info=True)
    
    return weak_passwords


# Excel文件检查已移除，现在只使用数据库


def generate_report(weak_passwords):
    """生成弱密码报告"""
    if not weak_passwords:
        logger.info("=" * 60)
        logger.info("✅ 未发现弱密码")
        logger.info("=" * 60)
        return
    
    logger.info("=" * 60)
    logger.info(f"⚠️  发现 {len(weak_passwords)} 个弱密码账号")
    logger.info("=" * 60)
    
    logger.info(f"\n数据库中的弱密码 ({len(weak_passwords)} 个):")
    logger.info("-" * 60)
    for pwd in weak_passwords:
        logger.info(f"  用户ID: {pwd['user_id']}, 用户名: {pwd['username']}")
        logger.info(f"    问题: {pwd['reason']}, 强度评分: {pwd['strength_score']}/5")
        logger.info("")
    
    logger.info("=" * 60)
    logger.info("建议措施:")
    logger.info("1. 立即修改所有弱密码账号的密码")
    logger.info("2. 设置密码策略：至少12位，包含大小写字母、数字和特殊符号")
    logger.info("3. 使用强哈希算法（bcrypt或SHA-512）存储密码")
    logger.info("4. 定期检查密码强度")
    logger.info("5. 运行修复脚本: python scripts/fix_weak_passwords.py")
    logger.info("=" * 60)


def main():
    """主函数"""
    logger.info("开始检查弱密码...")
    logger.info("注意：只检查明文密码，已哈希的密码无法检查强度")
    
    # 检查MySQL数据库
    logger.info("检查MySQL数据库中的密码...")
    mysql_weak = check_mysql_passwords()
    
    # 生成报告
    generate_report(mysql_weak)
    
    return len(mysql_weak)


if __name__ == '__main__':
    try:
        weak_count = main()
        sys.exit(0 if weak_count == 0 else 1)
    except Exception as e:
        logger.error(f"检查弱密码失败: {e}", exc_info=True)
        sys.exit(1)

