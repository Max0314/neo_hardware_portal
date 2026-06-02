"""近实时记忆抽取：有界队列 + 后台 worker。"""
from __future__ import annotations

import asyncio
import json
import os
import re
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from backend.memory.types import ExtractJob, MemoryScopeType
from backend.models.memory_store import MemoryItemStore

if TYPE_CHECKING:
    from backend.memory.memory_service import MemoryService
    from backend.models.message import MessageStore

_extract_queue: Optional[asyncio.Queue[ExtractJob]] = None


def init_extract_queue(maxsize: int = 500) -> None:
    global _extract_queue
    _extract_queue = asyncio.Queue(maxsize=maxsize)


def enqueue_extract(job: ExtractJob) -> bool:
    if _extract_queue is None:
        return False
    try:
        _extract_queue.put_nowait(job)
        return True
    except asyncio.QueueFull:
        print("[memory.extract] 队列已满，丢弃抽取任务")
        return False


def _parse_json_object(text: str) -> Optional[Dict[str, Any]]:
    text = (text or "").strip()
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


async def _llm_extract_json(dialog: str, template: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    from backend.services.ai_key_resolver import get_secret_async

    api_key = await get_secret_async("deepseek")
    if not api_key:
        print("[memory.extract] DeepSeek API Key 未配置，跳过 LLM 抽取")
        return None
    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=api_key, base_url="https://api.deepseek.com")
        schema_hint = (template.get("json_schema") or "")[:3000]
        hint = template.get("prompt_hint") or ""
        sys = (
            "你是信息抽取助手。只输出一个 JSON 对象，不要 markdown 代码围栏，不要其它说明。\n"
            f"抽取要求：{hint}\n"
            f"目标结构（JSON Schema 片段）：\n{schema_hint}"
        )
        resp = await client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": sys},
                {
                    "role": "user",
                    "content": f"以下是对话片段，请抽取信息：\n\n{dialog[:12000]}",
                },
            ],
            temperature=0.2,
            max_tokens=1024,
        )
        raw = (resp.choices[0].message.content or "").strip()
        return _parse_json_object(raw)
    except Exception as e:
        print(f"[memory.extract] LLM 调用失败: {e}")
        return None


async def _process_one_template(
    job: ExtractJob,
    template: Dict[str, Any],
    dialog: str,
    mem_store: MemoryItemStore,
    memory_service: "MemoryService",
) -> None:
    tid = template["id"]
    data = await _llm_extract_json(dialog, template)
    if not data:
        return
    if not await mem_store.try_mark_extraction(job.conversation_id, job.message_id, tid):
        return
    kind = template.get("kind", "note")
    item_id = mem_store.new_id()
    version = int(template.get("version") or 1)
    gid = job.group_id or job.conversation_id
    if kind == "profile":
        scope = MemoryScopeType.USER
        conv = ""
        asst = ""
    else:
        scope = MemoryScopeType.CONVERSATION
        conv = job.conversation_id
        asst = ""
    await memory_service.persist_item_with_vector(
        item_id=item_id,
        scope_type=scope,
        org_id=job.org_id,
        group_id=gid,
        user_id=job.user_id,
        assistant_id=asst,
        conversation_id=conv,
        template_id=tid,
        template_version=version,
        kind=kind,
        structured_obj=data,
        source_refs=[job.message_id],
        confidence=0.75,
    )


async def process_extract_job(
    job: ExtractJob,
    message_store: "MessageStore",
    mem_store: MemoryItemStore,
    memory_service: "MemoryService",
) -> None:
    templates = await mem_store.list_templates(enabled_only=True)
    if not templates:
        return
    msgs = await message_store.get_group_conversation_messages(job.conversation_id)
    tail = msgs[-40:] if len(msgs) > 40 else msgs
    lines: List[str] = []
    for m in tail:
        role = m.get("role", "")
        content = (m.get("content") or "")[:2000]
        lines.append(f"{role}: {content}")
    dialog = "\n".join(lines)
    for tpl in templates:
        try:
            await _process_one_template(job, tpl, dialog, mem_store, memory_service)
        except Exception as e:
            print(f"[memory.extract] 模板 {tpl.get('id')} 处理失败: {e}")


async def run_memory_extract_worker(
    message_store: "MessageStore",
    mem_store: MemoryItemStore,
    memory_service: "MemoryService",
) -> None:
    if _extract_queue is None:
        return
    print("[memory.extract] worker 已启动")
    while True:
        job = await _extract_queue.get()
        try:
            await process_extract_job(job, message_store, mem_store, memory_service)
        except Exception as e:
            print(f"[memory.extract] job 失败: {e}")
        finally:
            _extract_queue.task_done()
