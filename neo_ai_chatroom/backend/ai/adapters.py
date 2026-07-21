import os
import asyncio
import json
import aiohttp
from typing import List, Dict, Optional
from abc import ABC, abstractmethod

from backend.services.ai_key_resolver import get_secret_async
from backend.ai.bailian_models import (
    get_api_model,
    get_bailian_model,
    is_bailian_ai_id,
    resolve_base_ai_id,
)


class AIAdapter(ABC):
    """AI适配器基类"""
    
    @abstractmethod
    async def get_response(self, message: str, history: List[Dict], system_prompt: Optional[str] = None) -> str:
        pass


class OpenAIAdapter(AIAdapter):
    """OpenAI GPT适配器"""
    
    def __init__(self):
        self.model = "gpt-4"
    
    async def get_response(self, message: str, history: List[Dict], system_prompt: Optional[str] = None) -> str:
        api_key = await get_secret_async("gpt-4")
        if not api_key:
            raise ValueError("ChatGPT API Key 未配置，请在「API 密钥」中保存或设置 OPENAI_API_KEY")
        
        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=api_key)
            
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            
            for h in history:
                if h.get("role") == "user":
                    messages.append({"role": "user", "content": h.get("content", "")})
                elif h.get("role") == "assistant":
                    messages.append({"role": "assistant", "content": h.get("content", "")})
            
            messages.append({"role": "user", "content": message})
            
            response = await client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.7,
            )
            
            return response.choices[0].message.content
        except Exception as e:
            raise Exception(f"OpenAI API错误: {str(e)}")


class DeepSeekAdapter(AIAdapter):
    """DeepSeek适配器（兼容OpenAI API）"""
    
    def __init__(self):
        self.model = "deepseek-chat"
        self.base_url = (
            (os.getenv("DEEPSEEK_BASE_URL") or "https://api.deepseek.com").strip().rstrip("/")
            or "https://api.deepseek.com"
        )
    
    async def get_response(
        self, 
        message: str, 
        history: List[Dict], 
        system_prompt: Optional[str] = None,
        enable_reasoning: bool = False
    ) -> str:
        api_key = (await get_secret_async("deepseek") or "").strip()
        if not api_key:
            raise ValueError(
                "DeepSeek API Key 未配置。请在 AI 工作室「API 密钥」中保存，"
                "或在环境变量 DEEPSEEK_API_KEY 中设置。"
            )
        
        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(
                api_key=api_key,
                base_url=self.base_url
            )
            
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            
            for h in history:
                if h.get("role") == "user":
                    messages.append({"role": "user", "content": h.get("content", "")})
                elif h.get("role") == "assistant":
                    messages.append({"role": "assistant", "content": h.get("content", "")})
            
            messages.append({"role": "user", "content": message})
            
            request_params = {
                "model": "deepseek-reasoner" if enable_reasoning else self.model,
                "messages": messages,
                "stream": False
            }
            
            if enable_reasoning:
                request_params["extra_body"] = {"thinking": {"type": "enabled"}}
            else:
                request_params["temperature"] = 0.7
            
            response = await client.chat.completions.create(**request_params)
            
            usage = getattr(response, 'usage', None)
            cache_info = None
            if usage:
                cache_hit = getattr(usage, 'prompt_cache_hit_tokens', None)
                cache_miss = getattr(usage, 'prompt_cache_miss_tokens', None)
                if cache_hit is not None and cache_miss is not None:
                    total = cache_hit + cache_miss
                    cache_info = {
                        'cache_hit_tokens': cache_hit,
                        'cache_miss_tokens': cache_miss,
                        'cache_hit_rate': (cache_hit / total * 100) if total > 0 else 0
                    }
            
            reasoning_content = getattr(response.choices[0].message, 'reasoning_content', None)
            content = response.choices[0].message.content
            
            if cache_info:
                cache_marker = f"__CACHE_INFO__{cache_info['cache_hit_rate']:.1f}__{cache_info['cache_hit_tokens']}__{cache_info['cache_miss_tokens']}__"
                content = content + cache_marker
            
            if reasoning_content and enable_reasoning:
                return f"💭 **思考过程：**\n{reasoning_content}\n\n**最终回答：**\n{content}"
            
            return content
        except Exception as e:
            raise Exception(f"DeepSeek API错误: {str(e)}")


class BailianAdapter(AIAdapter):
    """AI Token Plan OpenAI 兼容 Chat API（内部沿用 bailian id 兼容历史配置）。"""

    def __init__(self):
        self.base_url = (
            (
                os.getenv("TOKENPLAN_BASE_URL")
                or "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
            )
            .strip()
            .rstrip("/")
        )
        self.reasoning_effort = (
            os.getenv("TOKENPLAN_REASONING_EFFORT") or "high"
        ).strip() or "high"
        self.default_max_tokens = int(os.getenv("BAILIAN_MAX_OUTPUT_TOKENS", "8192"))

    def _build_messages(
        self,
        message: str,
        history: List[Dict],
        system_prompt: Optional[str],
    ) -> List[Dict]:
        messages: List[Dict] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        for h in history:
            if h.get("role") == "user":
                messages.append({"role": "user", "content": h.get("content", "")})
            elif h.get("role") == "assistant":
                messages.append(
                    {"role": "assistant", "content": h.get("content", "")}
                )
        messages.append({"role": "user", "content": message})
        return messages

    async def get_response(
        self,
        message: str,
        history: List[Dict],
        system_prompt: Optional[str] = None,
        enable_reasoning: bool = False,
        ai_id: str = "bailian-deepseekv4",
    ) -> str:
        spec = get_bailian_model(ai_id)
        if not spec:
            raise ValueError(f"未知 AI Token Plan 模型: {ai_id}")

        api_key = (await get_secret_async("bailian") or "").strip()
        if not api_key:
            raise ValueError(
                "AI Token Plan API Key 未配置。请在「API 密钥」中保存密钥，"
                "或设置环境变量 TOKENPLAN_API_KEY。"
            )

        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=api_key, base_url=self.base_url)
            messages = self._build_messages(message, history, system_prompt)
            api_model = get_api_model(ai_id)

            request_params: Dict = {
                "model": api_model,
                "messages": messages,
                "stream": False,
                "max_tokens": spec.max_tokens,
            }
            extra_body: Dict = {}

            if spec.supports_reasoning:
                extra_body["enable_thinking"] = bool(enable_reasoning)
                if enable_reasoning and spec.use_reasoning_effort:
                    extra_body["reasoning_effort"] = self.reasoning_effort

            if extra_body:
                request_params["extra_body"] = extra_body

            if not (spec.supports_reasoning and enable_reasoning):
                request_params["temperature"] = spec.default_temperature

            response = await client.chat.completions.create(**request_params)

            reasoning_content = getattr(
                response.choices[0].message, "reasoning_content", None
            )
            content = response.choices[0].message.content or ""

            if reasoning_content and enable_reasoning:
                return (
                    f"💭 **思考过程：**\n{reasoning_content}\n\n"
                    f"**最终回答：**\n{content}"
                )
            return content
        except Exception as e:
            raise Exception(f"AI Token Plan API错误: {str(e)}") from e


class DoubaoArkAdapter(AIAdapter):
    """火山方舟豆包（OpenAI 兼容 chat/completions），模型如 doubao-seed-2-0-mini-260215。"""

    def __init__(self):
        self.base_url = os.getenv(
            "ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"
        )
        self.model = os.getenv("ARK_DOUBAO_MODEL", "doubao-seed-2-0-mini-260215")

    async def get_response(
        self,
        message: str,
        history: List[Dict],
        system_prompt: Optional[str] = None,
        enable_reasoning: bool = False,
    ) -> str:
        api_key = await get_secret_async("doubao")
        if not api_key:
            raise ValueError("豆包 API Key 未配置，请在「API 密钥」中保存或设置 ARK_API_KEY")

        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=api_key, base_url=self.base_url)

            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})

            for h in history:
                if h.get("role") == "user":
                    messages.append({"role": "user", "content": h.get("content", "")})
                elif h.get("role") == "assistant":
                    messages.append(
                        {"role": "assistant", "content": h.get("content", "")}
                    )

            messages.append({"role": "user", "content": message})

            response = await client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.7,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            raise Exception(f"豆包(方舟) API错误: {str(e)}")


class AnthropicAdapter(AIAdapter):
    """Anthropic Claude适配器"""
    
    def __init__(self):
        self.model = "claude-3-opus-20240229"
    
    async def get_response(self, message: str, history: List[Dict], system_prompt: Optional[str] = None) -> str:
        api_key = await get_secret_async("claude-3")
        if not api_key:
            raise ValueError("Claude API Key 未配置，请在「API 密钥」中保存或设置 ANTHROPIC_API_KEY")
        
        try:
            from anthropic import AsyncAnthropic
            client = AsyncAnthropic(api_key=api_key)
            
            messages = []
            for h in history:
                if h.get("role") == "user":
                    messages.append({"role": "user", "content": h.get("content", "")})
                elif h.get("role") == "assistant":
                    messages.append({"role": "assistant", "content": h.get("content", "")})
            
            messages.append({"role": "user", "content": message})
            
            response = await client.messages.create(
                model=self.model,
                max_tokens=1024,
                messages=messages,
                system=system_prompt if system_prompt else "You are a helpful assistant.",
            )
            
            return response.content[0].text
        except Exception as e:
            raise Exception(f"Anthropic API错误: {str(e)}")


class GoogleAdapter(AIAdapter):
    """Google Gemini适配器"""
    
    def __init__(self):
        self.model = "gemini-pro"
    
    async def get_response(self, message: str, history: List[Dict], system_prompt: Optional[str] = None) -> str:
        api_key = await get_secret_async("gemini")
        if not api_key:
            raise ValueError("Gemini API Key 未配置，请在「API 密钥」中保存或设置 GOOGLE_API_KEY")
        
        try:
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            
            model = genai.GenerativeModel(self.model)
            
            full_context = []
            for h in history:
                if h.get("role") == "user":
                    full_context.append(h.get("content", ""))
                elif h.get("role") == "assistant":
                    full_context.append(h.get("content", ""))
            
            full_context.append(message)
            prompt = "\n".join(full_context)
            
            response = await asyncio.to_thread(model.generate_content, prompt)
            return response.text
        except Exception as e:
            raise Exception(f"Google API错误: {str(e)}")


class AIAdapterManager:
    """AI适配器管理器"""
    
    def __init__(self):
        self.adapters: Dict[str, AIAdapter] = {
            "gpt-4": OpenAIAdapter(),
            "claude-3": AnthropicAdapter(),
            "gemini": GoogleAdapter(),
            "deepseek": DeepSeekAdapter(),
            "doubao": DoubaoArkAdapter(),
        }
        self._bailian = BailianAdapter()

    async def get_response(
        self,
        ai_id: str,
        message: str,
        history: List[Dict],
        system_prompt: Optional[str] = None,
        enable_reasoning: bool = False
    ) -> str:
        base_ai_id = resolve_base_ai_id(ai_id)

        if is_bailian_ai_id(ai_id):
            spec = get_bailian_model(ai_id)
            use_reasoning = enable_reasoning
            if spec and spec.supports_reasoning and not enable_reasoning:
                use_reasoning = spec.default_enable_reasoning
            return await self._bailian.get_response(
                message,
                history,
                system_prompt,
                enable_reasoning=use_reasoning,
                ai_id=ai_id,
            )

        adapter = self.adapters.get(base_ai_id)
        if not adapter:
            raise ValueError(f"不支持的AI: {base_ai_id}")

        if enable_reasoning and base_ai_id == "deepseek":
            return await adapter.get_response(
                message, history, system_prompt, enable_reasoning=True
            )
        return await adapter.get_response(message, history, system_prompt)
