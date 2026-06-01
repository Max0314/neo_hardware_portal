"""
事件处理器系统
支持多种事件类型的触发和执行
"""
import json
import asyncio
from typing import Dict, Optional, Any, List
from enum import Enum

from .sidebar_handlers import SidebarHandlers
from .script_handlers import ScriptHandlers
from .api_handlers import APIHandlers
from .message_handlers import MessageHandlers
from .custom_handlers import CustomHandlers
from .game_handlers import GameHandlers


class EventType(Enum):
    """事件类型枚举"""
    EXECUTE_SCRIPT = "execute_script"  # 执行后端脚本
    OPEN_SIDEBAR_COMPARE = "open_sidebar_compare"  # 打开对比功能
    OPEN_SIDEBAR_ANALYZE = "open_sidebar_analyze"  # 打开解析功能
    OPEN_SIDEBAR_REVIEW = "open_sidebar_review"  # 打开AI评审
    OPEN_SIDEBAR_SUMMARY = "open_sidebar_summary"  # 打开评审总结
    OPEN_SIDEBAR_CHECKLIST = "open_sidebar_checklist"  # 打开待检查项
    OPEN_SIDEBAR_TAB = "open_sidebar_tab"  # 打开指定标签页
    OPEN_GAME_TETRIS = "open_game_tetris"  # 打开俄罗斯方块游戏
    SEND_MESSAGE = "send_message"  # 发送消息
    CALL_API = "call_api"  # 调用API
    CUSTOM = "custom"  # 自定义事件


class EventHandler:
    """事件处理器"""
    
    def __init__(self):
        # 使用模块化的处理器
        self.event_handlers = {
            EventType.EXECUTE_SCRIPT: ScriptHandlers.handle_execute_script,
            EventType.OPEN_SIDEBAR_COMPARE: SidebarHandlers.handle_open_compare,
            EventType.OPEN_SIDEBAR_ANALYZE: SidebarHandlers.handle_open_analyze,
            EventType.OPEN_SIDEBAR_REVIEW: SidebarHandlers.handle_open_review,
            EventType.OPEN_SIDEBAR_SUMMARY: SidebarHandlers.handle_open_summary,
            EventType.OPEN_SIDEBAR_CHECKLIST: SidebarHandlers.handle_open_checklist,
            EventType.OPEN_SIDEBAR_TAB: SidebarHandlers.handle_open_tab,
            EventType.OPEN_GAME_TETRIS: GameHandlers.handle_open_tetris,
            EventType.SEND_MESSAGE: MessageHandlers.handle_send_message,
            EventType.CALL_API: APIHandlers.handle_call_api,
            EventType.CUSTOM: CustomHandlers.handle_custom,
        }
    
    async def trigger_event(
        self, 
        event_config: Dict[str, Any], 
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        触发事件
        
        Args:
            event_config: 事件配置字典，格式：
                {
                    "type": "open_sidebar_compare",
                    "params": {...}  # 事件参数
                }
            context: 上下文信息（用户消息、对话ID等）
        
        Returns:
            事件执行结果
        """
        if not event_config:
            return {"success": False, "error": "事件配置为空"}
        
        event_type_str = event_config.get("type")
        if not event_type_str:
            return {"success": False, "error": "事件类型未指定"}
        
        try:
            event_type = EventType(event_type_str)
        except ValueError:
            return {"success": False, "error": f"未知的事件类型: {event_type_str}"}
        
        handler = self.event_handlers.get(event_type)
        if not handler:
            return {"success": False, "error": f"事件类型 {event_type_str} 没有对应的处理器"}
        
        try:
            params = event_config.get("params", {})
            result = await handler(params, context or {})
            return {"success": True, "result": result, "event_type": event_type_str}
        except Exception as e:
            return {"success": False, "error": f"事件执行失败: {str(e)}"}
    


# 全局事件处理器实例
event_handler = EventHandler()
