"""原理图 AI 评审 — 多轮 JSON 片段合并"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

_STATUS_RANK = {"PASS": 0, "INFO": 1, "WARNING": 2, "FAIL": 3}


def _worst_status(a: Optional[str], b: Optional[str]) -> str:
    sa = str(a or "INFO").upper()
    sb = str(b or "INFO").upper()
    ra = _STATUS_RANK.get(sa, 1)
    rb = _STATUS_RANK.get(sb, 1)
    return sa if ra >= rb else sb


def _check_key(iface: Dict[str, Any], chk: Dict[str, Any]) -> str:
    iface_type = str(iface.get("type") or iface.get("name") or "接口")
    name = str(chk.get("check_name") or chk.get("name") or "")
    return f"{iface_type}::{name}"


def is_schematic_review_complete(parsed: Optional[Dict[str, Any]]) -> bool:
    if not parsed or not isinstance(parsed, dict):
        return False
    if parsed.get("complete") is False:
        return False
    if not isinstance(parsed.get("interfaces"), list):
        return False
    return True


def merge_schematic_review_json(parts: List[Dict[str, Any]]) -> Dict[str, Any]:
    """合并多轮评审 JSON；后写覆盖同 check_name+interface 的项。"""
    merged_interfaces: Dict[str, Dict[str, Any]] = {}
    check_index: Dict[str, tuple] = {}
    summaries: List[str] = []
    overall = "PASS"

    for part in parts:
        if not part or not isinstance(part, dict):
            continue
        if part.get("summary"):
            summaries.append(str(part["summary"]).strip())
        overall = _worst_status(overall, part.get("overall_status"))
        for iface in part.get("interfaces") or []:
            if not isinstance(iface, dict):
                continue
            iface_type = str(iface.get("type") or iface.get("name") or "接口")
            if iface_type not in merged_interfaces:
                merged_interfaces[iface_type] = {
                    "type": iface_type,
                    "checks": [],
                }
            target = merged_interfaces[iface_type]
            for chk in iface.get("checks") or []:
                if not isinstance(chk, dict):
                    continue
                key = _check_key(iface, chk)
                if key in check_index:
                    iface_type_key, idx = check_index[key]
                    target_iface = merged_interfaces[iface_type_key]
                    target_iface["checks"][idx] = chk
                else:
                    check_index[key] = (iface_type, len(target["checks"]))
                    target["checks"].append(chk)

    return {
        "overall_status": overall,
        "summary": "\n".join(s for s in summaries if s),
        "interfaces": list(merged_interfaces.values()),
        "complete": True,
    }
