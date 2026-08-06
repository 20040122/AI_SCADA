from __future__ import annotations

import copy
from typing import Any, Callable, Optional

from app.services.match_service import find_panels, type_compatible

Validator = Callable[[dict[str, Any]], list[str]]

DERIVED_DATATYPE_DESC = {
    "double": "双精度",
    "int": "整型",
    "bool": "布尔",
    "string": "字符串",
}


def _prop_key(prop: dict[str, Any]) -> tuple[str, str, str]:
    return (prop["projectId"], prop["deviceId"], prop["propertyId"])


def _find_property(
    properties: list[dict[str, Any]],
    project_id: str,
    device_id: str,
    property_id: str,
) -> Optional[dict[str, Any]]:
    for prop in properties:
        if (
            prop["projectId"] == project_id
            and prop["deviceId"] == device_id
            and prop["propertyId"] == property_id
        ):
            return prop
    return None


def _data_type_desc(prop: dict[str, Any]) -> str:
    desc = (prop.get("dataTypeDesc") or "").strip()
    if desc:
        return desc
    data_type = prop["dataType"]
    if data_type in DERIVED_DATATYPE_DESC:
        return DERIVED_DATATYPE_DESC[data_type]
    return data_type


def _panel_list_item(prop: dict[str, Any]) -> dict[str, Any]:
    unit = prop.get("unit") or ""
    if unit:
        bind_label = (
            f"{prop['projectName']} . {prop['deviceName']} . "
            f"{prop['propertyName']} ({unit})"
        )
    else:
        bind_label = (
            f"{prop['projectName']} . {prop['deviceName']} . "
            f"{prop['propertyName']}"
        )
    return {
        "label": prop["propertyName"],
        "bind": {
            "type": "designer",
            "path": f"{prop['projectId']}#{prop['deviceId']}#{prop['propertyId']}",
            "key": f"{prop['deviceId']}#{prop['propertyId']}",
            "label": bind_label,
            "proj": {"id": prop["projectId"], "name": prop["projectName"]},
            "dev": {"id": prop["deviceId"], "name": prop["deviceName"]},
            "param": {
                "id": prop["propertyId"],
                "name": prop["propertyName"],
                "unit": unit,
                "writable": prop["writable"],
                "dataType": prop["dataType"],
                "dataTypeDesc": _data_type_desc(prop),
            },
        },
    }


def build_bound_json(
    json_data: dict[str, Any],
    properties: list[dict[str, Any]],
    assignments: list[dict[str, Any]],
    expectations: Optional[list[dict[str, Any]]] = None,
    canvas_validator: Optional[Validator] = None,
    binding_validator: Optional[Validator] = None,
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    if not json_data:
        errors.append("没有可用画布")
    panels = find_panels(json_data) if json_data else []
    if not panels:
        errors.append("没有状态面板")
    panels_by_index = {p["node_i"]: p for p in panels}

    expected_by_id: dict[str, dict[str, Any]] = {}
    if expectations:
        expected_by_id = {e["id"]: e for e in expectations}

    by_panel: dict[int, list[dict[str, Any]]] = {}
    for assignment in assignments:
        node_index = assignment.get("panel_node_i")
        if node_index is None:
            errors.append(f"assignment 缺少 panel_node_i: {assignment}")
            continue
        by_panel.setdefault(int(node_index), []).append(assignment)

    device_to_panel: dict[tuple[str, str], int] = {}
    writable_reuse: dict[tuple[str, str, str], int] = {}
    readonly_reuse: dict[tuple[str, str, str], int] = {}
    resolved: dict[int, list[dict[str, Any]]] = {}

    for node_i, panel in panels_by_index.items():
        resolved_list: list[dict[str, Any]] = []
        for item in by_panel.get(node_i, []):
            expectation_id = item.get("expectation_id")
            cand = item.get("candidate") or {}
            prop = _find_property(
                properties,
                cand.get("projectId", ""),
                cand.get("deviceId", ""),
                cand.get("propertyId", ""),
            )
            if prop is None:
                errors.append(
                    f"面板 {panel['displayName']}: 候选属性 "
                    f"{cand.get('projectId')}#{cand.get('deviceId')}#{cand.get('propertyId')} "
                    f"不属于规范属性"
                )
                continue
            if expectations is not None:
                if expectation_id is None or expectation_id not in expected_by_id:
                    errors.append(
                        f"面板 {panel['displayName']}: 期望项 {expectation_id} 不在 JSONL 注册表中"
                    )
                    continue
                expectation = expected_by_id[expectation_id]
                if not type_compatible(expectation["dataType"], prop["dataType"]):
                    errors.append(
                        f"面板 {panel['displayName']}: 期望项 {expectation['property']} "
                        f"dataType {expectation['dataType']} 与属性 {prop['dataType']} 不兼容"
                    )
                if expectation["writable"] != prop["writable"]:
                    errors.append(
                        f"面板 {panel['displayName']}: 期望项 {expectation['property']} "
                        f"writable 与属性不兼容"
                    )
            dkey = (prop["projectId"], prop["deviceId"])
            if dkey in device_to_panel and device_to_panel[dkey] != node_i:
                errors.append(
                    f"设备 {prop['projectId']}#{prop['deviceId']} 被同时分配给多个状态面板"
                )
            else:
                device_to_panel[dkey] = node_i
            pkey = _prop_key(prop)
            if prop["writable"]:
                if pkey in writable_reuse:
                    errors.append(
                        f"可写属性 {prop['projectId']}#{prop['deviceId']}#{prop['propertyId']} "
                        f"被多个绑定复用"
                    )
                else:
                    writable_reuse[pkey] = node_i
            else:
                if pkey in readonly_reuse:
                    warnings.append(
                        f"只读属性 {prop['projectId']}#{prop['deviceId']}#{prop['propertyId']} "
                        f"被多个绑定复用"
                    )
                else:
                    readonly_reuse[pkey] = node_i
            resolved_list.append(_panel_list_item(prop))
        resolved[node_i] = resolved_list

    for node_i, panel in panels_by_index.items():
        assigned_ids = {item.get("expectation_id") for item in by_panel.get(node_i, [])}
        if expectations:
            for expectation in expectations:
                if expectation.get("required") and expectation["id"] not in assigned_ids:
                    errors.append(
                        f"面板 {panel['displayName']}: 必绑项 {expectation['property']} "
                        f"未匹配或未确认"
                    )

    bound_json: Optional[dict[str, Any]] = None
    if not errors:
        bound_json = copy.deepcopy(json_data)
        for node_i, panel in panels_by_index.items():
            node_a = bound_json["d"][node_i].setdefault("a", {})
            node_a["panel.list"] = resolved[node_i]

        if canvas_validator:
            errors.extend(f"Canvas Schema: {e}" for e in canvas_validator(bound_json))
        if binding_validator:
            for node_i, panel in panels_by_index.items():
                node_a = bound_json["d"][node_i].get("a", {})
                errors.extend(
                    f"Binding Schema (面板 {panel['displayName']}): {e}"
                    for e in binding_validator(node_a)
                )
        if errors:
            bound_json = None

    previews: list[dict[str, Any]] = []
    for node_i, panel in panels_by_index.items():
        previews.append({
            "node_i": node_i,
            "displayName": panel["displayName"],
            "instance": panel["instance"],
            "panel_list": resolved[node_i],
            "has_existing": panel.get("existing_panel_list") is not None,
        })

    return {
        "bound_json": bound_json,
        "previews": previews,
        "errors": errors,
        "warnings": warnings,
    }
