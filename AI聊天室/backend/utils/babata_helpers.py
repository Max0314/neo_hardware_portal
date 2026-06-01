"""
巴巴塔辅助功能模块
处理文件保存、邮件发送、计算等具体任务
"""
import os
import json
import datetime
from pathlib import Path
from typing import List, Dict, Optional
import re


class FileManager:
    """文件管理助手"""
    
    def __init__(self, base_dir: str = "./saved_conversations"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(exist_ok=True)
    
    def save_conversation(self, messages: List[Dict], filename: Optional[str] = None) -> str:
        """保存对话记录"""
        if not filename:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"conversation_{timestamp}.txt"
        
        # 确保文件名有扩展名
        if not filename.endswith(('.txt', '.md', '.json')):
            filename += ".txt"
        
        file_path = self.base_dir / filename
        
        # 格式化消息
        content = []
        content.append(f"对话记录 - {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        content.append("=" * 50 + "\n\n")
        
        for msg in messages:
            sender = msg.get("sender", "unknown")
            name = msg.get("name", "未知")
            content_text = msg.get("content", "")
            timestamp = msg.get("timestamp", "")
            
            if sender == "user":
                content.append(f"[用户 {name}] {timestamp}\n")
            else:
                content.append(f"[{name}] {timestamp}\n")
            
            content.append(f"{content_text}\n\n")
        
        # 写入文件
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write("".join(content))
        
        return str(file_path)
    
    def export_log(self, messages: List[Dict], format: str = "txt") -> str:
        """导出日志"""
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        
        if format == "json":
            filename = f"log_{timestamp}.json"
            file_path = self.base_dir / filename
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(messages, f, ensure_ascii=False, indent=2, default=str)
        else:
            filename = f"log_{timestamp}.txt"
            file_path = self.base_dir / filename
            with open(file_path, 'w', encoding='utf-8') as f:
                for msg in messages:
                    f.write(json.dumps(msg, ensure_ascii=False, default=str) + "\n")
        
        return str(file_path)


class EmailManager:
    """邮件管理助手（模拟）"""
    
    def __init__(self):
        self.sent_emails = []  # 存储已发送的邮件（模拟）
    
    def send_email(self, recipient: str, subject: str = "", content: str = "") -> bool:
        """发送邮件（模拟实现）"""
        email_record = {
            "recipient": recipient,
            "subject": subject or "无主题",
            "content": content,
            "sent_at": datetime.datetime.now().isoformat(),
            "status": "sent"
        }
        self.sent_emails.append(email_record)
        
        # 在实际应用中，这里应该调用真实的邮件API
        # 例如：smtplib, sendgrid, AWS SES等
        
        print(f"[邮件模拟] 发送给 {recipient}: {subject}")
        return True
    
    def get_sent_emails(self) -> List[Dict]:
        """获取已发送的邮件列表"""
        return self.sent_emails


class Calculator:
    """计算器助手"""
    
    def calculate(self, expression: str) -> Optional[float]:
        """计算数学表达式"""
        try:
            # 清理表达式
            expression = expression.replace(" ", "")
            expression = expression.replace("×", "*")
            expression = expression.replace("÷", "/")
            expression = expression.replace("x", "*")
            
            # 安全计算（只允许数字和基本运算符）
            if not re.match(r'^[\d+\-*/().\s]+$', expression):
                return None
            
            result = eval(expression)
            return float(result)
        except:
            return None
    
    def format_result(self, result: float) -> str:
        """格式化结果"""
        if result.is_integer():
            return str(int(result))
        return f"{result:.2f}"


class TimeHelper:
    """时间助手"""
    
    def get_current_time(self) -> str:
        """获取当前时间"""
        return datetime.datetime.now().strftime("%H:%M:%S")
    
    def get_current_date(self) -> str:
        """获取当前日期"""
        return datetime.datetime.now().strftime("%Y年%m月%d日")
    
    def get_current_datetime(self) -> str:
        """获取当前日期时间"""
        return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class AssistantRouter:
    """助手路由器（处理@特定助手）"""
    
    def __init__(self):
        self.assistants = {
            "翻译": self._handle_translate,
            "天气": self._handle_weather,
            "计算器": self._handle_calculator,
            "新闻": self._handle_news,
            "时间": self._handle_time,
            "文件": self._handle_file,
            "股票": self._handle_stock,
            "快递": self._handle_express,
            "航班": self._handle_flight,
        }
    
    def route(self, assistant_name: str, content: str) -> str:
        """路由到对应的助手
        
        对于暂不支持的助手，不再直接回复报错，而是交给上层决定是否调用大模型（如DeepSeek）
        这里返回一个提示性文本，语气更柔和，且不阻断后续处理。
        """
        handler = self.assistants.get(assistant_name)
        if handler:
            return handler(content)
        return f"[助手路由] 暂未内置 @{assistant_name} 专用助手，我会尝试通过其他AI来帮你处理这个请求。"
    
    def _handle_translate(self, content: str) -> str:
        """处理翻译请求"""
        # 这里应该调用翻译API，暂时返回模拟结果
        return f"[翻译助手] 正在翻译：{content}\n（实际应用中需要调用翻译API）"
    
    def _handle_weather(self, content: str) -> str:
        """处理天气查询"""
        # 提取城市名称
        city_match = re.search(r"(.+?)(天气|温度|预报)", content)
        city = city_match.group(1) if city_match else content
        
        return f"[天气助手] 正在查询{city}的天气...\n（实际应用中需要调用天气API）"
    
    def _handle_calculator(self, content: str) -> str:
        """处理计算请求"""
        calc = Calculator()
        result = calc.calculate(content)
        if result is not None:
            return f"[计算器] 计算结果：{calc.format_result(result)}"
        return f"[计算器] 无法计算：{content}"
    
    def _handle_news(self, content: str) -> str:
        """处理新闻查询"""
        return f"[新闻助手] 正在搜索相关新闻：{content}\n（实际应用中需要调用新闻API）"
    
    def _handle_time(self, content: str) -> str:
        """处理时间相关请求"""
        time_helper = TimeHelper()
        if "倒计时" in content or "番茄钟" in content:
            return f"[时间助手] 已设置时间提醒\n（实际应用中需要实现定时器功能）"
        return f"[时间助手] 当前时间：{time_helper.get_current_datetime()}"
    
    def _handle_file(self, content: str) -> str:
        """处理文件操作"""
        return f"[文件助手] 正在处理文件操作：{content}\n（实际应用中需要实现文件系统操作）"
    
    def _handle_stock(self, content: str) -> str:
        """处理股票查询"""
        return f"[股票助手] 正在查询股票信息：{content}\n（实际应用中需要调用股票API）"
    
    def _handle_express(self, content: str) -> str:
        """处理快递查询"""
        return f"[快递助手] 正在查询快递信息：{content}\n（实际应用中需要调用快递API）"
    
    def _handle_flight(self, content: str) -> str:
        """处理航班查询"""
        return f"[航班助手] 正在查询航班信息：{content}\n（实际应用中需要调用航班API）"


# 全局实例
file_manager = FileManager()
email_manager = EmailManager()
calculator = Calculator()
time_helper = TimeHelper()
assistant_router = AssistantRouter()

