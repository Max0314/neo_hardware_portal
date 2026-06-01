"""分层记忆：作用域、召回上下文与任务载荷。"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class MemoryScopeType(str, Enum):
    """记忆隔离层级（可裁剪扩展）。"""

    GLOBAL_ORG = "global_org"
    GROUP = "group"
    USER = "user"
    ASSISTANT = "assistant"
    USER_ASSISTANT = "user_assistant"
    CONVERSATION = "conversation"


class MemoryTemplateKind(str, Enum):
    EVENT = "event"
    PROFILE = "profile"
    NOTE = "note"


class RecallStep(BaseModel):
    """单步召回：在某 scope 层级上取 top_k 条向量命中。"""

    scope_level: str = Field(
        description="conversation | user_assistant | group | user | assistant | global_org"
    )
    top_k: int = 3


class RecallStrategy(BaseModel):
    """可持久化的召回策略（JSON 存 SQLite）。"""

    steps: List[RecallStep] = Field(default_factory=list)
    max_total: int = 8


class MemoryRecallContext(BaseModel):
    """一次对话推理时的记忆查询上下文。"""

    query: str
    org_id: str = ""
    group_id: str = ""
    user_id: str = "anonymous"
    assistant_id: str = ""
    conversation_id: str = ""


class ExtractJob(BaseModel):
    """近实时抽取任务（入队）。"""

    conversation_id: str
    message_id: str
    user_id: str = "anonymous"
    group_id: str = ""
    org_id: str = ""


class MemoryItemPayload(BaseModel):
    """写入 memory_items + 向量库用的载荷。"""

    id: str
    scope_type: MemoryScopeType
    org_id: str = ""
    group_id: str = ""
    user_id: str = ""
    assistant_id: str = ""
    conversation_id: str = ""
    template_id: str
    template_version: int = 1
    kind: str  # event | profile | note
    structured_json: str
    search_text: str
    source_refs: List[str] = Field(default_factory=list)
    confidence: float = 0.8
    supersedes_id: Optional[str] = None
