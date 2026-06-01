"""
自定义事件处理器
Custom Event Handlers
"""
from typing import Dict, Any


class CustomHandlers:
    """自定义事件处理器"""
    
    @staticmethod
    async def handle_custom(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """自定义事件"""
        handler_name = params.get("handler")
        if not handler_name:
            raise ValueError("自定义事件处理器名称不能为空")
        
        # 可以注册自定义处理器
        # 这里返回参数，由调用方决定如何处理
        return {
            "action": "custom",
            "handler": handler_name,
            "params": params
        }
