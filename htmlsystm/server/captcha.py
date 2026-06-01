#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
图形验证码模块
生成和验证图形验证码（MySQL 跨 worker 共享）
"""
import random
import string
import time
import hashlib
import secrets
import threading
from typing import Optional, Tuple
from io import BytesIO
from server.logger import logger
from server.db_adapter import get_connection_pool

# 尝试导入PIL（Pillow）
try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    logger.warning("Pillow未安装，验证码将使用纯文本模式")


class CaptchaManager:
    """验证码管理器 - 单例模式"""
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._initialized = True
        self._captchas: dict = {}
        self._cleanup_lock = threading.Lock()
        self.CAPTCHA_EXPIRE = 300
        self.CAPTCHA_LENGTH = 4
        self.CLEANUP_INTERVAL = 600
        self._start_cleanup_thread()
    
    def _table_exists(self) -> bool:
        try:
            pool = get_connection_pool()
            with pool.get_cursor() as cursor:
                cursor.execute('''
                    SELECT COUNT(*) as count
                    FROM information_schema.tables
                    WHERE table_schema = DATABASE()
                    AND table_name = 'captcha_tokens'
                ''')
                row = cursor.fetchone()
                if isinstance(row, dict):
                    return int(row.get('count', 0)) > 0
                return bool(row and int(row[0]) > 0)
        except Exception:
            return False

    @staticmethod
    def _hash_code(code: str) -> str:
        return hashlib.sha256(code.upper().strip().encode('utf-8')).hexdigest()

    def _save_captcha_db(self, token: str, code: str, expire_time: float) -> bool:
        if not self._table_exists():
            return False
        try:
            pool = get_connection_pool()
            with pool.get_cursor() as cursor:
                cursor.execute(
                    '''
                    INSERT INTO captcha_tokens (token, code_hash, expires_at)
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE code_hash = VALUES(code_hash), expires_at = VALUES(expires_at)
                    ''',
                    (token, self._hash_code(code), expire_time),
                )
            return True
        except Exception as e:
            logger.warning(f"保存验证码到数据库失败: {e}")
            return False

    def _verify_captcha_db(self, token: str, code: str) -> Optional[bool]:
        if not self._table_exists():
            return None
        current_time = time.time()
        try:
            pool = get_connection_pool()
            with pool.get_cursor() as cursor:
                cursor.execute(
                    'SELECT code_hash, expires_at FROM captcha_tokens WHERE token = %s',
                    (token,),
                )
                row = cursor.fetchone()
                if not row:
                    return None
                if isinstance(row, dict):
                    code_hash = row.get('code_hash', '')
                    expires_at = float(row.get('expires_at', 0))
                else:
                    code_hash, expires_at = row[0], float(row[1])
                if current_time > expires_at:
                    cursor.execute('DELETE FROM captcha_tokens WHERE token = %s', (token,))
                    return None
                if self._hash_code(code) != code_hash:
                    return False
                cursor.execute('DELETE FROM captcha_tokens WHERE token = %s', (token,))
                with self._cleanup_lock:
                    self._captchas.pop(token, None)
                return True
        except Exception as e:
            logger.warning(f"验证数据库验证码失败: {e}")
            return None

    def _cleanup_expired_captchas_db(self) -> None:
        if not self._table_exists():
            return
        try:
            pool = get_connection_pool()
            with pool.get_cursor() as cursor:
                cursor.execute('DELETE FROM captcha_tokens WHERE expires_at < %s', (time.time(),))
        except Exception as e:
            logger.debug(f"清理过期验证码失败: {e}")

    def _start_cleanup_thread(self):
        """启动清理线程"""
        def cleanup():
            while True:
                try:
                    time.sleep(self.CLEANUP_INTERVAL)
                    self._cleanup_expired_captchas()
                    self._cleanup_expired_captchas_db()
                except Exception as e:
                    logger.error(f"清理过期验证码失败: {e}", exc_info=True)
        
        thread = threading.Thread(target=cleanup, daemon=True)
        thread.start()
        logger.info("验证码管理器清理线程已启动")
    
    def _cleanup_expired_captchas(self):
        """清理过期的验证码（内存后备）"""
        current_time = time.time()
        with self._cleanup_lock:
            expired_tokens = [
                token for token, (_, expire_time) in self._captchas.items()
                if current_time > expire_time
            ]
            for token in expired_tokens:
                del self._captchas[token]
            if expired_tokens:
                logger.debug(f"清理了 {len(expired_tokens)} 个过期验证码")
    
    def generate_captcha(self) -> Tuple[str, bytes]:
        """
        生成验证码图片（如果Pillow不可用，返回纯文本验证码）
        
        Returns:
            (token, image_bytes)
        """
        chars = string.digits + string.ascii_uppercase
        chars = chars.replace('0', '').replace('O', '').replace('1', '').replace('I', '')
        code = ''.join(random.choices(chars, k=self.CAPTCHA_LENGTH))
        token = secrets.token_urlsafe(32)
        expire_time = time.time() + self.CAPTCHA_EXPIRE

        with self._cleanup_lock:
            self._captchas[token] = (code, expire_time)
        self._save_captcha_db(token, code, expire_time)
        
        if not HAS_PIL:
            svg_content = f'''<svg width="120" height="40" xmlns="http://www.w3.org/2000/svg">
                <rect width="120" height="40" fill="#f0f0f0" stroke="#ccc"/>
                <text x="60" y="25" font-family="Arial" font-size="20" font-weight="bold" text-anchor="middle" fill="#333">{code}</text>
            </svg>'''
            img_bytes = svg_content.encode('utf-8')
            logger.debug(f"生成纯文本验证码: token={token[:8]}..., code={code}")
        else:
            image = self._create_captcha_image(code)
            img_bytes_io = BytesIO()
            image.save(img_bytes_io, format='PNG')
            img_bytes_io.seek(0)
            img_bytes = img_bytes_io.getvalue()
            logger.debug(f"生成图片验证码: token={token[:8]}..., code={code}")
        
        return token, img_bytes
    
    def _create_captcha_image(self, code: str):
        """创建验证码图片（需要Pillow）"""
        if not HAS_PIL:
            raise ImportError("Pillow未安装，无法生成图片验证码")
        
        width, height = 120, 40
        image = Image.new('RGB', (width, height), color=(255, 255, 255))
        draw = ImageDraw.Draw(image)
        
        for _ in range(5):
            x1 = random.randint(0, width)
            y1 = random.randint(0, height)
            x2 = random.randint(0, width)
            y2 = random.randint(0, height)
            color = (random.randint(100, 200), random.randint(100, 200), random.randint(100, 200))
            draw.line([(x1, y1), (x2, y2)], fill=color, width=1)
        
        for _ in range(50):
            x = random.randint(0, width)
            y = random.randint(0, height)
            color = (random.randint(150, 255), random.randint(150, 255), random.randint(150, 255))
            draw.point((x, y), fill=color)
        
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 24)
        except Exception:
            try:
                font = ImageFont.truetype("arial.ttf", 24)
            except Exception:
                font = ImageFont.load_default()
        
        char_width = width // len(code)
        for i, char in enumerate(code):
            x = i * char_width + random.randint(8, 12)
            y = random.randint(8, 12)
            color = (random.randint(0, 100), random.randint(0, 100), random.randint(0, 100))
            draw.text((x, y), char, fill=color, font=font)
        
        return image
    
    def verify_captcha(self, token: str, code: str) -> bool:
        """
        验证验证码
        
        Args:
            token: 验证码token
            code: 用户输入的验证码
            
        Returns:
            是否验证通过
        """
        if not token or not code:
            return False

        db_result = self._verify_captcha_db(token, code)
        if db_result is not None:
            if db_result:
                logger.debug(f"验证码验证成功(DB): token={token[:8]}...")
            return db_result

        current_time = time.time()
        with self._cleanup_lock:
            if token not in self._captchas:
                return False
            stored_code, expire_time = self._captchas[token]
            if current_time > expire_time:
                del self._captchas[token]
                return False
            if code.upper().strip() == stored_code.upper().strip():
                del self._captchas[token]
                logger.debug(f"验证码验证成功: token={token[:8]}...")
                return True
            logger.debug(f"验证码验证失败: token={token[:8]}..., 输入={code}, 正确={stored_code}")
            return False


_captcha_manager = None
_captcha_manager_lock = threading.Lock()


def get_captcha_manager() -> CaptchaManager:
    """获取验证码管理器单例"""
    global _captcha_manager
    if _captcha_manager is None:
        with _captcha_manager_lock:
            if _captcha_manager is None:
                _captcha_manager = CaptchaManager()
    return _captcha_manager
