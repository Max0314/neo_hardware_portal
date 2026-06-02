"""NEO 用户等级阈值（与前端 HomePage USER_LEVELS 一致）。"""
from typing import Any, Dict, List, Optional, TypedDict


class UserLevelConfig(TypedDict):
    level: int
    requiredPoints: float
    title: str


USER_LEVELS: List[UserLevelConfig] = [
    {"level": 1, "requiredPoints": 0, "title": "新生工科生"},
    {"level": 2, "requiredPoints": 10, "title": "见习布线员"},
    {"level": 3, "requiredPoints": 30, "title": "初级制板师"},
    {"level": 4, "requiredPoints": 60, "title": "中级焊将"},
    {"level": 5, "requiredPoints": 100, "title": "认证调试员"},
    {"level": 6, "requiredPoints": 150, "title": "一板就成俠"},
    {"level": 7, "requiredPoints": 210, "title": "焊武帝"},
    {"level": 8, "requiredPoints": 280, "title": "洞洞板散人"},
    {"level": 9, "requiredPoints": 370, "title": "覆铜板修士"},
    {"level": 10, "requiredPoints": 480, "title": "四层板道长"},
    {"level": 11, "requiredPoints": 610, "title": "主任设计师"},
    {"level": 12, "requiredPoints": 770, "title": "资深硬件专家"},
    {"level": 13, "requiredPoints": 960, "title": "高级专家"},
    {"level": 14, "requiredPoints": 1200, "title": "首席硬件官"},
    {"level": 15, "requiredPoints": 1500, "title": "万用表真人"},
    {"level": 16, "requiredPoints": 1900, "title": "示波器仙人"},
    {"level": 17, "requiredPoints": 2400, "title": "硬件合伙人"},
    {"level": 18, "requiredPoints": 3100, "title": "院士级宗师"},
    {"level": 19, "requiredPoints": 4200, "title": "架构开拓者"},
    {"level": 20, "requiredPoints": 8000, "title": "平台硬件之神 👑"},
]


def level_from_points(total_points: float) -> Dict[str, Any]:
    """根据总积分返回当前等级信息。"""
    pts = float(total_points)
    current = USER_LEVELS[0]
    for item in reversed(USER_LEVELS):
        if pts >= item["requiredPoints"]:
            current = item
            break
    next_level = next((x for x in USER_LEVELS if x["level"] == current["level"] + 1), None)
    return {
        "level": current["level"],
        "title": current["title"],
        "requiredPoints": current["requiredPoints"],
        "nextLevel": next_level["level"] if next_level else None,
        "nextTitle": next_level["title"] if next_level else None,
        "nextRequiredPoints": next_level["requiredPoints"] if next_level else None,
    }
