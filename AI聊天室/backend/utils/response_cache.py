"""
响应缓存机制
减少API调用，降低成本
"""
import hashlib
import json
import threading
from datetime import datetime, timedelta
from typing import Optional, Dict, List


class ResponseCache:
    """响应缓存"""
    
    def __init__(self, ttl_minutes: int = 60, max_entries: int = 1000):
        self.cache: Dict[str, Dict] = {}
        self.ttl = timedelta(minutes=ttl_minutes)
        self.max_entries = max_entries
        self._lock = threading.RLock()
    
    def get_cache_key(self, messages: List[Dict], include_history: bool = False) -> str:
        """生成缓存键"""
        # 只考虑最近的消息（避免历史变化导致缓存失效）
        key_data = []
        
        if include_history:
            # 包含完整历史
            for msg in messages:
                role = msg.get("role", "")
                content = msg.get("content", "")[:200]  # 限制长度
                key_data.append(f"{role}:{content}")
        else:
            # 只考虑system prompt和最后一条用户消息
            for msg in messages:
                if msg.get("role") == "system":
                    content = msg.get("content", "")[:500]
                    key_data.append(f"system:{content}")
                elif msg.get("role") == "user" and msg == messages[-1]:
                    content = msg.get("content", "")[:200]
                    key_data.append(f"user:{content}")
        
        key_string = "|".join(key_data)
        return hashlib.md5(key_string.encode()).hexdigest()
    
    def get(self, cache_key: str) -> Optional[str]:
        """获取缓存响应"""
        with self._lock:
            if cache_key in self.cache:
                entry = self.cache[cache_key]
                if datetime.now() - entry["timestamp"] < self.ttl:
                    return entry["response"]
                del self.cache[cache_key]
            return None
    
    def set(self, cache_key: str, response: str):
        """设置缓存"""
        with self._lock:
            if len(self.cache) >= self.max_entries and self.cache:
                oldest_key = min(self.cache.items(), key=lambda x: x[1]["timestamp"])[0]
                del self.cache[oldest_key]
            self.cache[cache_key] = {
                "response": response,
                "timestamp": datetime.now()
            }
    
    def clear(self):
        """清空缓存"""
        with self._lock:
            self.cache.clear()
    
    def get_stats(self) -> Dict:
        """获取缓存统计"""
        with self._lock:
            valid_entries = sum(
                1 for entry in self.cache.values()
                if datetime.now() - entry["timestamp"] < self.ttl
            )
            return {
                "total_entries": len(self.cache),
                "valid_entries": valid_entries,
                "max_entries": self.max_entries,
                "ttl_minutes": self.ttl.total_seconds() / 60
            }

