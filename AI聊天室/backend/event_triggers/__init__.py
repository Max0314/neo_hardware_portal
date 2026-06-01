"""
事件触发系统
Event Triggers System
"""

from .handlers.event_handler import event_handler, EventHandler, EventType

__all__ = ['event_handler', 'EventHandler', 'EventType']
