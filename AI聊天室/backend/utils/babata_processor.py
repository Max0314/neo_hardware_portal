"""
巴巴塔低智能预处理系统
用于处理秘书类型任务，避免不必要的API调用
"""
import re
import datetime
from typing import Dict, Optional, List, Tuple
from enum import Enum
from backend.utils.babata_helpers import (
    file_manager, email_manager, calculator, 
    time_helper, assistant_router
)


class TaskAction(Enum):
    """任务动作类型"""
    CREATE_REMINDER = "CREATE_REMINDER"
    SCHEDULE_QUERY = "SCHEDULE_QUERY"
    BOOK_RESOURCE = "BOOK_RESOURCE"
    SEND_MESSAGE = "SEND_MESSAGE"
    SEND_EMAIL = "SEND_EMAIL"
    FIND_DOCUMENT = "FIND_DOCUMENT"
    SAVE_CONVERSATION = "SAVE_CONVERSATION"
    EXPORT_LOG = "EXPORT_LOG"
    MENTION_ROLES = "MENTION_ROLES"  # @相关角色
    MENTION_ASSISTANT = "MENTION_ASSISTANT"  # @特定助手（翻译、天气等）
    QUERY_TIME = "QUERY_TIME"
    QUERY_DATE = "QUERY_DATE"
    CALCULATE = "CALCULATE"
    QUERY_INFO = "QUERY_INFO"
    REPEAT = "REPEAT"
    STATUS_QUERY = "STATUS_QUERY"
    TEMPLATE_GENERATE = "TEMPLATE_GENERATE"
    NETLIST_COMPARE = "NETLIST_COMPARE"  # 原理图对比
    NETLIST_REVIEW = "NETLIST_REVIEW"  # 原理图评审
    ASK_AI_TO_LEARN = "ASK_AI_TO_LEARN"  # 让AI回答并学习（帮我问XX）
    UNKNOWN = "UNKNOWN"
    CALL_CLOUD_API = "CALL_CLOUD_API"  # 需要调用云端API


class BabataProcessor:
    """巴巴塔预处理系统"""
    
    def __init__(self):
        # 秘书任务关键词规则
        self.secretary_keyword_rules = {
            TaskAction.SCHEDULE_QUERY: ["日程", "安排", "有什么会", "今天干啥", "今天做什么", "查看日程", "我的日程", "本周日程"],
            TaskAction.CREATE_REMINDER: ["提醒", "记得", "别忘了", "记一下", "帮我记", "设置提醒", "设置闹钟"],
            TaskAction.BOOK_RESOURCE: ["订", "预约", "预订", "占用", "会议室", "酒店", "机票", "订房间"],
            TaskAction.SEND_MESSAGE: ["发消息", "告诉", "微信给", "联系", "通知"],
            TaskAction.SEND_EMAIL: ["发邮件", "邮件", "发送邮件", "邮件通知", "邮件给"],
            TaskAction.FIND_DOCUMENT: ["找文件", "查文档", "上周的报告", "会议记录", "文档", "文件", "查找"],
            TaskAction.SAVE_CONVERSATION: ["保存", "存", "保存对话", "保存聊天", "导出对话", "保存记录", "存为", "导出"],
            TaskAction.EXPORT_LOG: ["导出", "导出日志", "导出记录", "导出对话", "备份"],
            TaskAction.MENTION_ROLES: ["召集", "叫", "邀请", "通知", "开会", "会议", "讨论"],
            TaskAction.MENTION_ASSISTANT: ["@翻译", "@天气", "@计算器", "@新闻", "@时间", "@文件", "@股票", "@快递", "@航班"],
            TaskAction.QUERY_TIME: ["几点", "现在几点", "时间", "现在时间", "当前时间"],
            TaskAction.QUERY_DATE: ["几号", "今天几号", "日期", "今天日期", "今天是"],
            TaskAction.CALCULATE: ["计算", "算", "等于", "加", "减", "乘", "除", "平方", "开方"],
            TaskAction.QUERY_INFO: ["查询", "查", "是什么", "多少", "汇率", "股价"],
            TaskAction.REPEAT: ["重复", "再说一遍", "再说一次", "重复刚才"],
            TaskAction.STATUS_QUERY: ["状态", "运行", "正常", "健康", "使用情况"],
            TaskAction.TEMPLATE_GENERATE: ["模板", "生成模板", "创建模板", "格式"],
            TaskAction.NETLIST_COMPARE: ["原理图对比", "网表对比", "对比原理图", "对比网表", "原理图比较", "网表比较"],
            TaskAction.NETLIST_REVIEW: ["原理图评审", "网表评审", "评审原理图", "评审网表", "原理图分析", "网表分析"],
            TaskAction.ASK_AI_TO_LEARN: ["帮我问", "帮我问一下", "问一下", "帮我查", "帮我查一下", "让", "让AI", "让deepseek", "让DeepSeek"],
        }
        
        # 轻量级意图分类器特征权重
        self.feature_weights = {
            "提醒": {TaskAction.CREATE_REMINDER: 2.5, TaskAction.SCHEDULE_QUERY: 0.1},
            "明天": {TaskAction.CREATE_REMINDER: 1.8},
            "会议": {TaskAction.CREATE_REMINDER: 1.5, TaskAction.BOOK_RESOURCE: 1.2, TaskAction.MENTION_ROLES: 2.0},
            "是多少": {TaskAction.CALL_CLOUD_API: 1.5},  # 问题类，应该调用AI
            "是什么": {TaskAction.CALL_CLOUD_API: 1.5},
            "带宽": {TaskAction.CALL_CLOUD_API: 1.0},
            "电压": {TaskAction.CALL_CLOUD_API: 1.0},
            "接口": {TaskAction.CALL_CLOUD_API: 1.0},
            "pcie": {TaskAction.CALL_CLOUD_API: 1.0},
            "ddr": {TaskAction.CALL_CLOUD_API: 1.0},
            "预约": {TaskAction.BOOK_RESOURCE: 2.5},
            "日程": {TaskAction.SCHEDULE_QUERY: 2.8},
            "召集": {TaskAction.MENTION_ROLES: 3.0},
            "专家": {TaskAction.MENTION_ROLES: 2.5},
            "开会": {TaskAction.MENTION_ROLES: 2.0},
            "保存": {TaskAction.SAVE_CONVERSATION: 3.0},
            "导出": {TaskAction.EXPORT_LOG: 3.0},
            "邮件": {TaskAction.SEND_EMAIL: 3.0},
            "几点": {TaskAction.QUERY_TIME: 3.0},
            "几号": {TaskAction.QUERY_DATE: 3.0},
            "计算": {TaskAction.CALCULATE: 3.0},
            "@": {TaskAction.MENTION_ASSISTANT: 3.0},
            "帮我问": {TaskAction.ASK_AI_TO_LEARN: 3.0},
            "帮我查": {TaskAction.ASK_AI_TO_LEARN: 2.5},
            "问一下": {TaskAction.ASK_AI_TO_LEARN: 2.0},
            "让": {TaskAction.ASK_AI_TO_LEARN: 2.0},
        }
        
        self.intent_bias = {
            TaskAction.CREATE_REMINDER: 0.1,
            TaskAction.CALL_CLOUD_API: 0.3,  # 提高问题类任务的优先级
            TaskAction.SCHEDULE_QUERY: 0.05,
            TaskAction.BOOK_RESOURCE: 0.05,
            TaskAction.MENTION_ROLES: 0.1,
            TaskAction.SAVE_CONVERSATION: 0.1,
            TaskAction.SEND_EMAIL: 0.1,
            TaskAction.QUERY_TIME: 0.1,
            TaskAction.QUERY_DATE: 0.1,
            TaskAction.CALCULATE: 0.1,
            TaskAction.MENTION_ASSISTANT: 0.15,
        }
        
        # 回复模板
        self.response_templates = {
            TaskAction.CREATE_REMINDER: [
                "好的，已为您记下：{event}。",
                "提醒已设置：{event}，请放心。",
                "已记录：{event}，我会提醒您的。"
            ],
            TaskAction.SCHEDULE_QUERY: [
                "正在为您查看日程...",
                "我来看看今天的安排。",
                "让我查看一下您的日程表。"
            ],
            TaskAction.BOOK_RESOURCE: [
                "马上为您预约{resource}。",
                "正在处理您的预约请求。",
                "已为您预订{resource}。"
            ],
            TaskAction.MENTION_ROLES: [
                "已为您@相关角色：{roles}",
                "正在通知相关专家：{roles}",
                "已召集：{roles}"
            ],
            TaskAction.SAVE_CONVERSATION: [
                "好的，正在保存对话记录...",
                "已保存对话到：{file_path}",
                "对话记录已保存。"
            ],
            TaskAction.SEND_EMAIL: [
                "正在发送邮件给{recipient}...",
                "邮件已发送：{subject}",
                "已通知{recipient}：{content}"
            ],
            TaskAction.QUERY_TIME: [
                "现在时间是：{time}",
                "当前时间：{time}",
                "现在是{time}"
            ],
            TaskAction.QUERY_DATE: [
                "今天是{date}",
                "当前日期：{date}",
                "今天是{date}"
            ],
            TaskAction.CALCULATE: [
                "计算结果：{result}",
                "答案是：{result}",
                "等于{result}"
            ],
            TaskAction.MENTION_ASSISTANT: [
                "已为您@{assistant}助手",
                "正在调用{assistant}助手...",
                "已通知{assistant}助手处理"
            ],
            TaskAction.REPEAT: [
                "您刚才说的是：{content}",
                "重复：{content}",
                "您说的是：{content}"
            ],
            TaskAction.STATUS_QUERY: [
                "系统运行正常",
                "一切正常，运行良好",
                "系统状态：正常"
            ],
            TaskAction.ASK_AI_TO_LEARN: [
                "好的，我来帮您询问AI助手。",
                "正在为您咨询AI助手...",
                "让我帮您问一下AI助手。"
            ],
        }
    
    def parse_structured_command(self, text: str) -> Optional[Dict]:
        """第一层：精确指令解析（基于模板）"""
        text_clean = text.replace(" ", "").replace("点", ":")
        
        # 模式1：识别 "下午三点开会" 这类语句（需要明确的时间表达）
        # 排除技术问题（如"3.0"、"3.5"等版本号）
        if not re.search(r'\d+\.\d+', text_clean):  # 如果包含版本号（如3.0），跳过时间识别
            match = re.search(r"(上午|下午|今晚|明天|后天|下周)?(\d{1,2})(?:[:：](\d{1,2}))?分?(.+)$", text_clean)
            if match:
                period, hour, minute, event = match.groups()
                # 确保是时间相关的问题，而不是技术问题
                if period or (hour and int(hour) <= 24):  # 有明确的时间标识
                    time_str = self._convert_to_time(period, hour, minute)
                    return {
                        "action": TaskAction.CREATE_REMINDER,
                        "time": time_str,
                        "event": event.strip(),
                        "confidence": 0.9
                    }
        
        # 模式2：识别 "提醒我明天给张三打电话"
        match = re.search(r"提醒我(明天|下周|后天|(\d+)月(\d+)日)?(.+)", text)
        if match:
            date_info = match.group(1) if match.group(1) else "今天"
            event = match.groups()[-1] if match.groups()[-1] else ""
            return {
                "action": TaskAction.CREATE_REMINDER,
                "date": date_info,
                "event": event.strip(),
                "confidence": 0.85
            }
        
        # 模式3：识别@相关角色 "开会召集专家" 或单独的角色关键词 "专家"
        # 先检查是否有明确的mention关键词
        match = re.search(r"(开会|召集|叫|邀请|通知).*?(专家|工程师|设计师|经理|顾问|律师|医生|老师|教授)", text)
        if match:
            keyword = match.group(2)  # 提取角色关键词
            return {
                "action": TaskAction.MENTION_ROLES,
                "keyword": keyword,
                "confidence": 0.9
            }
        
        # 如果没有明确的mention关键词，但包含角色关键词，也识别为@角色
        role_keywords = ["专家", "工程师", "设计师", "经理", "顾问", "律师", "医生", "老师", "教授"]
        for role_kw in role_keywords:
            if role_kw in text:
                return {
                    "action": TaskAction.MENTION_ROLES,
                    "keyword": role_kw,
                    "confidence": 0.7  # 置信度稍低，因为没有明确的mention关键词
                }
        
        # 模式4：识别@特定助手 "@翻译 你好" / "@DeepSeek"（排除@巴巴塔；允许 @模型 后无正文）
        match = re.search(r"@([^\s@]+)\s*(.*)", text, flags=re.DOTALL)
        if match:
            assistant = match.group(1)
            content = (match.group(2) or "").strip()
            # 如果是@巴巴塔，则不作为助手路由处理，而是交给普通对话逻辑
            if assistant not in ["巴巴塔", "babata"]:
                return {
                    "action": TaskAction.MENTION_ASSISTANT,
                    "assistant": assistant,
                    "content": content,
                    "confidence": 0.95
                }
        
        # 模式5：识别保存对话 "保存对话"、"存为xxx.txt"
        match = re.search(r"(保存|存|导出).*?(对话|聊天|记录|日志)(.*?\.txt|.*?\.md)?", text)
        if match:
            file_type = match.group(3) if match.group(3) else ".txt"
            return {
                "action": TaskAction.SAVE_CONVERSATION,
                "file_type": file_type,
                "confidence": 0.9
            }
        
        # 模式6：识别发邮件 "给张三发邮件，内容：xxx"
        match = re.search(r"给(.+?)(发邮件|邮件).*?内容[：:](.+)", text)
        if match:
            recipient = match.group(1).strip()
            content = match.group(3).strip()
            return {
                "action": TaskAction.SEND_EMAIL,
                "recipient": recipient,
                "content": content,
                "confidence": 0.9
            }
        
        # 模式7：识别时间查询 "现在几点"、"几点钟"
        if re.search(r"(现在|当前)?(几点|时间)", text):
            return {
                "action": TaskAction.QUERY_TIME,
                "confidence": 0.95
            }
        
        # 模式8：识别日期查询 "今天几号"、"几月几号"
        if re.search(r"(今天|当前)?(几号|日期|几月)", text):
            return {
                "action": TaskAction.QUERY_DATE,
                "confidence": 0.95
            }
        
        # 模式9：识别计算 "计算123+456"、"算一下"
        match = re.search(r"(计算|算)(.+)", text)
        if match:
            expression = match.group(2).strip()
            return {
                "action": TaskAction.CALCULATE,
                "expression": expression,
                "confidence": 0.9
            }
        
        # 模式10：识别重复 "重复刚才"、"再说一遍"
        if re.search(r"(重复|再说)(一遍|一次|刚才)", text):
            return {
                "action": TaskAction.REPEAT,
                "confidence": 0.9
            }
        
        # 模式11：识别原理图对比 "原理图对比"、"网表对比"
        if re.search(r"(原理图|网表).*?(对比|比较)", text) or re.search(r"(对比|比较).*?(原理图|网表)", text):
            return {
                "action": TaskAction.NETLIST_COMPARE,
                "confidence": 0.9
            }
        
        # 模式12：识别原理图评审 "原理图评审"、"网表评审"
        if re.search(r"(原理图|网表).*?(评审|分析)", text) or re.search(r"(评审|分析).*?(原理图|网表)", text):
            return {
                "action": TaskAction.NETLIST_REVIEW,
                "confidence": 0.9
            }
        
        return None
    
    def fuzzy_intent_recognition(self, text: str) -> Optional[Dict]:
        """第二层：模糊意图识别（基于关键词规则）"""
        text_lower = text.lower()
        intent_scores = {}
        
        # 关键词匹配打分
        for intent, keywords in self.secretary_keyword_rules.items():
            # @助手需要明确包含@符号
            if intent == TaskAction.MENTION_ASSISTANT:
                if "@" in text:
                    for kw in keywords:
                        if kw in text_lower:
                            intent_scores[intent] = intent_scores.get(intent, 0) + 1
            else:
                for kw in keywords:
                    if kw in text_lower:
                        intent_scores[intent] = intent_scores.get(intent, 0) + 1
        
        # 特殊逻辑增强
        if "明天" in text_lower:
            if TaskAction.SCHEDULE_QUERY in intent_scores or TaskAction.CREATE_REMINDER in intent_scores:
                intent_scores[TaskAction.CREATE_REMINDER] = intent_scores.get(TaskAction.CREATE_REMINDER, 0) + 2
        
        # 检查是否需要@角色（优先检查，如果识别到角色关键词则执行@）
        mention_keywords = ["召集", "叫", "邀请", "开会", "会议", "讨论"]
        role_keywords = ["专家", "工程师", "设计师", "经理", "顾问", "律师", "医生", "老师", "教授"]
        
        has_mention = any(kw in text_lower for kw in mention_keywords)
        has_role = any(kw in text_lower for kw in role_keywords)
        
        # 如果包含角色关键词，优先识别为@角色功能
        if has_role:
            # 即使没有明确的mention关键词，如果只有角色关键词，也认为是@角色
            if has_mention:
                # 有明确的mention关键词，权重更高
                for role_kw in role_keywords:
                    if role_kw in text_lower:
                        intent_scores[TaskAction.MENTION_ROLES] = intent_scores.get(TaskAction.MENTION_ROLES, 0) + 5
                        break
            else:
                # 只有角色关键词，也认为是@角色（但权重较低）
                for role_kw in role_keywords:
                    if role_kw in text_lower:
                        intent_scores[TaskAction.MENTION_ROLES] = intent_scores.get(TaskAction.MENTION_ROLES, 0) + 3
                        break
        
        # 返回得分最高的意图
        if intent_scores:
            primary_intent = max(intent_scores, key=intent_scores.get)
            confidence = min(0.9, intent_scores[primary_intent] / 3.0)  # 归一化置信度
            
            result = {
                "action": primary_intent,
                "raw_text": text,
                "confidence": confidence
            }
            
            # 如果是@角色，提取关键词
            if primary_intent == TaskAction.MENTION_ROLES:
                for role_kw in role_keywords:
                    if role_kw in text_lower:
                        result["keyword"] = role_kw
                        break
            
            return result
        
        return None
    
    def tiny_classifier_predict(self, text: str) -> TaskAction:
        """第三层：微型分类模型（轻量级意图分类）"""
        words = list(text)  # 字符级N-gram (N=1)
        scores = {intent: self.intent_bias.get(intent, 0) for intent in TaskAction if intent != TaskAction.UNKNOWN}
        
        # 累加特征权重
        for word in words:
            if word in self.feature_weights:
                for intent, weight in self.feature_weights[word].items():
                    scores[intent] = scores.get(intent, 0) + weight
        
        # 返回得分最高的意图
        if scores:
            return max(scores, key=scores.get)
        return TaskAction.UNKNOWN
    
    def process(self, user_input: str) -> Dict:
        """处理用户输入，返回任务指令"""
        # 第一层：结构化解析
        structured = self.parse_structured_command(user_input)
        if structured:
            return structured
        
        # 第二层：模糊意图识别
        fuzzy = self.fuzzy_intent_recognition(user_input)
        if fuzzy and fuzzy.get("confidence", 0) > 0.5:
            return fuzzy
        
        # 第三层：分类模型兜底
        intent = self.tiny_classifier_predict(user_input)
        if intent != TaskAction.UNKNOWN:
            return {
                "action": intent,
                "raw_text": user_input,
                "confidence": 0.6
            }
        
        # 本地无法处理，交由云端
        return {
            "action": TaskAction.CALL_CLOUD_API,
            "raw_text": user_input,
            "confidence": 0.0
        }
    
    def format_response(self, task: Dict, mentioned_roles: List[str] = None, context: Dict = None) -> str:
        """将结构化的任务指令，转化为拟人化的秘书回复"""
        action = task.get("action")
        context = context or {}
        
        # 处理@角色
        if action == TaskAction.MENTION_ROLES and mentioned_roles:
            template = self.response_templates.get(action, ["已处理。"])[0]
            roles_str = "、".join(mentioned_roles)
            return template.format(roles=roles_str)
        
        # 处理@特定助手
        if action == TaskAction.MENTION_ASSISTANT:
            assistant = task.get("assistant", "")
            content = task.get("content", "")
            result = assistant_router.route(assistant, content)
            return result
        
        # 处理时间查询
        if action == TaskAction.QUERY_TIME:
            current_time = time_helper.get_current_time()
            template = self.response_templates.get(action, ["现在时间是：{time}"])[0]
            return template.format(time=current_time)
        
        # 处理日期查询
        if action == TaskAction.QUERY_DATE:
            current_date = time_helper.get_current_date()
            template = self.response_templates.get(action, ["今天是{date}"])[0]
            return template.format(date=current_date)
        
        # 处理计算
        if action == TaskAction.CALCULATE:
            expression = task.get("expression", "")
            result = calculator.calculate(expression)
            if result is not None:
                template = self.response_templates.get(action, ["计算结果：{result}"])[0]
                return template.format(result=calculator.format_result(result))
            return f"无法计算：{expression}"
        
        # 处理保存对话
        if action == TaskAction.SAVE_CONVERSATION:
            messages = context.get("messages", [])
            filename = task.get("file_type", ".txt")
            if messages:
                file_path = file_manager.save_conversation(messages, filename)
                template = self.response_templates.get(action, ["已保存对话到：{file_path}"])[0]
                return template.format(file_path=file_path)
            return "没有对话记录可保存"
        
        # 处理发送邮件
        if action == TaskAction.SEND_EMAIL:
            recipient = task.get("recipient", "")
            content = task.get("content", "")
            subject = task.get("subject", "无主题")
            if recipient and content:
                email_manager.send_email(recipient, subject, content)
                template = self.response_templates.get(action, ["已通知{recipient}：{content}"])[0]
                return template.format(recipient=recipient, content=content[:50])
            return "邮件信息不完整"
        
        # 处理重复
        if action == TaskAction.REPEAT:
            last_message = context.get("last_user_message", "")
            if last_message:
                template = self.response_templates.get(action, ["您刚才说的是：{content}"])[0]
                return template.format(content=last_message)
            return "没有找到您刚才说的话"
        
        # 处理状态查询
        if action == TaskAction.STATUS_QUERY:
            template = self.response_templates.get(action, ["系统运行正常"])[0]
            return template
        
        # 默认处理
        templates = self.response_templates.get(action, ["已处理。"])
        import random
        template = random.choice(templates)
        
        # 简单地将任务字典中的值填充到模板
        try:
            response = template.format(**task)
        except:
            response = template
        
        return response
    
    def find_matching_roles(self, keyword: str, available_roles: List[Dict]) -> List[str]:
        """根据关键词查找匹配的角色"""
        matching_roles = []
        keyword_lower = keyword.lower()
        
        for role in available_roles:
            role_name = role.get("name", "").lower()
            role_description = role.get("description", "").lower()
            role_prompt = role.get("rolePrompt", "").lower()
            
            # 检查角色名称、描述或提示词中是否包含关键词
            if (keyword_lower in role_name or 
                keyword_lower in role_description or 
                keyword_lower in role_prompt):
                matching_roles.append(role.get("name", role.get("id", "")))
        
        return matching_roles
    
    def _convert_to_time(self, period: Optional[str], hour: str, minute: Optional[str]) -> str:
        """将模糊时间转换为具体时间"""
        hour_int = int(hour)
        minute_int = int(minute) if minute else 0
        
        # 处理下午时间
        if period and "下午" in period:
            if hour_int < 12:
                hour_int += 12
        
        return f"{hour_int:02d}:{minute_int:02d}"

