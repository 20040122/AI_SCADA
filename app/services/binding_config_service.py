from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REQUIRED_KEYS = [
    "id",
    "displayName",
    "deviceName",
    "property",
    "dataType",
    "writable",
    "required",
]
VALID_DATATYPES = {"double", "int", "bool", "string"}


class BindingConfigError(Exception):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def _validate_record(item: Any, line_no: int) -> list[str]:
    errors: list[str] = []
    if not isinstance(item, dict):
        return [f"第 {line_no} 行不是 JSON 对象"]
    missing = [k for k in REQUIRED_KEYS if k not in item]
    if missing:
        errors.append(f"第 {line_no} 行缺少字段: {', '.join(missing)}")
    if not isinstance(item.get("id", ""), str) or not item.get("id"):
        errors.append(f"第 {line_no} 行 id 必须为非空字符串")
    if not isinstance(item.get("displayName", ""), str) or not item.get("displayName"):
        errors.append(f"第 {line_no} 行 displayName 必须为非空字符串")
    if not isinstance(item.get("deviceName", ""), str) or not item.get("deviceName"):
        errors.append(f"第 {line_no} 行 deviceName 必须为非空字符串")
    if not isinstance(item.get("property", ""), str) or not item.get("property"):
        errors.append(f"第 {line_no} 行 property 必须为非空字符串")
    if not isinstance(item.get("dataType", ""), str) or item.get("dataType") not in VALID_DATATYPES:
        errors.append(
            f"第 {line_no} 行 dataType 非法: {item.get('dataType')!r}，"
            f"仅支持 {', '.join(sorted(VALID_DATATYPES))}"
        )
    if not isinstance(item.get("writable"), bool):
        errors.append(f"第 {line_no} 行 writable 必须为布尔值")
    if not isinstance(item.get("required"), bool):
        errors.append(f"第 {line_no} 行 required 必须为布尔值")
    return errors


def load_binding_registry(path: Path) -> list[dict]:
    errors: list[str] = []
    registry: list[dict] = []
    seen_ids: set[str] = set()

    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"第 {line_no} 行 JSON 解析失败: {exc}")
                continue
            line_errors = _validate_record(item, line_no)
            if line_errors:
                errors.extend(line_errors)
                continue
            item_id = item["id"]
            if item_id in seen_ids:
                errors.append(f"第 {line_no} 行 id 重复: {item_id}")
                continue
            seen_ids.add(item_id)
            registry.append({
                "id": item_id,
                "displayName": item["displayName"],
                "deviceName": item["deviceName"],
                "property": item["property"],
                "dataType": item["dataType"],
                "writable": bool(item["writable"]),
                "required": bool(item["required"]),
                "path": item.get("path", ""),
                "label": item.get("label", ""),
            })

    if errors:
        raise BindingConfigError(errors)
    return registry
