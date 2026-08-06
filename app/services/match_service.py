from __future__ import annotations

import re
from typing import Any, Callable, Optional

from app.services.semantic import get_similarity

SimilarityFn = Callable[[str, str], float]

PANEL_NAME_RE = re.compile(r"^状态面板(\d*)$")
DEVICE_NUMBER_RE = re.compile(r"(\d+)$")

NUMERIC_TYPES = {"int", "double"}


def _normalize(name: str) -> str:
    return re.sub(r"[\s_\-]+", "", name).lower()


def parse_panel_instance(display_name: str) -> Optional[int]:
    m = PANEL_NAME_RE.match(display_name)
    if not m:
        return None
    digits = m.group(1)
    if not digits:
        return 1
    return int(digits)


def parse_device_instance(device_name: str) -> int:
    m = DEVICE_NUMBER_RE.search(device_name)
    if not m:
        return 1
    return int(m.group(1))


def type_compatible(a: str, b: str) -> bool:
    if a == b:
        return True
    return a in NUMERIC_TYPES and b in NUMERIC_TYPES


def find_panels(json_data: dict[str, Any]) -> list[dict[str, Any]]:
    panels: list[dict[str, Any]] = []
    for i, node in enumerate(json_data.get("d") or []):
        if node.get("c") != "ht.Node":
            continue
        p = node.get("p") or {}
        display_name = p.get("displayName") or ""
        instance = parse_panel_instance(display_name)
        if instance is None:
            continue
        a = node.get("a") or {}
        panels.append({
            "node_i": i,
            "node_id": node.get("i"),
            "displayName": display_name,
            "instance": instance,
            "existing_panel_list": a.get("panel.list"),
        })
    panels.sort(key=lambda x: x["instance"])
    return panels


def group_properties(properties: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for prop in properties:
        key = (prop["projectId"], prop["deviceId"])
        if key not in groups:
            groups[key] = {
                "projectId": prop["projectId"],
                "projectName": prop["projectName"],
                "deviceId": prop["deviceId"],
                "deviceName": prop["deviceName"],
                "instance": parse_device_instance(prop["deviceName"]),
                "props": [],
            }
        groups[key]["props"].append(prop)
    return list(groups.values())


def _candidate_key(prop: dict[str, Any]) -> str:
    return f"{prop['projectId']}#{prop['deviceId']}#{prop['propertyId']}"


def _component_similarity(
    expected: str,
    actual: str,
    similarity: SimilarityFn,
) -> float:
    if _normalize(expected) == _normalize(actual):
        return 1.0
    return round(similarity(expected, actual), 4)


def _confidence_for(score: float, lead: float) -> str:
    if score >= 0.85 and lead >= 0.08:
        return "high"
    if score >= 0.70 and lead >= 0.05:
        return "medium"
    if score >= 0.55:
        return "low"
    return "none"


def _build_candidates(
    expectation: dict[str, Any],
    groups: list[dict[str, Any]],
    panel_instance: int,
    similarity: SimilarityFn,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for group in groups:
        if group["instance"] != panel_instance:
            continue
        for prop in group["props"]:
            if not type_compatible(expectation["dataType"], prop["dataType"]):
                continue
            if expectation["writable"] != prop["writable"]:
                continue
            dev_sim = _component_similarity(
                expectation["deviceName"], prop["deviceName"], similarity
            )
            prop_sim = _component_similarity(
                expectation["property"], prop["propertyName"], similarity
            )
            score = round(0.35 * dev_sim + 0.65 * prop_sim, 4)
            evidence: list[str] = []
            if dev_sim >= 1.0:
                evidence.append("deviceName 规范化完全相等")
            if prop_sim >= 1.0:
                evidence.append("propertyName 规范化完全相等")
            evidence.append(
                f"deviceName 相似度 {dev_sim}, propertyName 相似度 {prop_sim}"
            )
            evidence.append(
                f"编号匹配 实例{group['instance']}, "
                f"dataType {expectation['dataType']}↔{prop['dataType']}, "
                f"writable {'可写' if expectation['writable'] else '只读'}"
            )
            candidates.append({
                "projectId": prop["projectId"],
                "projectName": prop["projectName"],
                "deviceId": prop["deviceId"],
                "deviceName": prop["deviceName"],
                "propertyId": prop["propertyId"],
                "propertyName": prop["propertyName"],
                "dataType": prop["dataType"],
                "writable": prop["writable"],
                "unit": prop.get("unit", ""),
                "dataTypeDesc": prop.get("dataTypeDesc", ""),
                "device_name_similarity": dev_sim,
                "property_name_similarity": prop_sim,
                "score": score,
                "evidence": evidence,
                "key": _candidate_key(prop),
            })

    candidates.sort(
        key=lambda c: (
            -c["score"],
            c["projectId"],
            c["deviceId"],
            c["propertyId"],
        )
    )
    for i, cand in enumerate(candidates[:5]):
        lead = 0.0
        if i + 1 < len(candidates):
            lead = round(cand["score"] - candidates[i + 1]["score"], 4)
        elif i == 0 and len(candidates) == 1:
            lead = round(cand["score"], 4)
        cand["lead"] = lead
        cand["confidence"] = _confidence_for(cand["score"], lead)
    return candidates[:5]


def match_properties(
    json_data: dict[str, Any],
    expectations: list[dict[str, Any]],
    properties: list[dict[str, Any]],
    similarity: Optional[SimilarityFn] = None,
) -> dict[str, Any]:
    if similarity is None:
        similarity = get_similarity().similarity

    panels = find_panels(json_data)
    groups = group_properties(properties)

    items: list[dict[str, Any]] = []
    for panel in panels:
        for expectation in expectations:
            candidates = _build_candidates(
                expectation, groups, panel["instance"], similarity
            )
            items.append({
                "panel_node_i": panel["node_i"],
                "panel_displayName": panel["displayName"],
                "panel_instance": panel["instance"],
                "expectation_id": expectation["id"],
                "expectation_property": expectation["property"],
                "expectation_required": expectation["required"],
                "candidates": candidates,
                "suggested": None,
                "confidence": "none",
                "confirmed": False,
            })

    assigned_groups: set[tuple[str, str]] = set()
    by_panel: dict[int, list[dict[str, Any]]] = {}
    for item in items:
        by_panel.setdefault(item["panel_instance"], []).append(item)

    for panel_instance in sorted(by_panel.keys()):
        panel_items = by_panel[panel_instance]
        pool: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for item in panel_items:
            for cand in item["candidates"]:
                gkey = (cand["projectId"], cand["deviceId"])
                pool.setdefault(gkey, []).append(cand)

        best_group: Optional[tuple[str, str]] = None
        best_total = -1.0
        for gkey, cands in pool.items():
            if gkey in assigned_groups:
                continue
            total = round(sum(c["score"] for c in cands) / len(cands), 4)
            if total > best_total:
                best_total = total
                best_group = gkey

        if best_group is not None:
            assigned_groups.add(best_group)
            for item in panel_items:
                available = [
                    c for c in item["candidates"]
                    if (c["projectId"], c["deviceId"]) == best_group
                ]
                if not available:
                    continue
                best = available[0]
                if best["confidence"] != "none":
                    item["suggested"] = best["key"]
                    item["confidence"] = best["confidence"]

    return {
        "panels": panels,
        "expectations": expectations,
        "items": items,
    }
