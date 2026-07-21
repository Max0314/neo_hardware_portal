"""AI Token Plan 内置文本模型注册表。

内部继续使用 ``bailian-*`` id，以兼容已有自定义角色和历史会话；对外展示和
实际 API 均为 AI Token Plan。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class BailianModelSpec:
    id: str
    name: str
    api_model: str
    avatar: str
    description: str
    max_tokens: int = 8192
    supports_reasoning: bool = False
    default_enable_reasoning: bool = False
    use_reasoning_effort: bool = False
    default_temperature: float = 0.7


def _spec(
    slug: str,
    api_model: str,
    avatar: str,
    *,
    reasoning: bool = True,
    reasoning_effort: bool = False,
) -> BailianModelSpec:
    return BailianModelSpec(
        id=f"bailian-{slug}",
        name=f"TokenPlan-{api_model}",
        api_model=api_model,
        avatar=avatar,
        description=f"AI Token Plan {api_model}",
        supports_reasoning=reasoning,
        default_enable_reasoning=reasoning,
        use_reasoning_effort=reasoning_effort,
        default_temperature=1.0 if reasoning else 0.7,
    )


BAILIAN_MODELS: List[BailianModelSpec] = [
    _spec("deepseekv4", "deepseek-v4-pro", "🔮", reasoning_effort=True),
    _spec("deepseekv4flash", "deepseek-v4-flash", "⚡", reasoning_effort=True),
    _spec("deepseekv32", "deepseek-v3.2", "🧠"),
    _spec("qwen37plus", "qwen3.7-plus", "🌟"),
    _spec("qwen37max", "qwen3.7-max", "✨"),
    _spec("qwen36plus", "qwen3.6-plus", "🚀"),
    _spec("qwen36flash", "qwen3.6-flash", "💨"),
    _spec("kimik27code", "kimi-k2.7-code", "💻"),
    _spec("kimik26", "kimi-k2.6", "🌙"),
    _spec("kimik25", "kimi-k2.5", "🌙"),
    _spec("glm52", "glm-5.2", "🔷"),
    _spec("glm51", "glm-5.1", "🔹"),
    _spec("glm5", "glm-5", "💠"),
    _spec("minimaxm25", "MiniMax-M2.5", "🎵"),
]

_MODEL_BY_ID: Dict[str, BailianModelSpec] = {m.id: m for m in BAILIAN_MODELS}

# 已保存角色可能仍引用旧 id；透明映射到当前套餐支持的近似模型。
_LEGACY_ID_ALIASES = {
    "bailian-deepseekr1": "bailian-deepseekv32",
    "bailian-qwenplus": "bailian-qwen37plus",
    "bailian-qwenmax": "bailian-qwen37max",
    "bailian-qwenturbo": "bailian-qwen36plus",
    "bailian-qwenflash": "bailian-qwen36flash",
    "bailian-glm47": "bailian-glm5",
}


def is_bailian_ai_id(ai_id: str) -> bool:
    base = resolve_base_ai_id(ai_id)
    return base.startswith("bailian-")


def resolve_base_ai_id(ai_id: str) -> str:
    """从 builtin 或 custom-bailian-xxx-uuid 解析内部模型 id。"""
    if not ai_id:
        return ai_id
    if ai_id.startswith("custom-"):
        rest = ai_id[len("custom-") :]
        candidates = list(_MODEL_BY_ID) + list(_LEGACY_ID_ALIASES)
        for model_id in sorted(candidates, key=len, reverse=True):
            if rest == model_id or rest.startswith(model_id + "-"):
                return _LEGACY_ID_ALIASES.get(model_id, model_id)
        return ai_id
    return _LEGACY_ID_ALIASES.get(ai_id, ai_id)


def get_bailian_model(ai_id: str) -> Optional[BailianModelSpec]:
    return _MODEL_BY_ID.get(resolve_base_ai_id(ai_id))


def get_api_model(ai_id: str) -> str:
    spec = get_bailian_model(ai_id)
    if not spec:
        raise ValueError(f"未知 AI Token Plan 模型: {ai_id}")
    env_key = f"TOKENPLAN_MODEL_{spec.id.replace('-', '_')}"
    return (os.getenv(env_key) or "").strip() or spec.api_model


def get_default_mention_model_id() -> str:
    default_id = (
        os.getenv("TOKENPLAN_DEFAULT_MENTION_MODEL") or "bailian-deepseekv4"
    ).strip()
    default_id = _LEGACY_ID_ALIASES.get(default_id, default_id)
    return default_id if default_id in _MODEL_BY_ID else BAILIAN_MODELS[0].id


def build_mention_alias_map() -> Dict[str, str]:
    """别名（小写）到展示名。保留百炼别名仅用于历史输入兼容。"""
    aliases: Dict[str, str] = {}
    default_spec = _MODEL_BY_ID[get_default_mention_model_id()]

    def add(alias: str, display_name: str) -> None:
        key = alias.strip().casefold()
        if key:
            aliases[key] = display_name

    for alias in ("tokenplan", "token-plan", "ai token plan", "百炼", "bailian"):
        add(alias, default_spec.name)
    for spec in BAILIAN_MODELS:
        add(spec.id, spec.name)
        add(spec.name, spec.name)
        add(spec.api_model, spec.name)
        add(spec.id.removeprefix("bailian-"), spec.name)
    return aliases
