"""各 AI 服务商密钥配置元数据（不含密钥明文）。"""

from typing import List, Dict, Any, Optional

AI_KEY_PROVIDERS: List[Dict[str, Any]] = [
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "env_var": "DEEPSEEK_API_KEY",
        "description": "DeepSeek 对话与思考模式",
    },
    {
        "id": "bailian",
        "name": "AI Token Plan",
        "env_var": "TOKENPLAN_API_KEY",
        "description": "AI Token Plan OpenAI 兼容接口（TokenPlan-XXX 模型共用）",
    },
    {
        "id": "doubao",
        "name": "豆包 SEED Mini",
        "env_var": "ARK_API_KEY",
        "description": "火山方舟 Doubao API",
    },
    {
        "id": "gpt-4",
        "name": "ChatGPT",
        "env_var": "OPENAI_API_KEY",
        "description": "OpenAI GPT-4",
    },
    {
        "id": "claude-3",
        "name": "Claude",
        "env_var": "ANTHROPIC_API_KEY",
        "description": "Anthropic Claude",
    },
    {
        "id": "gemini",
        "name": "Gemini",
        "env_var": "GOOGLE_API_KEY",
        "description": "Google Gemini",
    },
]

_PROVIDER_BY_ID = {p["id"]: p for p in AI_KEY_PROVIDERS}


def get_provider(provider_id: str) -> Optional[Dict[str, Any]]:
    return _PROVIDER_BY_ID.get(provider_id)
