#!/usr/bin/env python3
"""
在服务器上设置 / 查看 / 删除 NEO 加密库中的 AI API Key（不经过 Web 界面）。

示例（统一部署，容器名 stack-neo-backend）：
  docker exec stack-neo-backend python -m backend.scripts.set_ai_key list
  docker exec stack-neo-backend python -m backend.scripts.set_ai_key set deepseek 'sk-xxxxxxxx'
  docker exec stack-neo-backend python -m backend.scripts.set_ai_key delete deepseek

provider_id: deepseek | bailian | doubao | gpt-4 | claude-3 | gemini
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

# 保证 /app 在 path（Docker WORKDIR=/app）
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.models.message import MessageStore
from backend.services.ai_key_resolver import (
    delete_provider_secret,
    init_ai_key_resolver,
    list_providers_status,
    save_provider_secret,
)
from backend.models.ai_provider_keys import get_provider, AI_KEY_PROVIDERS


def _data_dir() -> Path:
    raw = (os.getenv("CHATROOM_DATA_DIR") or "").strip()
    return Path(raw) if raw else Path("/data")


async def _cmd_list() -> int:
    rows = await list_providers_status()
    for r in rows:
        status = "OK" if r["configured"] else "--"
        src = r["source"]
        hint = r["hint"] or ""
        print(f"{r['id']:10} {status:3}  [{src:5}]  {r['name']:<18}  {hint}")
    return 0


async def _cmd_set(provider_id: str, api_key: str) -> int:
    if not get_provider(provider_id):
        print(f"未知 provider_id: {provider_id}", file=sys.stderr)
        print("可选:", ", ".join(p["id"] for p in AI_KEY_PROVIDERS), file=sys.stderr)
        return 1
    key = (api_key or "").strip()
    if not key:
        print("API Key 不能为空", file=sys.stderr)
        return 1
    await save_provider_secret(provider_id, key)
    print(f"已加密保存: {provider_id}")
    return 0


async def _cmd_delete(provider_id: str) -> int:
    if not get_provider(provider_id):
        print(f"未知 provider_id: {provider_id}", file=sys.stderr)
        return 1
    await delete_provider_secret(provider_id)
    print(f"已删除加密库中的密钥: {provider_id}（仍可使用环境变量）")
    return 0


async def _main_async(args: argparse.Namespace) -> int:
    data_dir = _data_dir()
    db_path = str(data_dir / "chatroom.db")
    store = MessageStore(db_path=db_path)
    init_ai_key_resolver(store, data_dir)

    if args.command == "list":
        return await _cmd_list()
    if args.command == "set":
        return await _cmd_set(args.provider_id, args.api_key)
    if args.command == "delete":
        return await _cmd_delete(args.provider_id)
    return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="NEO AI API Key 管理（加密入库）")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="查看各模型密钥是否已配置（仅掩码）")

    p_set = sub.add_parser("set", help="保存 API Key（Fernet 加密）")
    p_set.add_argument("provider_id", help="如 deepseek")
    p_set.add_argument("api_key", help="密钥明文，建议用单引号包裹")

    p_del = sub.add_parser("delete", help="删除加密库中的 Key")
    p_del.add_argument("provider_id")

    args = parser.parse_args()
    code = asyncio.run(_main_async(args))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
