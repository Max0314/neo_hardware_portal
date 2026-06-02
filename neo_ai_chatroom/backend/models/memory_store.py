"""分层记忆结构化存储：模板、记忆条目、召回策略、抽取幂等。"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import aiosqlite

from backend.memory.types import MemoryScopeType, RecallStrategy, RecallStep


DEFAULT_RECALL_STRATEGY = RecallStrategy(
    steps=[
        RecallStep(scope_level="conversation", top_k=4),
        RecallStep(scope_level="user_assistant", top_k=3),
        RecallStep(scope_level="group", top_k=3),
    ],
    max_total=8,
)

DEFAULT_EVENT_SCHEMA = json.dumps(
    {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "summary": {"type": "string"},
            "entities": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["title", "summary"],
    },
    ensure_ascii=False,
)

DEFAULT_PROFILE_SCHEMA = json.dumps(
    {
        "type": "object",
        "properties": {
            "traits": {"type": "array", "items": {"type": "string"}},
            "preferences": {"type": "array", "items": {"type": "string"}},
            "facts": {"type": "array", "items": {"type": "string"}},
        },
    },
    ensure_ascii=False,
)


class MemoryItemStore:
    def __init__(self, db_path: str = "chatroom.db"):
        self.db_path = db_path

    async def init_db(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_recall_config (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    strategy_json TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_templates (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    name TEXT NOT NULL,
                    json_schema TEXT NOT NULL,
                    prompt_hint TEXT,
                    version INTEGER NOT NULL DEFAULT 1,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_items (
                    id TEXT PRIMARY KEY,
                    scope_type TEXT NOT NULL,
                    org_id TEXT NOT NULL DEFAULT '',
                    group_id TEXT NOT NULL DEFAULT '',
                    user_id TEXT NOT NULL DEFAULT '',
                    assistant_id TEXT NOT NULL DEFAULT '',
                    conversation_id TEXT NOT NULL DEFAULT '',
                    template_id TEXT NOT NULL,
                    template_version INTEGER NOT NULL DEFAULT 1,
                    kind TEXT NOT NULL,
                    structured_json TEXT NOT NULL,
                    search_text TEXT NOT NULL,
                    source_refs TEXT NOT NULL DEFAULT '[]',
                    confidence REAL NOT NULL DEFAULT 0.8,
                    supersedes_id TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            await db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_items_conv ON memory_items(conversation_id)
                """
            )
            await db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_items_user_asst ON memory_items(user_id, assistant_id)
                """
            )
            await db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_items_group ON memory_items(group_id)
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_extraction_dedup (
                    conversation_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    template_id TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (conversation_id, message_id, template_id)
                )
                """
            )
            await db.commit()

        await self._seed_defaults()

    async def _seed_defaults(self):
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute("SELECT COUNT(*) FROM memory_recall_config WHERE id = 1")
            row = await cur.fetchone()
            if row and row[0] == 0:
                await db.execute(
                    "INSERT INTO memory_recall_config (id, strategy_json) VALUES (1, ?)",
                    (DEFAULT_RECALL_STRATEGY.model_dump_json(),),
                )
            cur = await db.execute("SELECT COUNT(*) FROM memory_templates")
            row = await cur.fetchone()
            if row and row[0] == 0:
                await db.execute(
                    """
                    INSERT INTO memory_templates (id, kind, name, json_schema, prompt_hint, version, enabled)
                    VALUES (?, ?, ?, ?, ?, ?, 1)
                    """,
                    (
                        "tpl_default_event",
                        "event",
                        "默认关键事件",
                        DEFAULT_EVENT_SCHEMA,
                        "从对话中抽取可追踪的业务/协作事件，输出 JSON。",
                        1,
                    ),
                )
                await db.execute(
                    """
                    INSERT INTO memory_templates (id, kind, name, json_schema, prompt_hint, version, enabled)
                    VALUES (?, ?, ?, ?, ?, ?, 1)
                    """,
                    (
                        "tpl_default_profile",
                        "profile",
                        "默认用户画像片段",
                        DEFAULT_PROFILE_SCHEMA,
                        "从对话中抽取与用户偏好、角色、习惯相关的短事实，输出 JSON。",
                        1,
                    ),
                )
            await db.commit()

    async def get_recall_strategy(self) -> RecallStrategy:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT strategy_json FROM memory_recall_config WHERE id = 1"
            )
            row = await cur.fetchone()
            if not row:
                return DEFAULT_RECALL_STRATEGY
            try:
                return RecallStrategy.model_validate_json(row[0])
            except Exception:
                return DEFAULT_RECALL_STRATEGY

    async def set_recall_strategy(self, strategy: RecallStrategy):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO memory_recall_config (id, strategy_json, updated_at)
                VALUES (1, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    strategy_json = excluded.strategy_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (strategy.model_dump_json(),),
            )
            await db.commit()

    async def list_templates(self, enabled_only: bool = True) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            q = "SELECT * FROM memory_templates"
            if enabled_only:
                q += " WHERE enabled = 1"
            q += " ORDER BY kind, name"
            cur = await db.execute(q)
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def get_template(self, template_id: str) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM memory_templates WHERE id = ?", (template_id,)
            )
            row = await cur.fetchone()
            return dict(row) if row else None

    async def upsert_template(
        self,
        template_id: str,
        kind: str,
        name: str,
        json_schema: str,
        prompt_hint: str = "",
        version: int = 1,
        enabled: bool = True,
    ) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO memory_templates (id, kind, name, json_schema, prompt_hint, version, enabled)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    kind = excluded.kind,
                    name = excluded.name,
                    json_schema = excluded.json_schema,
                    prompt_hint = excluded.prompt_hint,
                    version = excluded.version,
                    enabled = excluded.enabled
                """,
                (
                    template_id,
                    kind,
                    name,
                    json_schema,
                    prompt_hint,
                    version,
                    1 if enabled else 0,
                ),
            )
            await db.commit()

    async def insert_memory_item(
        self,
        item_id: str,
        scope_type: str,
        org_id: str,
        group_id: str,
        user_id: str,
        assistant_id: str,
        conversation_id: str,
        template_id: str,
        template_version: int,
        kind: str,
        structured_json: str,
        search_text: str,
        source_refs: List[str],
        confidence: float,
        supersedes_id: Optional[str],
    ) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO memory_items (
                    id, scope_type, org_id, group_id, user_id, assistant_id, conversation_id,
                    template_id, template_version, kind, structured_json, search_text,
                    source_refs, confidence, supersedes_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    scope_type,
                    org_id or "",
                    group_id or "",
                    user_id or "",
                    assistant_id or "",
                    conversation_id or "",
                    template_id,
                    template_version,
                    kind,
                    structured_json,
                    search_text,
                    json.dumps(source_refs, ensure_ascii=False),
                    confidence,
                    supersedes_id,
                ),
            )
            await db.commit()

    async def get_memory_item(self, item_id: str) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM memory_items WHERE id = ?", (item_id,)
            )
            row = await cur.fetchone()
            return dict(row) if row else None

    async def try_mark_extraction(
        self, conversation_id: str, message_id: str, template_id: str
    ) -> bool:
        """幂等：若已存在则返回 False。"""
        async with aiosqlite.connect(self.db_path) as db:
            try:
                await db.execute(
                    """
                    INSERT INTO memory_extraction_dedup (conversation_id, message_id, template_id)
                    VALUES (?, ?, ?)
                    """,
                    (conversation_id, message_id, template_id),
                )
                await db.commit()
                return True
            except aiosqlite.IntegrityError:
                return False

    def new_id(self) -> str:
        return str(uuid.uuid4())
