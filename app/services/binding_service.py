from __future__ import annotations

import re


def _normalize(name: str) -> str:
    return re.sub(r"[_\s\-]+", "", name).lower()


def _fuzzy_match(control_name: str, variable_name: str) -> float:
    cn = _normalize(control_name)
    vn = _normalize(variable_name)
    if cn == vn:
        return 1.0
    if cn in vn or vn in cn:
        return 0.85
    common = sum(1 for c in cn if c in vn)
    if not cn:
        return 0.0
    return common / len(cn) * 0.6


def match_variables(
    controls: list[dict],
    variables: list[dict],
    threshold: float = 0.5,
) -> tuple[list[dict], list[dict], list[str], list[str]]:
    matches: list[dict] = []
    conflicts: list[dict] = []
    matched_controls: set[str] = set()
    matched_variables: set[str] = set()
    address_map: dict[str, list[str]] = {}

    for ctrl in controls:
        best_var = None
        best_score = 0.0
        best_reason = ""
        for var in variables:
            score = _fuzzy_match(ctrl["displayName"], var["name"])
            if score > best_score:
                best_score = score
                best_var = var
                best_reason = (
                    "exact" if score >= 0.99
                    else "contains" if score >= 0.8
                    else "partial"
                )
        if best_var and best_score >= threshold:
            matches.append({
                "control_name": ctrl["displayName"],
                "variable_name": best_var["name"],
                "variable_address": best_var.get("register_address", ""),
                "confidence": round(best_score, 4),
                "match_reason": best_reason,
            })
            matched_controls.add(ctrl["displayName"])
            matched_variables.add(best_var["name"])
            addr = best_var.get("register_address")
            if addr:
                address_map.setdefault(addr, []).append(
                    f"{ctrl['displayName']}->{best_var['name']}"
                )

    for addr, items in address_map.items():
        if len(items) > 1:
            conflicts.append({
                "conflict_type": "duplicate_address",
                "description": f"寄存器地址 {addr} 被多个控件绑定",
                "items": items,
            })

    seen_var_names: dict[str, str] = {}
    for var in variables:
        if var["name"] in seen_var_names:
            conflicts.append({
                "conflict_type": "duplicate_variable",
                "description": f"变量名 {var['name']} 重复",
                "items": [seen_var_names[var["name"]], var["name"]],
            })
        seen_var_names[var["name"]] = var["name"]

    return (
        matches,
        conflicts,
        [c["displayName"] for c in controls if c["displayName"] not in matched_controls],
        [v["name"] for v in variables if v["name"] not in matched_variables],
    )
