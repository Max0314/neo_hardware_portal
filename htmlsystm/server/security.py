#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
安全模块
提供密码哈希、输入验证等安全功能
"""
import hashlib
import secrets
import re
import os
from typing import Optional, Tuple, List

# 尝试导入bcrypt（如果可用）
try:
    import bcrypt
    HAS_BCRYPT = True
except ImportError:
    HAS_BCRYPT = False

# 从环境变量读取超级管理员凭据（如果设置了）
SUPER_ADMIN_USERNAME = os.getenv('SUPER_ADMIN_USERNAME', 'zzw')
def _strip_env_quotes(value: str) -> str:
    if value and len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
        return value[1:-1]
    return value


# 已废弃：zzw 登录密码由 data/admin_credentials.json 管理，勿再设置 SUPER_ADMIN_PASSWORD
SUPER_ADMIN_PASSWORD = ''


class PasswordHasher:
    """密码哈希工具类 - 使用强哈希算法（bcrypt或SHA-512）"""
    
    @staticmethod
    def hash_password(password: str) -> str:
        """
        哈希密码 - 使用强哈希算法
        
        Args:
            password: 明文密码
            
        Returns:
            哈希后的密码
        """
        if HAS_BCRYPT:
            # 使用bcrypt（推荐，自适应成本因子）
            salt = bcrypt.gensalt(rounds=12)  # 增加成本因子提高安全性
            return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')
        else:
            # 使用SHA-512 + salt（强哈希算法，替代SHA-256）
            salt = secrets.token_hex(32)  # 64字符的随机salt
            hash_obj = hashlib.sha512()
            hash_obj.update((password + salt).encode('utf-8'))
            return f"sha512:{salt}:{hash_obj.hexdigest()}"
    
    @staticmethod
    def verify_password(password: str, hashed: str) -> bool:
        """
        验证密码 - 支持多种哈希格式（向后兼容）
        
        Args:
            password: 明文密码
            hashed: 哈希后的密码
            
        Returns:
            是否匹配
        """
        if not password or not hashed:
            return False
        
        # bcrypt格式（以$2b$开头）
        if hashed.startswith('$2b$') or hashed.startswith('$2a$'):
            if HAS_BCRYPT:
                try:
                    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
                except:
                    return False
            else:
                return False
        
        # SHA-512格式：sha512:salt:hash
        if hashed.startswith('sha512:'):
            try:
                _, salt, stored_hash = hashed.split(':', 2)
                hash_obj = hashlib.sha512()
                hash_obj.update((password + salt).encode('utf-8'))
                return hash_obj.hexdigest() == stored_hash
            except:
                return False
        
        # SHA-256格式（旧格式，向后兼容）：salt:hash
        if ':' in hashed and not hashed.startswith('sha512:'):
            try:
                parts = hashed.split(':', 1)
                if len(parts) == 2:
                    salt, stored_hash = parts
                    # 检查是否是SHA-256格式（64字符的hex）
                    if len(stored_hash) == 64:
                        hash_obj = hashlib.sha256()
                        hash_obj.update((password + salt).encode('utf-8'))
                        return hash_obj.hexdigest() == stored_hash
            except:
                pass
        
        # 旧格式（明文）不再支持；请运行 password_service.audit_passwords 迁移
        return False


class InputValidator:
    """输入验证工具类"""
    
    # 用户名规则：3-20个字符，只能包含字母、数字、下划线
    USERNAME_PATTERN = re.compile(r'^[a-zA-Z0-9_]{3,20}$')
    
    # 密码规则：至少12个字符，必须包含大小写字母、数字和特殊符号
    MIN_PASSWORD_LENGTH = 12
    
    @staticmethod
    def validate_username(username: str) -> Tuple[bool, Optional[str]]:
        """
        验证用户名
        
        Args:
            username: 用户名
            
        Returns:
            (是否有效, 错误消息)
        """
        if not username:
            return False, "用户名不能为空"
        
        if not InputValidator.USERNAME_PATTERN.match(username):
            return False, "用户名只能包含字母、数字和下划线，长度3-20个字符"
        
        return True, None
    
    @staticmethod
    def validate_password(password: str, check_strength: bool = True) -> Tuple[bool, Optional[str]]:
        """
        验证密码强度
        
        Args:
            password: 密码
            check_strength: 是否检查密码强度（默认True）
            
        Returns:
            (是否有效, 错误消息)
        """
        if not password:
            return False, "密码不能为空"
        
        # 检查最小长度
        if len(password) < InputValidator.MIN_PASSWORD_LENGTH:
            return False, f"密码长度至少{InputValidator.MIN_PASSWORD_LENGTH}个字符"
        
        # 如果不需要检查强度（用于登录验证），只检查长度
        if not check_strength:
            return True, None
        
        # 检查密码强度：必须包含大小写字母、数字和特殊符号
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
            return False, f"密码必须包含：{', '.join(missing)}"
        
        return True, None
    
    @staticmethod
    def check_password_strength(password: str) -> Tuple[bool, str, int]:
        """
        检查密码强度并返回详细信息
        
        Args:
            password: 密码
            
        Returns:
            (是否通过, 强度描述, 强度等级 0-4)
        """
        if not password:
            return False, "密码为空", 0
        
        score = 0
        feedback = []
        
        # 长度检查
        if len(password) >= 12:
            score += 1
        else:
            feedback.append("长度不足12位")
        
        # 复杂度检查
        has_lower = bool(re.search(r'[a-z]', password))
        has_upper = bool(re.search(r'[A-Z]', password))
        has_digit = bool(re.search(r'\d', password))
        has_special = bool(re.search(r'[!@#$%^&*()_+\-=\[\]{};\':"\\|,.<>/?]', password))
        
        if has_lower:
            score += 1
        else:
            feedback.append("缺少小写字母")
        
        if has_upper:
            score += 1
        else:
            feedback.append("缺少大写字母")
        
        if has_digit:
            score += 1
        else:
            feedback.append("缺少数字")
        
        if has_special:
            score += 1
        else:
            feedback.append("缺少特殊符号")
        
        # 强度等级描述
        if score == 5:
            strength_desc = "强"
        elif score >= 3:
            strength_desc = "中等"
        else:
            strength_desc = "弱"
        
        is_valid = score == 5
        message = strength_desc if is_valid else f"密码强度不足：{', '.join(feedback)}"
        
        return is_valid, message, score
    
    @staticmethod
    def sanitize_string(value: str, max_length: int = 1000) -> str:
        """
        清理字符串输入
        
        Args:
            value: 输入字符串
            max_length: 最大长度
            
        Returns:
            清理后的字符串
        """
        if not value:
            return ''
        
        # 移除控制字符（保留换行和制表符）
        cleaned = ''.join(char for char in value if ord(char) >= 32 or char in '\n\t')
        
        # 限制长度
        if len(cleaned) > max_length:
            cleaned = cleaned[:max_length]
        
        return cleaned
    
    @staticmethod
    def validate_file_extension(filename: str, allowed_extensions: List[str]) -> Tuple[bool, Optional[str]]:
        """
        验证文件扩展名
        
        Args:
            filename: 文件名
            allowed_extensions: 允许的扩展名列表（如 ['.xlsx', '.pdf']）
            
        Returns:
            (是否有效, 错误消息)
        """
        if not filename:
            return False, "文件名不能为空"
        
        ext = os.path.splitext(filename)[1].lower()
        if ext not in allowed_extensions:
            return False, f"不允许的文件类型，只允许: {', '.join(allowed_extensions)}"
        
        return True, None

