"""服务端密钥加密存储（Fernet）。主密钥仅存于环境变量或数据目录受保护文件，不落库明文。"""

from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


class CryptoVault:
    def __init__(self, data_dir: Path):
        self._fernet = Fernet(self._resolve_master_key(data_dir))

    @staticmethod
    def _resolve_master_key(data_dir: Path) -> bytes:
        env_key = (os.getenv("CHATROOM_SECRETS_MASTER_KEY") or "").strip()
        if env_key:
            try:
                key_bytes = env_key.encode("utf-8") if isinstance(env_key, str) else env_key
                Fernet(key_bytes)
                return key_bytes
            except Exception as e:
                print(
                    f"[vault] CHATROOM_SECRETS_MASTER_KEY 无效，将改用数据目录 .vault_master: {e}"
                )

        master_path = data_dir / ".vault_master"
        if master_path.is_file():
            raw = master_path.read_text(encoding="utf-8").strip()
            if raw:
                return raw.encode()

        key = Fernet.generate_key()
        data_dir.mkdir(parents=True, exist_ok=True)
        master_path.write_text(key.decode(), encoding="utf-8")
        try:
            os.chmod(master_path, 0o600)
        except OSError:
            pass
        print(
            "[vault] 已在数据目录生成加密主密钥文件 .vault_master；"
            "生产环境建议设置 CHATROOM_SECRETS_MASTER_KEY 并备份主密钥。"
        )
        return key

    def encrypt(self, plaintext: str) -> str:
        if not plaintext:
            raise ValueError("无法加密空字符串")
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
        except InvalidToken as e:
            raise ValueError("密钥解密失败，主密钥可能已更换") from e


def mask_secret_hint(secret: str, visible_tail: int = 4) -> str:
    s = (secret or "").strip()
    if not s:
        return ""
    if len(s) <= visible_tail:
        return "•" * len(s)
    return "•" * 8 + s[-visible_tail:]
