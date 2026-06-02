"""与 vector_store 一致的异步嵌入生成（OpenAI 或哈希回退）。"""
from __future__ import annotations

import hashlib
import os
from typing import List


async def generate_embedding(text: str) -> List[float]:
    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key:
        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=openai_key)
            response = await client.embeddings.create(
                model="text-embedding-3-small",
                input=text[:8000],
            )
            return list(response.data[0].embedding)
        except Exception as e:
            if not getattr(generate_embedding, "_warned", False):
                print(f"[memory.embedding] OpenAI 嵌入失败: {e}，使用哈希回退")
                generate_embedding._warned = True  # type: ignore[attr-defined]

    hash_obj = hashlib.sha256(text.encode("utf-8", errors="ignore"))
    hash_bytes = hash_obj.digest()
    return [
        (hash_bytes[i % len(hash_bytes)] / 255.0) * 2 - 1 for i in range(1536)
    ]
