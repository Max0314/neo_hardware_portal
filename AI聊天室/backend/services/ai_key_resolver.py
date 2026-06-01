"""统一解析 AI API Key：优先加密库，其次环境变量。永不向前端返回明文。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional, List, Any

from backend.models.ai_provider_keys import AI_KEY_PROVIDERS, get_provider
from backend.utils.crypto_vault import CryptoVault, mask_secret_hint

_vault: Optional[CryptoVault] = None
_store = None
_cache: Dict[str, str] = {}


def init_ai_key_resolver(message_store, data_dir: Path) -> None:
    global _store, _vault
    _store = message_store
    try:
        _vault = CryptoVault(data_dir)
    except Exception as e:
        _vault = None
        print(
            f"[vault] 密钥库初始化失败，API Key 仅能从环境变量读取: {e}"
        )
    _cache.clear()


def _env_key(env_var: str) -> str:
    return (os.getenv(env_var) or "").strip()


async def get_secret_async(provider_id: str) -> Optional[str]:
    if provider_id in _cache and _cache[provider_id]:
        return _cache[provider_id]

    prov = get_provider(provider_id)
    if not prov:
        return None

    secret: Optional[str] = None
    if _store and _vault:
        row = await _store.get_ai_secret(provider_id)
        if row and row.get("ciphertext"):
            try:
                secret = _vault.decrypt(row["ciphertext"]).strip() or None
            except ValueError:
                secret = None

    if not secret:
        secret = _env_key(prov["env_var"]) or None

    if secret:
        _cache[provider_id] = secret
    return secret


async def has_provider(provider_id: str) -> bool:
    return bool(await get_secret_async(provider_id))


def invalidate_provider(provider_id: str) -> None:
    _cache.pop(provider_id, None)


async def save_provider_secret(provider_id: str, api_key: str) -> None:
    if not _store or not _vault:
        raise RuntimeError("密钥库未初始化")
    key = (api_key or "").strip()
    if not key:
        raise ValueError("API Key 不能为空")
    ciphertext = _vault.encrypt(key)
    hint = mask_secret_hint(key)
    await _store.upsert_ai_secret(provider_id, ciphertext, hint)
    _cache[provider_id] = key


async def delete_provider_secret(provider_id: str) -> None:
    if not _store:
        raise RuntimeError("密钥库未初始化")
    await _store.delete_ai_secret(provider_id)
    invalidate_provider(provider_id)


async def list_providers_status() -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for prov in AI_KEY_PROVIDERS:
        pid = prov["id"]
        env_var = prov["env_var"]
        vault_row = await _store.get_ai_secret(pid) if _store else None
        in_vault = bool(vault_row and vault_row.get("ciphertext"))
        in_env = bool(_env_key(env_var))
        if in_vault:
            source = "vault"
            configured = True
            hint = vault_row.get("hint") or "••••••••"
        elif in_env:
            source = "env"
            configured = True
            hint = mask_secret_hint(_env_key(env_var))
        else:
            source = "none"
            configured = False
            hint = ""

        result.append(
            {
                "id": pid,
                "name": prov["name"],
                "description": prov.get("description", ""),
                "env_var": env_var,
                "configured": configured,
                "source": source,
                "hint": hint,
            }
        )
    return result
