"""记忆召回与写入编排。"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from backend.memory.embedding import generate_embedding
from backend.memory.types import MemoryRecallContext, MemoryScopeType
from backend.memory.vector_backend import VectorMemoryBackend
from backend.models.memory_store import MemoryItemStore


def _chroma_where_for_scope(
    scope_level: str, ctx: MemoryRecallContext
) -> Optional[Dict[str, Any]]:
    """构建 Chroma metadata 过滤（值均为字符串）。"""

    def eq(k: str, v: str) -> Dict[str, Any]:
        return {k: {"$eq": v}}

    if scope_level == "conversation":
        if not ctx.conversation_id:
            return None
        return {
            "$and": [
                eq("scope_type", MemoryScopeType.CONVERSATION.value),
                eq("conversation_id", ctx.conversation_id),
            ]
        }
    if scope_level == "user_assistant":
        if not ctx.user_id or not ctx.assistant_id:
            return None
        return {
            "$and": [
                eq("scope_type", MemoryScopeType.USER_ASSISTANT.value),
                eq("user_id", ctx.user_id),
                eq("assistant_id", ctx.assistant_id),
            ]
        }
    if scope_level == "group":
        if not ctx.group_id:
            return None
        return {
            "$and": [
                eq("scope_type", MemoryScopeType.GROUP.value),
                eq("group_id", ctx.group_id),
            ]
        }
    if scope_level == "user":
        if not ctx.user_id:
            return None
        return {"$and": [eq("scope_type", MemoryScopeType.USER.value), eq("user_id", ctx.user_id)]}
    if scope_level == "assistant":
        if not ctx.assistant_id:
            return None
        return {
            "$and": [
                eq("scope_type", MemoryScopeType.ASSISTANT.value),
                eq("assistant_id", ctx.assistant_id),
            ]
        }
    if scope_level == "global_org":
        if not ctx.org_id:
            return None
        return {
            "$and": [
                eq("scope_type", MemoryScopeType.GLOBAL_ORG.value),
                eq("org_id", ctx.org_id),
            ]
        }
    return None


def _vector_metadata_flat(item: Dict[str, Any]) -> Dict[str, str]:
    return {
        "scope_type": str(item.get("scope_type", "")),
        "org_id": str(item.get("org_id", "")),
        "group_id": str(item.get("group_id", "")),
        "user_id": str(item.get("user_id", "")),
        "assistant_id": str(item.get("assistant_id", "")),
        "conversation_id": str(item.get("conversation_id", "")),
        "template_id": str(item.get("template_id", "")),
        "kind": str(item.get("kind", "")),
    }


class MemoryService:
    def __init__(
        self,
        store: MemoryItemStore,
        vector: Optional[VectorMemoryBackend],
    ):
        self._store = store
        self._vector = vector

    async def recall_for_prompt(self, ctx: MemoryRecallContext) -> str:
        """生成可注入 system 或 user 的补充文本块。"""
        if not self._vector or not ctx.query.strip():
            return ""
        strategy = await self._store.get_recall_strategy()
        qvec = await generate_embedding(ctx.query[:4000])
        seen: set[str] = set()
        chunks: List[str] = []

        for step in strategy.steps:
            where = _chroma_where_for_scope(step.scope_level, ctx)
            if not where:
                continue
            try:
                hits = await self._vector.search(qvec, where, step.top_k)
            except Exception as e:
                print(f"[memory.recall] search 失败 ({step.scope_level}): {e}")
                continue
            for h in hits:
                mid = h.get("memory_item_id") or ""
                if not mid or mid in seen:
                    continue
                seen.add(mid)
                row = await self._store.get_memory_item(mid)
                if row:
                    title = (row.get("search_text") or h.get("document") or "")[:500]
                    kind = row.get("kind", "")
                    sj = row.get("structured_json", "")
                    chunks.append(f"- [{kind}] {title}\n  数据: {sj[:800]}")
                else:
                    chunks.append(f"- {h.get('document', '')[:500]}")

        if not chunks:
            return ""
        lines = chunks[: strategy.max_total]
        return (
            "【结构化记忆召回】\n"
            + "\n".join(lines)
            + "\n（以上由记忆库按语义检索，供你参考；若与当前问题无关可忽略。）"
        )

    async def persist_item_with_vector(
        self,
        item_id: str,
        scope_type: MemoryScopeType,
        org_id: str,
        group_id: str,
        user_id: str,
        assistant_id: str,
        conversation_id: str,
        template_id: str,
        template_version: int,
        kind: str,
        structured_obj: Any,
        source_refs: List[str],
        confidence: float,
    ) -> None:
        structured_json = json.dumps(structured_obj, ensure_ascii=False)
        search_text = self._build_search_text(kind, structured_obj)
        await self._store.insert_memory_item(
            item_id=item_id,
            scope_type=scope_type.value,
            org_id=org_id,
            group_id=group_id,
            user_id=user_id,
            assistant_id=assistant_id,
            conversation_id=conversation_id,
            template_id=template_id,
            template_version=template_version,
            kind=kind,
            structured_json=structured_json,
            search_text=search_text,
            source_refs=source_refs,
            confidence=confidence,
            supersedes_id=None,
        )
        if self._vector:
            vec = await generate_embedding(search_text[:8000])
            meta = {
                "scope_type": scope_type.value,
                "org_id": org_id or "",
                "group_id": group_id or "",
                "user_id": user_id or "",
                "assistant_id": assistant_id or "",
                "conversation_id": conversation_id or "",
                "template_id": template_id,
                "kind": kind,
            }
            await self._vector.upsert(item_id, vec, search_text, meta)

    @staticmethod
    def _build_search_text(kind: str, structured_obj: Any) -> str:
        if isinstance(structured_obj, dict):
            parts = []
            for k in ("title", "summary", "traits", "preferences", "facts", "entities"):
                v = structured_obj.get(k)
                if v:
                    parts.append(f"{k}: {v}")
            if parts:
                return "\n".join(parts)[:8000]
            return json.dumps(structured_obj, ensure_ascii=False)[:8000]
        return str(structured_obj)[:8000]
