"""原理图 AI 审核 — 用户评审历史记录"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def serialize_review_payload(
    *,
    aggregated_review_summary: Any,
    ai_review_entries: List[Dict],
    cleaned_netlist_text: str,
    check_dispositions: Dict,
    default_ai_name: str,
    netlist_name: str,
) -> Dict[str, Any]:
    entries = []
    for e in ai_review_entries or []:
        ts = e.get("timestamp")
        if hasattr(ts, "isoformat"):
            ts_str = ts.isoformat()
        else:
            ts_str = str(ts) if ts else None
        entries.append(
            {
                "id": e.get("id"),
                "content": e.get("content"),
                "parsed": e.get("parsed"),
                "timestamp": ts_str,
                "aiName": e.get("aiName"),
            }
        )
    return {
        "aggregated_review_summary": aggregated_review_summary,
        "ai_review_entries": entries,
        "cleaned_netlist_text": cleaned_netlist_text or "",
        "check_dispositions": check_dispositions or {},
        "default_ai_name": default_ai_name or "",
        "netlist_name": netlist_name or "",
    }


def normalize_loaded_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    entries = payload.get("ai_review_entries") or []
    normalized_entries = []
    for e in entries:
        ts_raw = e.get("timestamp")
        normalized_entries.append(
            {
                **e,
                "timestamp": ts_raw,
            }
        )
    return {
        **payload,
        "ai_review_entries": normalized_entries,
    }
