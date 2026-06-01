"""网表分析结果 → 完整 Markdown（供 AI 评审，无连接缩略）"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def _esc(s: Any) -> str:
    return str(s or "").replace("|", "/")


def get_net_connection_list(net: Dict[str, Any]) -> List[str]:
    conns = net.get("connections")
    if isinstance(conns, list):
        return [str(c) for c in conns]
    if isinstance(conns, dict):
        return list(conns.keys())
    return []


def _count_interface_net_categories(interface_nets: Any) -> int:
    if not interface_nets:
        return 0
    if isinstance(interface_nets, list):
        return len(interface_nets)
    if isinstance(interface_nets, dict):
        return len(interface_nets)
    return 0


def format_analysis_result_markdown(
    analysis_result: Dict[str, Any],
    result_id: Optional[str] = None,
) -> str:
    summary = analysis_result.get("summary") or {}
    nets: List[Dict[str, Any]] = analysis_result.get("nets") or []
    components: List[Dict[str, Any]] = analysis_result.get("components") or []
    power_nets: List[str] = summary.get("power_nets") or []
    differential_pairs = summary.get("differential_pairs") or []
    interface_nets = summary.get("interface_nets") or {}
    interface_count = _count_interface_net_categories(interface_nets)
    total_nets = summary.get("total_nets", len(nets))
    total_components = summary.get("total_components", len(components))

    lines: List[str] = [
        "# 网表分析结果",
        "",
        (
            f"**分析摘要**：总元件 {total_components} 个，总网络 {total_nets} 个，"
            f"电源网络 {len(power_nets)} 个，差分对 {len(differential_pairs)} 对，"
            f"接口网络 {interface_count} 类。"
            + (f"结果ID: `{result_id}`" if result_id else "")
        ),
        "",
    ]

    if power_nets:
        lines.append("## 电源网络（供接口供电与地参考）")
        lines.append("")
        for name in power_nets:
            lines.append(f"- **{_esc(name)}**")
        lines.append("")

    if differential_pairs:
        lines.append("## 差分对")
        lines.append("")
        for pair in differential_pairs:
            pos = pair.get("positive", "")
            neg = pair.get("negative", "")
            base = pair.get("base_name", "")
            lines.append(f"- **{_esc(base)}**：+ {_esc(pos)} / - {_esc(neg)}")
        lines.append("")

    if interface_nets and isinstance(interface_nets, dict):
        lines.append("## 接口网络分类")
        lines.append("")
        for iface_type, net_names in sorted(interface_nets.items()):
            if not net_names:
                continue
            lines.append(f"### {_esc(iface_type)}")
            for nn in net_names:
                lines.append(f"- {_esc(nn)}")
            lines.append("")

    by_type: Dict[str, List[Dict[str, Any]]] = {}
    for net in nets:
        t = net.get("type") or "Signal"
        by_type.setdefault(t, []).append(net)
    type_order = ["Power", "Clock", "Signal"]

    lines.append("## 网络连接详情（按类型：Power → Clock → Signal）")
    lines.append("")

    def _append_net_section(net: Dict[str, Any]) -> None:
        name = _esc(net.get("name"))
        ntype = _esc(net.get("type") or "Signal")
        conn_list = get_net_connection_list(net)
        count = net.get("connection_count", len(conn_list))
        lines.append(f"### {name}（{ntype}，{count} 个连接）")
        for ref in conn_list:
            lines.append(f"- {_esc(ref)}")
        lines.append("")

    for t in type_order:
        for net in by_type.get(t, []):
            _append_net_section(net)
    for t in sorted(by_type.keys()):
        if t in type_order:
            continue
        for net in by_type[t]:
            _append_net_section(net)

    lines.append("## 元件列表（位号、类型、值、耐压/精度、封装）")
    lines.append("")
    lines.append("| 位号 | 类型 | 值 | 耐压/精度 | 封装 |")
    lines.append("| --- | --- | --- | --- | --- |")
    for comp in components:
        ctype = str(comp.get("type") or "")
        if ctype == "Capacitor":
            extra = comp.get("voltage_rating") or ""
        elif ctype == "Resistor":
            extra = comp.get("tolerance") or ""
        else:
            extra = comp.get("voltage_rating") or comp.get("tolerance") or ""
        lines.append(
            f"| {_esc(comp.get('id'))} | {_esc(comp.get('type'))} | {_esc(comp.get('value'))} | "
            f"{_esc(extra)} | {_esc(comp.get('package'))} |"
        )

    lines.append("")
    lines.append("## 元件引脚连接")
    lines.append("")
    for comp in components:
        pins = comp.get("pins") or {}
        if not pins:
            continue
        ref = _esc(comp.get("id"))
        ctype = _esc(comp.get("type"))
        value = _esc(comp.get("value"))
        package = _esc(comp.get("package"))
        meta = "，".join(x for x in [ctype, value, package] if x)
        lines.append(f"### {ref}" + (f"（{meta}）" if meta else ""))
        for pin, net_name in sorted(pins.items(), key=lambda x: str(x[0])):
            lines.append(f"- {_esc(pin)} → {_esc(net_name)}")
        lines.append("")

    return "\n".join(lines)
