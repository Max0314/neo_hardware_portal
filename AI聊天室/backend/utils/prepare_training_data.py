"""
准备训练数据工具
从对话记录中提取和标注数据
"""
import json
import sqlite3
from pathlib import Path
from typing import List, Dict
from backend.models.dialogue_classifier import DialogueCategory


def extract_from_database(db_path: str = "chatroom.db", limit: int = 1000) -> List[Dict]:
    """从数据库提取对话数据"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 查询用户消息
    cursor.execute("""
        SELECT content, created_at 
        FROM messages 
        WHERE role = 'user' 
        ORDER BY created_at DESC 
        LIMIT ?
    """, (limit,))
    
    messages = []
    for row in cursor.fetchall():
        content, created_at = row
        if content and len(content.strip()) > 0:
            messages.append({
                "text": content,
                "timestamp": created_at
            })
    
    conn.close()
    return messages


def auto_label(text: str) -> str:
    """自动标注（基于简单规则）"""
    text_lower = text.lower()
    
    # 问候
    if any(kw in text_lower for kw in ["你好", "您好", "早上好", "下午好", "晚上好", "hi", "hello"]):
        return DialogueCategory.GREETING
    
    # 问题
    if any(kw in text_lower for kw in ["什么", "怎么", "为什么", "如何", "哪里", "哪个", "?", "？", "吗"]):
        return DialogueCategory.QUESTION
    
    # 命令
    if any(kw in text_lower for kw in ["帮我", "请", "做", "执行", "运行", "开始", "停止", "保存", "删除"]):
        return DialogueCategory.COMMAND
    
    # 请求
    if any(kw in text_lower for kw in ["可以", "能否", "能不能", "麻烦", "请求"]):
        return DialogueCategory.REQUEST
    
    # 感谢
    if any(kw in text_lower for kw in ["谢谢", "感谢", "多谢", "thx", "thanks"]):
        return DialogueCategory.THANKS
    
    # 抱怨
    if any(kw in text_lower for kw in ["不好", "不行", "错误", "失败", "问题", "bug"]):
        return DialogueCategory.COMPLAINT
    
    # 闲聊
    if any(kw in text_lower for kw in ["哈哈", "呵呵", "嗯", "哦", "好的", "ok", "okay"]):
        return DialogueCategory.CHAT
    
    return DialogueCategory.UNKNOWN


def prepare_training_data(
    source: str = "database",
    db_path: str = "chatroom.db",
    output_file: str = "training_data.json",
    auto_label_enabled: bool = True,
    limit: int = 1000
):
    """
    准备训练数据
    
    Args:
        source: 数据源 ("database" 或 "file")
        db_path: 数据库路径
        output_file: 输出文件路径
        auto_label_enabled: 是否启用自动标注
        limit: 提取数据量限制
    """
    if source == "database":
        print(f"从数据库提取数据: {db_path}")
        messages = extract_from_database(db_path, limit)
        print(f"提取了 {len(messages)} 条消息")
    else:
        print("请手动提供数据文件")
        return
    
    # 自动标注
    training_data = []
    if auto_label_enabled:
        print("自动标注中...")
        for msg in messages:
            label = auto_label(msg["text"])
            if label != DialogueCategory.UNKNOWN:
                training_data.append({
                    "text": msg["text"],
                    "label": label
                })
        print(f"自动标注了 {len(training_data)} 条数据")
    else:
        # 需要手动标注
        training_data = [{"text": msg["text"], "label": ""} for msg in messages]
    
    # 保存
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(training_data, f, ensure_ascii=False, indent=2)
    
    print(f"训练数据已保存到: {output_file}")
    print(f"\n数据统计:")
    label_counts = {}
    for item in training_data:
        label = item["label"]
        label_counts[label] = label_counts.get(label, 0) + 1
    
    for label, count in sorted(label_counts.items()):
        print(f"  {label}: {count}")
    
    print(f"\n提示: 请检查并手动修正标注，确保数据质量")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="准备对话分类训练数据")
    parser.add_argument("--source", type=str, default="database", 
                       help="数据源: database 或 file")
    parser.add_argument("--db", type=str, default="chatroom.db",
                       help="数据库路径")
    parser.add_argument("--output", type=str, default="training_data.json",
                       help="输出文件路径")
    parser.add_argument("--no-auto-label", action="store_true",
                       help="禁用自动标注")
    parser.add_argument("--limit", type=int, default=1000,
                       help="提取数据量限制")
    
    args = parser.parse_args()
    
    prepare_training_data(
        source=args.source,
        db_path=args.db,
        output_file=args.output,
        auto_label_enabled=not args.no_auto_label,
        limit=args.limit
    )
