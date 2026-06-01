"""
上下文优化器
管理Token数量、压缩历史、总结对话
"""
from typing import List, Dict, Optional
import os


class ContextOptimizer:
    """上下文优化器"""
    
    def __init__(self):
        self.token_counter = 0
    
    def estimate_tokens(self, text: str) -> int:
        """估算token数量"""
        # 中文为主的估算：中文约2字符=1token，英文约4字符=1token
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        english_chars = len(text) - chinese_chars
        return (chinese_chars // 2) + (english_chars // 4)
    
    def compress_history(self, history: List[Dict], max_tokens: int = 2000) -> List[Dict]:
        """压缩对话历史，控制token数量"""
        compressed = []
        current_tokens = 0
        
        # 从最新对话开始添加
        for message in reversed(history):
            content = message.get("content", "")
            tokens = self.estimate_tokens(content)
            
            if current_tokens + tokens <= max_tokens:
                compressed.insert(0, message)  # 保持顺序
                current_tokens += tokens
            else:
                # 如果单条消息太长，截断
                if tokens > max_tokens * 0.3:  # 单条消息不超过30%
                    truncated_content = content[:int(max_tokens * 0.3 * 2)]  # 字符数
                    compressed.insert(0, {
                        **message,
                        "content": truncated_content + "..."
                    })
                    current_tokens += self.estimate_tokens(truncated_content)
                break
        
        return compressed
    
    async def summarize_history(self, history: List[Dict], api_client) -> Optional[str]:
        """使用API总结长对话历史"""
        if len(history) <= 4:
            return None
        
        try:
            # 提取需要总结的部分（保留最近2轮对话）
            to_summarize = history[:-4]
            
            if not to_summarize:
                return None
            
            # 构建总结提示词
            summary_prompt = f"""请将以下对话总结为简短的要点（不超过200字）：

{self._format_history_for_summary(to_summarize)}

总结要点："""
            
            # 调用API获取总结（使用更便宜的模型）
            response = await api_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": summary_prompt}],
                temperature=0.3,
                max_tokens=300
            )
            
            return response.choices[0].message.content
        
        except Exception as e:
            print(f"对话总结失败: {e}")
            return None
    
    def _format_history_for_summary(self, history: List[Dict]) -> str:
        """格式化历史用于总结"""
        formatted = []
        for msg in history:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")[:200]  # 限制长度
            formatted.append(f"{role}: {content}")
        return "\n".join(formatted)
    
    def build_optimized_context(
        self,
        system_prompt: str,
        knowledge_context: Optional[str],
        history: List[Dict],
        current_message: str,
        max_total_tokens: int = 4000
    ) -> List[Dict]:
        """构建优化的上下文消息列表"""
        messages = []
        
        # 1. 系统提示词（包含知识上下文）
        full_system_prompt = system_prompt
        if knowledge_context:
            full_system_prompt += f"\n\n以下是相关专业知识，请参考：\n{knowledge_context}"
        
        system_tokens = self.estimate_tokens(full_system_prompt)
        messages.append({"role": "system", "content": full_system_prompt})
        
        # 2. 计算剩余可用token
        current_message_tokens = self.estimate_tokens(current_message)
        available_tokens = max_total_tokens - system_tokens - current_message_tokens - 200  # 预留200token
        
        # 3. 压缩历史
        compressed_history = self.compress_history(history, max_tokens=available_tokens)
        
        # 4. 添加历史消息
        for msg in compressed_history:
            messages.append({
                "role": msg.get("role"),
                "content": msg.get("content")
            })
        
        # 5. 添加当前消息
        messages.append({"role": "user", "content": current_message})
        
        return messages

