"""原理图 AI 审核 — 评审提示词与系统配置（当前版本 + 历史备份）"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from backend.ai.bailian_models import BAILIAN_MODELS

DEFAULT_SCHEMATIC_REVIEW_PROMPT = """你是一名资深硬件工程师，请对以下网表进行原理图/接口评审。
请严格以 JSON 格式输出，包含 overall_status、summary、complete、interfaces（含 checks 数组，每项含 check_name、status、description）。
status 仅使用 PASS、WARNING、INFO、FAIL 四种。
若单次输出无法覆盖全部接口检查，请设 "complete": false 并输出已完成的 interfaces；续写轮次使用 "continuation": true 且仅输出新增检查项，不要重复已输出内容。全部完成时设 "complete": true。"""

DEFAULT_SCHEMATIC_AI_ID = "bailian-deepseekv4"
SCHEMATIC_DEFAULT_AI_CONFIG_KEY = "schematic_default_ai_id"

_BUILTIN_SCHEMATIC_AI_IDS = {
    "gpt-4",
    "claude-3",
    "gemini",
    "deepseek",
    "doubao",
    *(m.id for m in BAILIAN_MODELS),
}


def list_selectable_schematic_ai_models() -> List[Dict[str, str]]:
    """原理图审核可选默认模型（不含巴巴塔）。"""
    specs = [
        ("deepseek", "DeepSeek", "DeepSeek V3.2"),
        ("doubao", "豆包 SEED Mini", "火山方舟 Doubao"),
        ("gpt-4", "ChatGPT", "OpenAI GPT-4"),
        ("claude-3", "Claude", "Anthropic Claude"),
        ("gemini", "Gemini", "Google Gemini"),
    ]
    out = [{"id": pid, "name": name, "description": desc} for pid, name, desc in specs]
    for spec in BAILIAN_MODELS:
        out.append({"id": spec.id, "name": spec.name, "description": spec.description})
    return out


def normalize_schematic_default_ai_id(ai_id: Optional[str]) -> str:
    val = (ai_id or "").strip()
    if val in _BUILTIN_SCHEMATIC_AI_IDS:
        return val
    return DEFAULT_SCHEMATIC_AI_ID


async def get_schematic_default_ai_id(message_store) -> str:
    raw = await message_store.get_system_config(SCHEMATIC_DEFAULT_AI_CONFIG_KEY)
    return normalize_schematic_default_ai_id(raw)


async def get_prompt_payload(message_store, user: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    row = await message_store.get_current_schematic_review_prompt()
    prompt = (row["content"] if row else DEFAULT_SCHEMATIC_REVIEW_PROMPT).strip()
    default_ai_id = await get_schematic_default_ai_id(message_store)
    can_edit = _can_manage(user)
    models = list_selectable_schematic_ai_models()
    default_model = next((m for m in models if m["id"] == default_ai_id), None)
    payload: Dict[str, Any] = {
        "success": True,
        "prompt": prompt,
        "default_ai_id": default_ai_id,
        "default_ai_name": default_model["name"] if default_model else default_ai_id,
        "available_ai_models": models,
        "can_edit": can_edit,
        "current_id": row["id"] if row else None,
        "updated_at": row.get("created_at") if row else None,
        "updated_by": row.get("created_by") if row else None,
    }
    if can_edit:
        history = await message_store.list_schematic_review_prompt_history(limit=50)
        payload["history"] = [
            {
                "id": h["id"],
                "content": h["content"],
                "note": h.get("note") or "",
                "created_by": h.get("created_by") or "",
                "created_at": h.get("created_at"),
                "is_current": bool(h.get("is_current")),
            }
            for h in history
        ]
    return payload


def _can_manage(user: Optional[Dict[str, Any]]) -> bool:
    if not user:
        return False
    if str(user.get("username", "")).lower() == "zzw":
        return True
    roles = user.get("roles") or []
    if isinstance(roles, str):
        roles = [roles]
    return any(r in roles for r in ("management", "admin", "super_admin"))


async def save_prompt(
    message_store,
    user: Dict[str, Any],
    content: str,
    note: str = "",
    default_ai_id: Optional[str] = None,
) -> Dict[str, Any]:
    created_by = str(user.get("username") or user.get("userKey") or "")
    row = await message_store.save_schematic_review_prompt(content, created_by, note)
    saved_default = await get_schematic_default_ai_id(message_store)
    if default_ai_id is not None:
        normalized = normalize_schematic_default_ai_id(default_ai_id)
        await message_store.set_system_config(
            SCHEMATIC_DEFAULT_AI_CONFIG_KEY, normalized, created_by
        )
        saved_default = normalized
    history = await message_store.list_schematic_review_prompt_history(limit=50)
    models = list_selectable_schematic_ai_models()
    default_model = next((m for m in models if m["id"] == saved_default), None)
    return {
        "success": True,
        "prompt": row["content"],
        "default_ai_id": saved_default,
        "default_ai_name": default_model["name"] if default_model else saved_default,
        "available_ai_models": models,
        "current_id": row["id"],
        "history": [
            {
                "id": h["id"],
                "content": h["content"],
                "note": h.get("note") or "",
                "created_by": h.get("created_by") or "",
                "created_at": h.get("created_at"),
                "is_current": bool(h.get("is_current")),
            }
            for h in history
        ],
    }


async def restore_prompt(
    message_store,
    user: Dict[str, Any],
    history_id: str,
) -> Dict[str, Any]:
    restored_by = str(user.get("username") or user.get("userKey") or "")
    row = await message_store.restore_schematic_review_prompt(history_id, restored_by)
    history = await message_store.list_schematic_review_prompt_history(limit=50)
    return {
        "success": True,
        "prompt": row["content"],
        "current_id": row["id"],
        "history": [
            {
                "id": h["id"],
                "content": h["content"],
                "note": h.get("note") or "",
                "created_by": h.get("created_by") or "",
                "created_at": h.get("created_at"),
                "is_current": bool(h.get("is_current")),
            }
            for h in history
        ],
    }
