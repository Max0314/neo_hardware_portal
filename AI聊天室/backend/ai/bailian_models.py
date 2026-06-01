"""
阿里云百炼（DashScope OpenAI 兼容模式）内置模型注册表。

展示名：百炼-XXX；内部 id：bailian-{slug}（slug 仅字母数字，便于 custom-bailian-xxx-uuid 解析）。
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


BAILIAN_MODELS: List[BailianModelSpec] = [
    # DeepSeek（阿里云直供）
    BailianModelSpec(
        id="bailian-deepseekv4",
        name="百炼-deepseekV4",
        api_model="deepseek-v4-pro",
        avatar="🔮",
        description="百炼 DeepSeek V4 Pro",
        supports_reasoning=True,
        default_enable_reasoning=True,
        use_reasoning_effort=True,
        default_temperature=1.0,
    ),
    BailianModelSpec(
        id="bailian-deepseekv4flash",
        name="百炼-deepseekV4Flash",
        api_model="deepseek-v4-flash",
        avatar="⚡",
        description="百炼 DeepSeek V4 Flash",
        supports_reasoning=True,
        default_enable_reasoning=True,
        use_reasoning_effort=True,
        default_temperature=1.0,
    ),
    BailianModelSpec(
        id="bailian-deepseekv32",
        name="百炼-deepseekV32",
        api_model="deepseek-v3.2",
        avatar="🧠",
        description="百炼 DeepSeek V3.2",
        supports_reasoning=True,
        default_enable_reasoning=False,
        default_temperature=1.0,
    ),
    BailianModelSpec(
        id="bailian-deepseekr1",
        name="百炼-deepseekR1",
        api_model="deepseek-r1",
        avatar="💡",
        description="百炼 DeepSeek R1",
        supports_reasoning=True,
        default_enable_reasoning=True,
        default_temperature=0.6,
    ),
    # Qwen
    BailianModelSpec(
        id="bailian-qwenplus",
        name="百炼-qwenPlus",
        api_model="qwen-plus",
        avatar="🌟",
        description="百炼通义千问 Plus",
    ),
    BailianModelSpec(
        id="bailian-qwenmax",
        name="百炼-qwenMax",
        api_model="qwen-max",
        avatar="✨",
        description="百炼通义千问 Max",
    ),
    BailianModelSpec(
        id="bailian-qwenturbo",
        name="百炼-qwenTurbo",
        api_model="qwen-turbo",
        avatar="🚀",
        description="百炼通义千问 Turbo",
    ),
    BailianModelSpec(
        id="bailian-qwenflash",
        name="百炼-qwenFlash",
        api_model="qwen-flash",
        avatar="💨",
        description="百炼通义千问 Flash",
    ),
    # 其他
    BailianModelSpec(
        id="bailian-kimik25",
        name="百炼-kimiK25",
        api_model="kimi-k2.5",
        avatar="🌙",
        description="百炼 Kimi K2.5",
        supports_reasoning=True,
        default_enable_reasoning=False,
        default_temperature=1.0,
    ),
    BailianModelSpec(
        id="bailian-glm47",
        name="百炼-glm47",
        api_model="glm-4.7",
        avatar="🔷",
        description="百炼 GLM 4.7",
        default_temperature=1.0,
    ),
    BailianModelSpec(
        id="bailian-minimaxm25",
        name="百炼-MiniMaxM25",
        api_model="MiniMax-M2.5",
        avatar="🎵",
        description="百炼 MiniMax M2.5",
        default_temperature=1.0,
    ),
]

_MODEL_BY_ID: Dict[str, BailianModelSpec] = {m.id: m for m in BAILIAN_MODELS}


def is_bailian_ai_id(ai_id: str) -> bool:
    base = resolve_base_ai_id(ai_id)
    return base.startswith("bailian-")


def resolve_base_ai_id(ai_id: str) -> str:
    """从 builtin 或 custom-bailian-xxx-uuid 解析出 bailian-xxx。"""
    if not ai_id:
        return ai_id
    if ai_id.startswith("custom-"):
        rest = ai_id[len("custom-") :]
        for spec in sorted(BAILIAN_MODELS, key=lambda s: len(s.id), reverse=True):
            prefix = spec.id + "-"
            if rest == spec.id or rest.startswith(prefix):
                return spec.id
        parts = rest.split("-", 1)
        if len(parts) >= 1 and parts[0].startswith("bailian"):
            # 兼容未知 bailian 前缀
            candidate = parts[0]
            if len(parts) > 1 and not parts[1][:8].count("-"):
                pass
            return candidate if candidate.startswith("bailian-") else ai_id
        # 旧逻辑：custom-deepseek-uuid
        legacy = rest.split("-", 1)
        return legacy[0] if legacy else ai_id
    return ai_id


def get_bailian_model(ai_id: str) -> Optional[BailianModelSpec]:
    base = resolve_base_ai_id(ai_id)
    return _MODEL_BY_ID.get(base)


def get_api_model(ai_id: str) -> str:
    spec = get_bailian_model(ai_id)
    if not spec:
        raise ValueError(f"未知百炼模型: {ai_id}")
    env_key = f"BAILIAN_MODEL_{spec.id.replace('-', '_')}"
    override = (os.getenv(env_key) or "").strip()
    return override or spec.api_model


def get_default_mention_model_id() -> str:
    default_id = (
        os.getenv("BAILIAN_DEFAULT_MENTION_MODEL") or "bailian-deepseekv4"
    ).strip()
    if default_id in _MODEL_BY_ID:
        return default_id
    return BAILIAN_MODELS[0].id


def build_mention_alias_map() -> Dict[str, str]:
    """别名（小写）-> 展示名 name。"""
    aliases: Dict[str, str] = {}
    default_spec = _MODEL_BY_ID[get_default_mention_model_id()]

    def add(alias: str, display_name: str) -> None:
        key = alias.strip().casefold()
        if key:
            aliases[key] = display_name

    add("百炼", default_spec.name)
    add("bailian", default_spec.name)
    add("dashscope", default_spec.name)
    add("百炼-deepseek", default_spec.name)
    add("百炼-deepseekv4", default_spec.name)

    for spec in BAILIAN_MODELS:
        add(spec.id, spec.name)
        add(spec.name, spec.name)
        if spec.name.startswith("百炼-"):
            slug = spec.name[len("百炼-") :]
            add(slug, spec.name)
            add(f"百炼-{slug}", spec.name)
        # id 去掉 bailian- 前缀
        if spec.id.startswith("bailian-"):
            tail = spec.id[len("bailian-") :]
            add(tail, spec.name)
            add(f"百炼-{tail}", spec.name)

    return aliases
