"""
角色提示词生成器
根据角色配置自动生成结构化的system prompt
"""
from typing import Dict, Optional, List


class RolePromptBuilder:
    """角色提示词构建器"""
    
    @staticmethod
    def build_system_prompt(
        name: str,
        role_prompt: str,
        role_config: Optional[Dict] = None
    ) -> str:
        """
        构建完整的system prompt
        
        Args:
            name: 角色名称
            role_prompt: 基础角色设定
            role_config: 详细角色配置（可选）
        
        Returns:
            完整的system prompt字符串
        """
        if not role_config:
            # 如果没有详细配置，使用基础提示词
            return f"你是{name}。{role_prompt}"
        
        # 构建结构化提示词
        parts = []
        
        # 1. 核心身份
        parts.append(f"# 角色身份\n你是{name}")
        if role_config.get("identity"):
            identity = role_config["identity"]
            if identity.get("title"):
                parts.append(f"，{identity['title']}")
            if identity.get("company"):
                parts.append(f"，来自{identity['company']}")
            if identity.get("yearsOfExperience"):
                parts.append(f"，拥有{identity['yearsOfExperience']}年工作经验")
            if identity.get("personality"):
                parts.append(f"。性格特点：{identity['personality']}")
        parts.append("。\n")
        
        # 2. 专业能力
        if role_config.get("expertise"):
            expertise = role_config["expertise"]
            parts.append("## 专业能力\n")
            
            if expertise.get("primarySkills"):
                parts.append("**核心技能：**\n")
                for skill in expertise["primarySkills"]:
                    parts.append(f"- {skill}\n")
            
            if expertise.get("secondarySkills"):
                parts.append("\n**辅助技能：**\n")
                for skill in expertise["secondarySkills"]:
                    parts.append(f"- {skill}\n")
            
            if expertise.get("limitations"):
                parts.append("\n**职责边界：**\n")
                for limit in expertise["limitations"]:
                    parts.append(f"- {limit}\n")
            parts.append("\n")
        
        # 3. 沟通风格
        if role_config.get("communication"):
            comm = role_config["communication"]
            parts.append("## 沟通风格\n")
            
            if comm.get("tone"):
                parts.append(f"- **语气**：{comm['tone']}\n")
            
            if comm.get("formalityLevel") is not None:
                formality = "正式" if comm["formalityLevel"] > 0.5 else "轻松"
                parts.append(f"- **正式程度**：{formality}\n")
            
            if comm.get("useFormalities"):
                parts.append("- **称呼方式**：使用\"您\"等尊称\n")
            
            if comm.get("signaturePhrases"):
                parts.append(f"- **常用表达**：{', '.join(comm['signaturePhrases'])}\n")
            
            parts.append("\n")
        
        # 4. 行为准则
        parts.append("## 行为准则\n")
        
        if role_config.get("shouldDo"):
            parts.append("✅ **应该做：**\n")
            for item in role_config["shouldDo"]:
                parts.append(f"- {item}\n")
            parts.append("\n")
        
        if role_config.get("shouldNotDo"):
            parts.append("❌ **不做：**\n")
            for item in role_config["shouldNotDo"]:
                parts.append(f"- {item}\n")
            parts.append("\n")
        
        # 5. 基础角色设定
        if role_prompt:
            parts.append("## 角色设定\n")
            parts.append(f"{role_prompt}\n\n")
        
        # 6. 对话示例（可选）
        if role_config.get("examples"):
            parts.append("## 对话示例\n")
            for example in role_config["examples"]:
                if example.get("user") and example.get("assistant"):
                    parts.append(f"用户：{example['user']}\n")
                    parts.append(f"{name}：{example['assistant']}\n\n")
        
        # 7. 结尾
        parts.append("---\n")
        parts.append(f"现在开始以{name}的身份回复用户的问题。")
        
        return "".join(parts)
    
    @staticmethod
    def build_simple_prompt(name: str, role_prompt: str) -> str:
        """构建简单提示词（兼容旧版本）"""
        return f"你是{name}。{role_prompt}"


# 预定义角色模板
ROLE_TEMPLATES = {
    "secretary": {
        "name": "艾米",
        "identity": {
            "title": "行政秘书",
            "company": "智创科技",
            "yearsOfExperience": 5,
            "personality": "专业、高效、细心、礼貌"
        },
        "expertise": {
            "primarySkills": ["日程管理", "会议安排", "文档处理", "邮件沟通"],
            "secondarySkills": ["访客接待", "差旅安排", "报告整理"],
            "limitations": ["不处理财务决策", "不涉及技术开发", "不提供法律建议"]
        },
        "communication": {
            "tone": "正式而友好",
            "formalityLevel": 0.8,
            "responseSpeed": "及时",
            "useFormalities": True,
            "signaturePhrases": ["明白", "马上处理", "请确认"]
        },
        "shouldDo": [
            "确认需求细节",
            "提供明确时间节点",
            "使用专业术语但解释清晰",
            "主动询问遗漏信息"
        ],
        "shouldNotDo": [
            "代替决策",
            "透露机密信息",
            "处理专业领域外问题"
        ],
        "examples": [
            {
                "user": "明天上午有什么安排？",
                "assistant": "您明天上午的日程如下：\n1. 9:00-10:00 部门周会（302会议室）\n2. 10:30-11:30 客户视频会议（已测试设备）\n3. 11:45 与张总午餐会议（预定星云餐厅）\n\n需要我调整任何安排吗？"
            }
        ]
    },
    "hardware_expert": {
        "name": "硬件专家",
        "identity": {
            "title": "资深硬件工程师",
            "yearsOfExperience": 10,
            "personality": "严谨、专业、注重细节"
        },
        "expertise": {
            "primarySkills": ["硬件设计", "电路分析", "故障诊断", "性能优化"],
            "secondarySkills": ["PCB设计", "元器件选型", "测试验证"],
            "limitations": ["不涉及软件编程", "不提供商业建议"]
        },
        "communication": {
            "tone": "专业严谨",
            "formalityLevel": 0.7,
            "useFormalities": True,
            "signaturePhrases": ["根据技术规范", "建议检查", "需要注意"]
        }
    }
}

