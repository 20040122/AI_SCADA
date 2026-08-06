from __future__ import annotations

import csv
import io
import re
from difflib import SequenceMatcher
from typing import Optional

MAX_CSV_BYTES = 5 * 1024 * 1024
MAX_CSV_ROWS = 10000

REQUIRED_FIELDS = [
    "projectId",
    "projectName",
    "deviceId",
    "deviceName",
    "propertyId",
    "propertyName",
    "dataType",
    "writable",
]
OPTIONAL_FIELDS = ["unit", "dataTypeDesc"]
ALL_FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS

FIELD_ALIASES: dict[str, list[str]] = {
    "projectId": ["projectId", "project_id", "project id", "项目ID", "项目编号", "工程ID"],
    "projectName": ["projectName", "project_name", "project name", "项目名称", "项目名"],
    "deviceId": ["deviceId", "device_id", "device id", "设备ID", "设备编号"],
    "deviceName": ["deviceName", "device_name", "device name", "设备名称", "设备名"],
    "propertyId": ["propertyId", "property_id", "property id", "属性ID", "属性编号", "变量ID"],
    "propertyName": ["propertyName", "property_name", "property name", "属性名称", "属性名"],
    "dataType": ["dataType", "data_type", "data type", "数据类型", "类型"],
    "writable": ["writable", "可写", "是否可写", "读写"],
    "unit": ["unit", "单位"],
    "dataTypeDesc": ["dataTypeDesc", "data_type_desc", "类型描述", "数据类型描述"],
}

DATATYPE_ALIASES: dict[str, list[str]] = {
    "double": ["double", "float", "real", "浮点", "双精度", "实数"],
    "int": ["int", "integer", "int32", "int16", "整型", "整数"],
    "bool": ["bool", "boolean", "bit", "布尔", "布尔型"],
    "string": ["string", "str", "text", "字符串", "文本"],
}

WRITABLE_ALIASES: dict[bool, list[str]] = {
    True: ["true", "1", "yes", "是", "可写"],
    False: ["false", "0", "no", "否", "只读"],
}


class CsvError(Exception):
    pass


class CsvEncodingError(CsvError):
    pass


class CsvTooLargeError(CsvError):
    pass


class CsvTooManyRowsError(CsvError):
    pass


def _normalize_column(name: str) -> str:
    return re.sub(r"[\s_\-]+", "", name).lower()


def _build_alias_lookup() -> dict[str, str]:
    lookup: dict[str, str] = {}
    for field, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            key = _normalize_column(alias)
            if key in lookup and lookup[key] != field:
                lookup[key] = "?"
            else:
                lookup.setdefault(key, field)
    return lookup


_ALIAS_LOOKUP = _build_alias_lookup()


def detect_encoding(data: bytes) -> str:
    if data.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    for enc in ("utf-8", "gb18030"):
        try:
            data.decode(enc)
            return enc
        except UnicodeDecodeError:
            continue
    raise CsvEncodingError("无法识别的编码，仅支持 UTF-8 / GB18030")


def _parse(data: bytes) -> tuple[str, list[str], list[list[str]]]:
    if len(data) > MAX_CSV_BYTES:
        raise CsvTooLargeError("CSV 超过 5MB 限制")
    encoding = detect_encoding(data)
    text = data.decode(encoding)
    reader = csv.reader(io.StringIO(text))
    rows = [row for row in reader if any(cell.strip() for cell in row)]
    if not rows:
        raise CsvError("CSV 为空")
    headers = [h.strip() for h in rows[0]]
    data_rows = rows[1:]
    if len(data_rows) > MAX_CSV_ROWS:
        raise CsvTooManyRowsError(f"CSV 超过 {MAX_CSV_ROWS} 行限制")
    return encoding, headers, data_rows


def suggest_mapping(headers: list[str]) -> dict:
    suggestions: list[dict] = []
    ambiguities: list[dict] = []
    used_columns: set[int] = set()
    matched_fields: set[str] = set()

    column_to_fields: dict[int, list[str]] = {}
    for col, header in enumerate(headers):
        key = _normalize_column(header)
        field = _ALIAS_LOOKUP.get(key)
        if field and field != "?":
            column_to_fields.setdefault(col, []).append(field)

    field_to_columns: dict[str, list[int]] = {}
    for col, fields in column_to_fields.items():
        if len(fields) > 1:
            ambiguities.append({
                "column": col,
                "header": headers[col],
                "matched_fields": fields,
            })
            continue
        field = fields[0]
        field_to_columns.setdefault(field, []).append(col)

    for field, cols in field_to_columns.items():
        if len(cols) > 1:
            ambiguities.append({
                "column": None,
                "header": None,
                "matched_fields": [field],
                "detail": "多个列映射到同一字段",
            })
            continue
        suggestions.append({"field": field, "column": cols[0], "source": "exact"})
        used_columns.add(cols[0])
        matched_fields.add(field)

    for field in ALL_FIELDS:
        if field in matched_fields:
            continue
        best_col: Optional[int] = None
        best_score = 0.0
        for col, header in enumerate(headers):
            if col in used_columns:
                continue
            hkey = _normalize_column(header)
            score = max(
                SequenceMatcher(None, hkey, _normalize_column(alias)).ratio()
                for alias in FIELD_ALIASES[field]
            )
            if score > best_score:
                best_score = score
                best_col = col
        if best_col is not None and best_score >= 0.5:
            suggestions.append({
                "field": field,
                "column": best_col,
                "source": "fuzzy",
            })
            used_columns.add(best_col)

    missing = [f for f in REQUIRED_FIELDS if f not in matched_fields]
    return {
        "suggestions": suggestions,
        "ambiguities": ambiguities,
        "missing": missing,
    }


def preview_csv(data: bytes) -> dict:
    encoding, headers, data_rows = _parse(data)
    mapping = suggest_mapping(headers)
    return {
        "encoding": encoding,
        "headers": headers,
        "total_rows": len(data_rows),
        "rows": data_rows[:20],
        "mapping": mapping,
    }


def _normalize_datatype(raw: str) -> Optional[str]:
    key = raw.strip().lower()
    for canonical, aliases in DATATYPE_ALIASES.items():
        if key in aliases:
            return canonical
    return None


def _parse_writable(raw: str) -> Optional[bool]:
    key = raw.strip().lower()
    for value, aliases in WRITABLE_ALIASES.items():
        if key in aliases:
            return value
    return None


def normalize_csv(data: bytes, mapping: dict[str, int]) -> dict:
    encoding, headers, data_rows = _parse(data)

    config_errors: list[str] = []
    missing = [f for f in REQUIRED_FIELDS if f not in mapping]
    if missing:
        config_errors.append(f"必填列未映射: {', '.join(missing)}")
    seen_columns: set[int] = set()
    for field, col in mapping.items():
        if col in seen_columns:
            config_errors.append(f"列 {col} 被映射到多个字段")
        seen_columns.add(col)
        if field not in ALL_FIELDS:
            config_errors.append(f"未知字段: {field}")
        elif not (0 <= col < len(headers)):
            config_errors.append(f"{field} 列索引越界: {col}")
    if config_errors:
        return {"properties": [], "errors": [], "blocked": True, "blocking": config_errors}

    properties: list[dict] = []
    errors: list[dict] = []
    blocking: list[dict] = []
    seen_ids: dict[tuple[str, str, str], dict] = {}

    def cell(row: list[str], col: Optional[int]) -> str:
        if col is None or col >= len(row):
            return ""
        return row[col].strip()

    for row_num, row in enumerate(data_rows, start=2):
        raw = {f: cell(row, mapping.get(f)) for f in ALL_FIELDS}

        if any(not raw[f] for f in REQUIRED_FIELDS):
            empty = [f for f in REQUIRED_FIELDS if not raw[f]]
            blocking.append({
                "row": row_num,
                "message": f"必填字段为空: {', '.join(empty)}",
            })
            continue

        ids_ok = True
        for idf in ("projectId", "deviceId", "propertyId"):
            if not raw[idf].isdigit():
                errors.append({
                    "row": row_num,
                    "message": f"{idf} 必须为数字字符串，实际为: {raw[idf]}",
                })
                ids_ok = False
        if not ids_ok:
            continue

        data_type = _normalize_datatype(raw["dataType"])
        if data_type is None:
            errors.append({
                "row": row_num,
                "message": f"dataType 无法识别: {raw['dataType']}",
            })
            continue

        writable = _parse_writable(raw["writable"])
        if writable is None:
            errors.append({
                "row": row_num,
                "message": f"writable 无法确定: {raw['writable']}",
            })
            continue

        id_key = (raw["projectId"], raw["deviceId"], raw["propertyId"])
        name_key = (raw["projectName"], raw["deviceName"], raw["propertyName"])
        if id_key in seen_ids:
            prev = seen_ids[id_key]
            if prev["names"] != name_key:
                blocking.append({
                    "row": row_num,
                    "message": f"重复 ID 对应不同名称: 行 {prev['row']} vs 行 {row_num}",
                })
            else:
                blocking.append({
                    "row": row_num,
                    "message": f"重复项目/设备/属性 ID: {id_key[0]}/{id_key[1]}/{id_key[2]}",
                })
            continue
        seen_ids[id_key] = {"row": row_num, "names": name_key}

        properties.append({
            "projectId": raw["projectId"],
            "projectName": raw["projectName"],
            "deviceId": raw["deviceId"],
            "deviceName": raw["deviceName"],
            "propertyId": raw["propertyId"],
            "propertyName": raw["propertyName"],
            "dataType": data_type,
            "writable": writable,
            "unit": raw["unit"],
            "dataTypeDesc": raw["dataTypeDesc"],
        })

    if blocking:
        return {
            "properties": [],
            "errors": [],
            "blocked": True,
            "blocking": blocking,
        }

    return {"properties": properties, "errors": errors, "blocked": False, "blocking": []}
