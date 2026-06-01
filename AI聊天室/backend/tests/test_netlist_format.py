"""网表格式化与评审合并单元测试"""

from backend.utils.netlist_format import format_analysis_result_markdown, get_net_connection_list
from backend.utils.schematic_review_merge import (
    is_schematic_review_complete,
    merge_schematic_review_json,
)


def test_net_connection_list_full():
    net = {"connections": [f"U{i}.1" for i in range(13)]}
    lst = get_net_connection_list(net)
    assert len(lst) == 13
    assert "U12.1" in lst


def test_format_markdown_no_ellipsis():
    analysis = {
        "summary": {
            "total_components": 1,
            "total_nets": 1,
            "power_nets": ["+3_3V"],
            "differential_pairs": [],
            "interface_nets": {},
        },
        "nets": [
            {
                "name": "+3_3V",
                "type": "Power",
                "connection_count": 13,
                "connections": [f"U5.{i}" for i in range(1, 14)],
            }
        ],
        "components": [
            {
                "id": "U5",
                "type": "IC",
                "value": "TEST",
                "package": "QFN",
                "pins": {"11": "+3_3V", "8": "GND"},
            }
        ],
    }
    md = format_analysis_result_markdown(analysis, "rid-1")
    assert "等共" not in md
    assert "…" not in md
    assert "U5.13" in md
    assert "## 元件引脚连接" in md
    assert "11 → +3_3V" in md
    assert "8 → GND" in md


def test_merge_schematic_review_json():
    part1 = {
        "overall_status": "PASS",
        "summary": "part1",
        "complete": False,
        "interfaces": [
            {
                "type": "USB",
                "checks": [
                    {"check_name": "VBUS", "status": "PASS", "description": "ok"},
                ],
            }
        ],
    }
    part2 = {
        "overall_status": "WARNING",
        "summary": "part2",
        "complete": True,
        "interfaces": [
            {
                "type": "DDR",
                "checks": [
                    {"check_name": "阻抗", "status": "WARNING", "description": "check"},
                ],
            }
        ],
    }
    merged = merge_schematic_review_json([part1, part2])
    assert merged["overall_status"] == "WARNING"
    assert merged["complete"] is True
    types = {i["type"] for i in merged["interfaces"]}
    assert types == {"USB", "DDR"}


def test_is_schematic_review_complete():
    assert is_schematic_review_complete({"complete": False, "interfaces": []}) is False
    assert is_schematic_review_complete({"complete": True, "interfaces": []}) is True
    assert is_schematic_review_complete(None) is False
