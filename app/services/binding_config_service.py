from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REQUIRED_KEYS = [
    "id",
    "handler",
    "displayName",
    "propertyName",
    "projectId",
    "projectName",
    "deviceId",
    "deviceName",
    "propertyId",
    "dataType",
    "dataTypeDesc",
    "writable",
]
ID_KEYS = ["projectId", "deviceId", "propertyId"]
STRING_KEYS = ["id", "handler", "displayName", "propertyName", "projectName", "deviceName", "dataTypeDesc"]
VALID_DATATYPES = {"double", "int", "bool", "string"}


class BindingConfigError(Exception):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def _validate_record(item: Any, line_no: int) -> list[str]:
    errors: list[str] = []
    if not isinstance(item, dict):
        return [f"第 {line_no} 行不是 JSON 对象"]
    for key in REQUIRED_KEYS:
        if key not in item:
            errors.append(f"第 {line_no} 行缺少字段: {key}")
    for key in STRING_KEYS:
        value = item.get(key)
        if not isinstance(value, str) or not value:
            errors.append(f"第 {line_no} 行 {key} 必须为非空字符串")
    for key in ID_KEYS:
        value = item.get(key)
        if not isinstance(value, str) or not value.isdigit():
            errors.append(f"第 {line_no} 行 {key} 必须为数字字符串")
    datatype = item.get("dataType")
    if not isinstance(datatype, str) or datatype not in VALID_DATATYPES:
        errors.append(
            f"第 {line_no} 行 dataType 非法: {datatype!r}，"
            f"仅支持 {', '.join(sorted(VALID_DATATYPES))}"
        )
    if not isinstance(item.get("writable"), bool):
        errors.append(f"第 {line_no} 行 writable 必须为布尔值")
    if "unit" in item and not isinstance(item["unit"], str):
        errors.append(f"第 {line_no} 行 unit 必须为字符串")
    return errors


def load_binding_registry(path: Path) -> list[dict]:
    errors: list[str] = []
    registry: list[dict] = []
    seen_ids: set[str] = set()
    seen_sources: set[tuple[str, str, str, str, str]] = set()

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
            source_key = (
                item["handler"],
                item["displayName"],
                item["projectId"],
                item["deviceId"],
                item["propertyId"],
            )
            if source_key in seen_sources:
                errors.append(
                    f"第 {line_no} 行重复物理源: handler={item['handler']} "
                    f"displayName={item['displayName']} "
                    f"projectId={item['projectId']} deviceId={item['deviceId']} "
                    f"propertyId={item['propertyId']}"
                )
                continue
            seen_ids.add(item_id)
            seen_sources.add(source_key)
            record = {key: item[key] for key in REQUIRED_KEYS}
            record["unit"] = item.get("unit", "")
            registry.append(record)

    if errors:
        raise BindingConfigError(errors)
    return registry
