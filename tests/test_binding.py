from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.binding_config_service import (
    BindingConfigError,
    load_binding_registry,
)
from app.services.build_service import build_bound_json
from app.services.csv_service import (
    CsvEncodingError,
    CsvError,
    CsvTooLargeError,
    CsvTooManyRowsError,
    MAX_CSV_BYTES,
    MAX_CSV_ROWS,
    detect_encoding,
    normalize_csv,
    preview_csv,
    suggest_mapping,
)
from app.services.match_service import (
    match_properties,
    parse_device_instance,
    parse_panel_instance,
    type_compatible,
)


def _props(properties: list[dict]) -> list[dict]:
    return properties


BASIC_HEADER = "projectId,projectName,deviceId,deviceName,propertyId,propertyName,dataType,writable,unit"


def _basic_csv(rows: list[list[str]]) -> bytes:
    lines = [BASIC_HEADER] + [",".join(r) for r in rows]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _default_mapping() -> dict[str, int]:
    fields = ["projectId", "projectName", "deviceId", "deviceName", "propertyId", "propertyName", "dataType", "writable", "unit"]
    return {f: i for i, f in enumerate(fields)}


def _panel_canvas(*display_names: str) -> dict:
    return {
        "v": "1",
        "p": {"layers": [], "autoAdjustIndex": True, "hierarchicalRendering": False},
        "a": {"width": 1920, "fitContent": True, "rectSelectable": True, "pannable": True, "zoomable": True, "height": 1080},
        "contentRect": {"x": 0, "y": 0, "width": 1920, "height": 1080},
        "d": [
            {"c": "ht.Node", "i": f"n{i}", "p": {"displayName": name}, "a": {"layout.node": i}}
            for i, name in enumerate(display_names)
        ],
    }


def _expectations() -> list[dict]:
    return [
        {"id": "temp", "displayName": "状态面板", "deviceName": "空气罐", "property": "空气罐温度", "dataType": "int", "writable": False, "required": True},
        {"id": "press", "displayName": "状态面板", "deviceName": "空气罐", "property": "空气罐压力", "dataType": "double", "writable": False, "required": True},
    ]


class TestCsvEncoding:
    def test_utf8(self):
        data = _basic_csv([["1", "A", "2", "空气罐", "3", "温度", "int", "否", "°C"]])
        assert detect_encoding(data) == "utf-8"

    def test_utf8_bom(self):
        data = b"\xef\xbb\xbf" + _basic_csv([["1", "A", "2", "空气罐", "3", "温度", "int", "否", "°C"]])
        assert detect_encoding(data) == "utf-8-sig"

    def test_gb18030(self):
        text = "项目ID,项目名称,设备ID,设备名称,属性ID,属性名称,数据类型,可写,单位\n1,项目A,2,空气罐,3,温度,int,否,℃\n"
        data = text.encode("gb18030")
        assert detect_encoding(data) == "gb18030"

    def test_reject_unknown_encoding(self):
        data = bytes(range(256)) * 4
        with pytest.raises(CsvEncodingError):
            detect_encoding(data)

    def test_too_large(self):
        data = _basic_csv([["1", "A", "2", "空气罐", "3", "温度", "int", "否", "°C"]])
        data = data + b"0" * (MAX_CSV_BYTES + 1)
        with pytest.raises(CsvTooLargeError):
            preview_csv(data)

    def test_too_many_rows(self):
        rows = [["1", "A", "2", "空气罐", "3", "温度", "int", "否", "°C"]] * (MAX_CSV_ROWS + 1)
        with pytest.raises(CsvTooManyRowsError):
            preview_csv(_basic_csv(rows))

    def test_empty_csv(self):
        with pytest.raises(CsvError):
            preview_csv(b"")

    def test_quoted_fields(self):
        data = "projectId,projectName,deviceName,propertyId,propertyName,dataType,writable\n1,\"项目,A\",空气罐,3,\"温,度\",int,否\n".encode("utf-8")
        result = preview_csv(data)
        assert result["rows"][0][1] == "项目,A"
        assert result["rows"][0][4] == "温,度"


class TestCsvMapping:
    def test_english_exact(self):
        headers = ["projectId", "projectName", "deviceId", "deviceName", "propertyId", "propertyName", "dataType", "writable"]
        m = suggest_mapping(headers)
        suggested = {s["field"]: s["column"] for s in m["suggestions"] if s["source"] == "exact"}
        assert suggested == {
            "projectId": 0, "projectName": 1, "deviceId": 2, "deviceName": 3,
            "propertyId": 4, "propertyName": 5, "dataType": 6, "writable": 7,
        }
        assert m["missing"] == []

    def test_chinese_aliases(self):
        headers = ["项目ID", "项目名称", "设备ID", "设备名称", "属性ID", "属性名称", "数据类型", "可写"]
        m = suggest_mapping(headers)
        exact = {s["field"]: s["column"] for s in m["suggestions"] if s["source"] == "exact"}
        assert exact["projectId"] == 0
        assert exact["projectName"] == 1
        assert exact["deviceId"] == 2
        assert exact["deviceName"] == 3
        assert exact["propertyId"] == 4
        assert exact["propertyName"] == 5
        assert exact["dataType"] == 6
        assert exact["writable"] == 7

    def test_aliases_with_spaces_case(self):
        headers = ["Project ID", "project_name", "Device-Id", "设备名称", "属性ID", "属性名称", "DATA TYPE", "可写"]
        m = suggest_mapping(headers)
        exact = {s["field"]: s["column"] for s in m["suggestions"] if s["source"] == "exact"}
        assert exact["projectId"] == 0
        assert exact["projectName"] == 1
        assert exact["deviceId"] == 2

    def test_fuzzy_suggestion_prefill(self):
        headers = ["项目标识", "设备标识", "属性标识"]
        m = suggest_mapping(headers)
        fuzzy = {s["field"]: s["column"] for s in m["suggestions"] if s["source"] == "fuzzy"}
        assert "projectId" in fuzzy
        assert "deviceId" in fuzzy
        assert "propertyId" in fuzzy

    def test_ambiguity_two_columns_same_field(self):
        headers = ["projectId", "项目ID", "projectName"]
        m = suggest_mapping(headers)
        assert m["ambiguities"]
        assert any(a["matched_fields"] == ["projectId"] for a in m["ambiguities"])

    def test_manual_mapping_overrides(self):
        mapping = {"projectId": 0, "projectName": 0}
        result = normalize_csv(_basic_csv([["1", "A", "2", "空气罐", "3", "温度", "int", "否", "°C"]]), mapping)
        assert result["blocked"] is True
        assert any("列 0 被映射到多个字段" in b for b in result["blocking"])


class TestCsvNormalize:
    def test_valid_normalize(self):
        rows = [
            ["1", "A", "2", "空气罐", "3", "温度", "integer", "只读", "°C"],
            ["1", "A", "2", "空气罐", "4", "压力", "float", "否", "MPa"],
            ["1", "A", "2", "空气罐", "5", "运行", "bool", "是", ""],
            ["1", "A", "2", "空气罐", "6", "状态", "string", "true", ""],
        ]
        result = normalize_csv(_basic_csv(rows), _default_mapping())
        assert result["blocked"] is False
        props = result["properties"]
        assert props[0]["dataType"] == "int"
        assert props[1]["dataType"] == "double"
        assert props[2]["dataType"] == "bool"
        assert props[3]["dataType"] == "string"
        assert props[0]["writable"] is False
        assert props[2]["writable"] is True
        assert props[0]["unit"] == "°C"

    def test_writable_aliases(self):
        for alias, expected in [("true", True), ("1", True), ("yes", True), ("是", True), ("可写", True),
                                ("false", False), ("0", False), ("no", False), ("否", False), ("只读", False)]:
            rows = [["1", "A", "2", "空气罐", "3", "温度", "int", alias, ""]]
            result = normalize_csv(_basic_csv(rows), _default_mapping())
            assert result["blocked"] is False, alias
            assert result["properties"][0]["writable"] is expected, alias

    def test_datatype_aliases(self):
        for alias, expected in [("double", "double"), ("float", "double"), ("real", "double"), ("浮点", "double"),
                                ("int", "int"), ("integer", "int"), ("int32", "int"), ("整型", "int"),
                                ("bool", "bool"), ("boolean", "bool"), ("bit", "bool"), ("布尔", "bool"),
                                ("string", "string"), ("str", "string"), ("text", "string"), ("字符串", "string")]:
            rows = [["1", "A", "2", "空气罐", "3", "温度", alias, "否", ""]]
            result = normalize_csv(_basic_csv(rows), _default_mapping())
            assert result["blocked"] is False, alias
            assert result["properties"][0]["dataType"] == expected, alias

    def test_unknown_datatype_row_error(self):
        rows = [["1", "A", "2", "空气罐", "3", "温度", "hex", "否", ""]]
        result = normalize_csv(_basic_csv(rows), _default_mapping())
        assert result["blocked"] is False
        assert result["properties"] == []
        assert any("dataType 无法识别" in e["message"] for e in result["errors"])
        assert result["errors"][0]["row"] == 2

    def test_unknown_writable_row_error(self):
        rows = [["1", "A", "2", "空气罐", "3", "温度", "int", "maybe", ""]]
        result = normalize_csv(_basic_csv(rows), _default_mapping())
        assert result["properties"] == []
        assert any("writable 无法确定" in e["message"] for e in result["errors"])

    def test_non_digit_id_row_error(self):
        rows = [["1", "A", "2", "空气罐", "abc", "温度", "int", "否", ""]]
        result = normalize_csv(_basic_csv(rows), _default_mapping())
        assert any("propertyId 必须为数字字符串" in e["message"] for e in result["errors"])

    def test_empty_required_blocking(self):
        rows = [["1", "A", "", "空气罐", "3", "温度", "int", "否", ""]]
        result = normalize_csv(_basic_csv(rows), _default_mapping())
        assert result["blocked"] is True
        assert any("必填字段为空" in b["message"] for b in result["blocking"])

    def test_duplicate_id_same_name_row_error(self):
        rows = [
            ["1", "A", "2", "空气罐", "3", "温度", "int", "否", ""],
            ["1", "A", "2", "空气罐", "3", "温度", "int", "否", ""],
        ]
        result = normalize_csv(_basic_csv(rows), _default_mapping())
        assert result["blocked"] is True
        assert any("重复项目/设备/属性 ID" in b["message"] for b in result["blocking"])

    def test_duplicate_id_different_name_blocking(self):
        rows = [
            ["1", "A", "2", "空气罐", "3", "温度", "int", "否", ""],
            ["1", "A", "2", "空气罐", "3", "温标", "int", "否", ""],
        ]
        result = normalize_csv(_basic_csv(rows), _default_mapping())
        assert result["blocked"] is True
        assert any("重复 ID 对应不同名称" in b["message"] for b in result["blocking"])

    def test_missing_required_mapping_blocking(self):
        mapping = {"projectId": 0, "projectName": 1, "deviceId": 2, "deviceName": 3, "propertyId": 4, "propertyName": 5, "dataType": 6}
        result = normalize_csv(_basic_csv([["1", "A", "2", "空气罐", "3", "温度", "int", "否", ""]]), mapping)
        assert result["blocked"] is True
        assert any("必填列未映射" in b for b in result["blocking"])

    def test_column_index_out_of_bounds(self):
        mapping = dict(_default_mapping())
        mapping["writable"] = 99
        result = normalize_csv(_basic_csv([["1", "A", "2", "空气罐", "3", "温度", "int", "否", ""]]), mapping)
        assert result["blocked"] is True

    def test_preview_first_20_rows(self):
        rows = [["1", "A", "2", "空气罐", str(i), "温度", "int", "否", ""] for i in range(25)]
        result = preview_csv(_basic_csv(rows))
        assert result["total_rows"] == 25
        assert len(result["rows"]) == 20


class TestBindingRegistry:
    def test_load_valid(self, tmp_path: Path):
        p = tmp_path / "binding.jsonl"
        p.write_text(
            '{"id":"a","displayName":"状态面板","deviceName":"空气罐","property":"温度","dataType":"int","writable":false,"required":true}\n'
            '{"id":"b","displayName":"状态面板","deviceName":"空气罐","property":"压力","dataType":"double","writable":false,"required":true}\n',
            encoding="utf-8",
        )
        reg = load_binding_registry(p)
        assert [r["id"] for r in reg] == ["a", "b"]
        assert reg[0]["dataType"] == "int"

    def test_duplicate_id(self, tmp_path: Path):
        p = tmp_path / "binding.jsonl"
        p.write_text(
            '{"id":"a","displayName":"状态面板","deviceName":"空气罐","property":"温度","dataType":"int","writable":false,"required":true}\n'
            '{"id":"a","displayName":"状态面板","deviceName":"空气罐","property":"压力","dataType":"int","writable":false,"required":true}\n',
            encoding="utf-8",
        )
        with pytest.raises(BindingConfigError) as exc:
            load_binding_registry(p)
        assert any("id 重复" in e for e in exc.value.errors)

    def test_missing_field(self, tmp_path: Path):
        p = tmp_path / "binding.jsonl"
        p.write_text('{"id":"a","displayName":"状态面板","deviceName":"空气罐","property":"温度","dataType":"int"}\n', encoding="utf-8")
        with pytest.raises(BindingConfigError) as exc:
            load_binding_registry(p)
        assert any("缺少字段" in e for e in exc.value.errors)

    def test_illegal_datatype(self, tmp_path: Path):
        p = tmp_path / "binding.jsonl"
        p.write_text('{"id":"a","displayName":"状态面板","deviceName":"空气罐","property":"温度","dataType":"int16","writable":false,"required":true}\n', encoding="utf-8")
        with pytest.raises(BindingConfigError) as exc:
            load_binding_registry(p)
        assert any("dataType 非法" in e for e in exc.value.errors)

    def test_non_bool_writable(self, tmp_path: Path):
        p = tmp_path / "binding.jsonl"
        p.write_text('{"id":"a","displayName":"状态面板","deviceName":"空气罐","property":"温度","dataType":"int","writable":"false","required":true}\n', encoding="utf-8")
        with pytest.raises(BindingConfigError) as exc:
            load_binding_registry(p)
        assert any("writable 必须为布尔值" in e for e in exc.value.errors)

    def test_json_syntax_error(self, tmp_path: Path):
        p = tmp_path / "binding.jsonl"
        p.write_text('{"id": "a", broken\n', encoding="utf-8")
        with pytest.raises(BindingConfigError):
            load_binding_registry(p)

    def test_path_label_preserved_as_reference(self, tmp_path: Path):
        p = tmp_path / "binding.jsonl"
        p.write_text('{"id":"a","displayName":"状态面板","deviceName":"空气罐","property":"温度","dataType":"int","writable":false,"required":true,"path":"1#2#3","label":"样本"}\n', encoding="utf-8")
        reg = load_binding_registry(p)
        assert reg[0]["path"] == "1#2#3"
        assert reg[0]["label"] == "样本"


class TestMatchRules:
    def test_panel_instance_parsing(self):
        assert parse_panel_instance("状态面板") == 1
        assert parse_panel_instance("状态面板2") == 2
        assert parse_panel_instance("状态面板02") == 2
        assert parse_panel_instance("其他控件") is None

    def test_device_instance_parsing(self):
        assert parse_device_instance("空气罐") == 1
        assert parse_device_instance("空气罐2") == 2
        assert parse_device_instance("空气罐02") == 2
        assert parse_device_instance("空气罐A") == 1

    def test_type_compatible(self):
        assert type_compatible("int", "int") is True
        assert type_compatible("int", "double") is True
        assert type_compatible("double", "int") is True
        assert type_compatible("bool", "int") is False
        assert type_compatible("string", "string") is True

    def _similarity(self, a: str, b: str) -> float:
        na = a.replace(" ", "")
        nb = b.replace(" ", "")
        if na == nb:
            return 1.0
        if na in nb or nb in na:
            return 0.8
        return 0.3

    def test_exact_match_high_confidence(self):
        canvas = _panel_canvas("状态面板")
        props = [
            {"projectId": "1", "projectName": "A", "deviceId": "2", "deviceName": "空气罐", "propertyId": "3", "propertyName": "空气罐温度", "dataType": "int", "writable": False, "unit": "", "dataTypeDesc": ""},
            {"projectId": "1", "projectName": "A", "deviceId": "2", "deviceName": "空气罐", "propertyId": "4", "propertyName": "空气罐压力", "dataType": "double", "writable": False, "unit": "", "dataTypeDesc": ""},
        ]
        result = match_properties(canvas, _expectations(), props, similarity=self._similarity)
        assert result["panels"][0]["instance"] == 1
        for item in result["items"]:
            assert item["suggested"] is not None
            assert item["confidence"] == "high"

    def test_semantic_similarity_used(self):
        canvas = _panel_canvas("状态面板")
        props = [
            {"projectId": "1", "projectName": "A", "deviceId": "2", "deviceName": "空气罐", "propertyId": "3", "propertyName": "空气罐温度采集", "dataType": "int", "writable": False, "unit": "", "dataTypeDesc": ""},
        ]
        result = match_properties(canvas, [_expectations()[0]], props, similarity=self._similarity)
        item = result["items"][0]
        assert item["candidates"][0]["property_name_similarity"] == 0.8
        assert item["candidates"][0]["score"] == round(0.35 * 1.0 + 0.65 * 0.8, 4)

    def test_numbering_multi_instance(self):
        canvas = _panel_canvas("状态面板", "状态面板2")
        props = [
            {"projectId": "1", "projectName": "A", "deviceId": "2", "deviceName": "空气罐", "propertyId": "3", "propertyName": "空气罐温度", "dataType": "int", "writable": False, "unit": "", "dataTypeDesc": ""},
            {"projectId": "1", "projectName": "A", "deviceId": "2", "deviceName": "空气罐", "propertyId": "4", "propertyName": "空气罐压力", "dataType": "double", "writable": False, "unit": "", "dataTypeDesc": ""},
            {"projectId": "1", "projectName": "A", "deviceId": "20", "deviceName": "空气罐2", "propertyId": "5", "propertyName": "空气罐温度", "dataType": "int", "writable": False, "unit": "", "dataTypeDesc": ""},
            {"projectId": "1", "projectName": "A", "deviceId": "20", "deviceName": "空气罐2", "propertyId": "6", "propertyName": "空气罐压力", "dataType": "double", "writable": False, "unit": "", "dataTypeDesc": ""},
        ]
        result = match_properties(canvas, _expectations(), props, similarity=self._similarity)
        for item in result["items"]:
            suggested = next(c for c in item["candidates"] if c["key"] == item["suggested"])
            dev = suggested["deviceName"]
            if item["panel_instance"] == 1:
                assert dev == "空气罐"
            else:
                assert dev == "空气罐2"

    def test_device_group_not_reused_between_panels(self):
        canvas = _panel_canvas("状态面板", "状态面板2")
        props = [
            {"projectId": "1", "projectName": "A", "deviceId": "2", "deviceName": "空气罐", "propertyId": "3", "propertyName": "空气罐温度", "dataType": "int", "writable": False, "unit": "", "dataTypeDesc": ""},
            {"projectId": "1", "projectName": "A", "deviceId": "2", "deviceName": "空气罐", "propertyId": "4", "propertyName": "空气罐压力", "dataType": "double", "writable": False, "unit": "", "dataTypeDesc": ""},
        ]
        result = match_properties(canvas, _expectations(), props, similarity=self._similarity)
        assigned = set()
        for item in result["items"]:
            if item["suggested"]:
                cand = next(c for c in item["candidates"] if c["key"] == item["suggested"])
                assigned.add((cand["projectId"], cand["deviceId"]))
        assert len(assigned) <= 1

    def test_type_filter(self):
        canvas = _panel_canvas("状态面板")
        props = [
            {"projectId": "1", "projectName": "A", "deviceId": "2", "deviceName": "空气罐", "propertyId": "3", "propertyName": "空气罐温度", "dataType": "string", "writable": False, "unit": "", "dataTypeDesc": ""},
        ]
        result = match_properties(canvas, [_expectations()[0]], props, similarity=self._similarity)
        assert result["items"][0]["candidates"] == []

    def test_writable_filter(self):
        canvas = _panel_canvas("状态面板")
        props = [
            {"projectId": "1", "projectName": "A", "deviceId": "2", "deviceName": "空气罐", "propertyId": "3", "propertyName": "空气罐温度", "dataType": "int", "writable": True, "unit": "", "dataTypeDesc": ""},
        ]
        result = match_properties(canvas, [_expectations()[0]], props, similarity=self._similarity)
        assert result["items"][0]["candidates"] == []

    def test_stable_sort(self):
        canvas = _panel_canvas("状态面板")
        props = [
            {"projectId": "10", "projectName": "A", "deviceId": "2", "deviceName": "空气罐", "propertyId": "1", "propertyName": "空气罐温度", "dataType": "int", "writable": False, "unit": "", "dataTypeDesc": ""},
            {"projectId": "2", "projectName": "A", "deviceId": "2", "deviceName": "空气罐", "propertyId": "1", "propertyName": "空气罐温度", "dataType": "int", "writable": False, "unit": "", "dataTypeDesc": ""},
        ]
        result = match_properties(canvas, [_expectations()[0]], props, similarity=self._similarity)
        keys = [c["key"] for c in result["items"][0]["candidates"]]
        assert keys == sorted(keys)

    def test_confidence_boundaries(self):
        low_sim = self._similarity
        canvas = _panel_canvas("状态面板")
        props = [
            {"projectId": "1", "projectName": "A", "deviceId": "2", "deviceName": "完全不同", "propertyId": "3", "propertyName": "完全不同", "dataType": "int", "writable": False, "unit": "", "dataTypeDesc": ""},
        ]
        result = match_properties(canvas, [_expectations()[0]], props, similarity=low_sim)
        item = result["items"][0]
        if item["candidates"]:
            cand = item["candidates"][0]
            if cand["score"] < 0.55:
                assert item["suggested"] is None
                assert item["confidence"] == "none"
            else:
                assert item["confidence"] in ("low", "medium", "high")

    def test_top5_candidates(self):
        canvas = _panel_canvas("状态面板")
        props = [
            {"projectId": "1", "projectName": "A", "deviceId": str(i), "deviceName": "空气罐", "propertyId": str(i), "propertyName": "空气罐温度", "dataType": "int", "writable": False, "unit": "", "dataTypeDesc": ""}
            for i in range(10)
        ]
        result = match_properties(canvas, [_expectations()[0]], props, similarity=self._similarity)
        assert len(result["items"][0]["candidates"]) <= 5

    def test_all_items_start_unconfirmed(self):
        canvas = _panel_canvas("状态面板")
        props = [
            {"projectId": "1", "projectName": "A", "deviceId": "2", "deviceName": "空气罐", "propertyId": "3", "propertyName": "空气罐温度", "dataType": "int", "writable": False, "unit": "", "dataTypeDesc": ""},
        ]
        result = match_properties(canvas, [_expectations()[0]], props, similarity=self._similarity)
        assert result["items"][0]["confirmed"] is False


class TestBuild:
    def _props(self):
        return [
            {"projectId": "1", "projectName": "项目一", "deviceId": "2", "deviceName": "空气罐", "propertyId": "3", "propertyName": "空气罐温度", "dataType": "int", "writable": False, "unit": "°C", "dataTypeDesc": ""},
            {"projectId": "1", "projectName": "项目一", "deviceId": "2", "deviceName": "空气罐", "propertyId": "4", "propertyName": "空气罐压力", "dataType": "double", "writable": False, "unit": "MPa", "dataTypeDesc": ""},
        ]

    def _assignments(self, props):
        return [
            {"panel_node_i": 0, "expectation_id": "temp", "candidate": props[0]},
            {"panel_node_i": 0, "expectation_id": "press", "candidate": props[1]},
        ]

    def test_panel_list_exact_structure(self):
        canvas = _panel_canvas("状态面板")
        props = self._props()
        result = build_bound_json(canvas, props, self._assignments(props), expectations=_expectations())
        assert result["errors"] == []
        bound = result["bound_json"]
        panel_list = bound["d"][0]["a"]["panel.list"]
        assert panel_list[0] == {
            "label": "空气罐温度",
            "bind": {
                "type": "designer",
                "path": "1#2#3",
                "key": "2#3",
                "label": "项目一 . 空气罐 . 空气罐温度 (°C)",
                "proj": {"id": "1", "name": "项目一"},
                "dev": {"id": "2", "name": "空气罐"},
                "param": {
                    "id": "3",
                    "name": "空气罐温度",
                    "unit": "°C",
                    "writable": False,
                    "dataType": "int",
                    "dataTypeDesc": "整型",
                },
            },
        }

    def test_no_empty_unit_parens(self):
        canvas = _panel_canvas("状态面板")
        props = self._props()
        props[0]["unit"] = ""
        result = build_bound_json(canvas, props, self._assignments(props), expectations=_expectations())
        bind_label = result["bound_json"]["d"][0]["a"]["panel.list"][0]["bind"]["label"]
        assert bind_label == "项目一 . 空气罐 . 空气罐温度"
        assert "()" not in bind_label

    def test_data_type_desc_from_csv(self):
        canvas = _panel_canvas("状态面板")
        props = self._props()
        props[0]["dataTypeDesc"] = "摄氏温度"
        result = build_bound_json(canvas, props, self._assignments(props), expectations=_expectations())
        assert result["bound_json"]["d"][0]["a"]["panel.list"][0]["bind"]["param"]["dataTypeDesc"] == "摄氏温度"

    def test_full_old_list_replacement(self):
        canvas = _panel_canvas("状态面板")
        canvas["d"][0]["a"]["panel.list"] = [{"old": True}]
        props = self._props()
        result = build_bound_json(canvas, props, self._assignments(props), expectations=_expectations())
        bound_list = result["bound_json"]["d"][0]["a"]["panel.list"]
        assert len(bound_list) == 2
        assert all("old" not in item for item in bound_list)

    def test_original_canvas_unchanged(self):
        canvas = _panel_canvas("状态面板")
        props = self._props()
        build_bound_json(canvas, props, self._assignments(props), expectations=_expectations())
        assert "panel.list" not in canvas["d"][0]["a"]

    def test_non_target_nodes_unchanged(self):
        canvas = _panel_canvas("其他控件", "状态面板")
        props = self._props()
        assignments = [
            {"panel_node_i": 1, "expectation_id": "temp", "candidate": props[0]},
            {"panel_node_i": 1, "expectation_id": "press", "candidate": props[1]},
        ]
        result = build_bound_json(canvas, props, assignments, expectations=_expectations())
        assert result["bound_json"]["d"][0] == canvas["d"][0]
        assert "panel.list" not in result["bound_json"]["d"][0]["a"]

    def test_layout_metadata_preserved(self):
        canvas = _panel_canvas("状态面板")
        canvas["d"][0]["a"]["layout.group"] = "G"
        canvas["d"][0]["a"]["layout.materialName"] = "M"
        props = self._props()
        result = build_bound_json(canvas, props, self._assignments(props), expectations=_expectations())
        a = result["bound_json"]["d"][0]["a"]
        assert a["layout.group"] == "G"
        assert a["layout.materialName"] == "M"
        assert a["panel.list"]

    def test_required_missing_blocks(self):
        canvas = _panel_canvas("状态面板")
        props = self._props()
        assignments = self._assignments(props)[:1]
        result = build_bound_json(canvas, props, assignments, expectations=_expectations())
        assert result["bound_json"] is None
        assert any("必绑项" in e for e in result["errors"])

    def test_candidate_not_in_properties(self):
        canvas = _panel_canvas("状态面板")
        props = self._props()
        assignments = self._assignments(props)
        assignments[0]["candidate"] = {"projectId": "99", "deviceId": "98", "propertyId": "97"}
        result = build_bound_json(canvas, props, assignments, expectations=_expectations())
        assert result["bound_json"] is None
        assert any("不属于规范属性" in e for e in result["errors"])

    def test_device_reuse_across_panels_blocks(self):
        canvas = _panel_canvas("状态面板", "状态面板2")
        props = self._props()
        assignments = [
            {"panel_node_i": 0, "expectation_id": "temp", "candidate": props[0]},
            {"panel_node_i": 1, "expectation_id": "temp", "candidate": props[0]},
            {"panel_node_i": 0, "expectation_id": "press", "candidate": props[1]},
        ]
        result = build_bound_json(canvas, props, assignments, expectations=_expectations())
        assert result["bound_json"] is None
        assert any("同时分配给多个状态面板" in e for e in result["errors"])

    def test_writable_property_reuse_blocks(self):
        canvas = _panel_canvas("状态面板")
        props = self._props()
        props[0]["writable"] = True
        assignments = [
            {"panel_node_i": 0, "expectation_id": "temp", "candidate": props[0]},
            {"panel_node_i": 0, "expectation_id": "press", "candidate": props[0]},
        ]
        result = build_bound_json(canvas, props, assignments, expectations=_expectations())
        assert result["bound_json"] is None
        assert any("被多个绑定复用" in e for e in result["errors"])

    def test_readonly_reuse_warning(self):
        canvas = _panel_canvas("状态面板")
        props = self._props()
        assignments = [
            {"panel_node_i": 0, "expectation_id": "temp", "candidate": props[0]},
            {"panel_node_i": 0, "expectation_id": "press", "candidate": props[0]},
        ]
        result = build_bound_json(canvas, props, assignments, expectations=_expectations())
        assert result["bound_json"] is not None
        assert any("只读属性" in w and "复用" in w for w in result["warnings"])

    def test_no_panel_blocks(self):
        canvas = _panel_canvas("其他控件")
        props = self._props()
        result = build_bound_json(canvas, props, [], expectations=_expectations())
        assert result["bound_json"] is None
        assert any("没有状态面板" in e for e in result["errors"])

    def test_schema_validator_hooks(self):
        canvas = _panel_canvas("状态面板")
        props = self._props()
        assignments = self._assignments(props)
        result = build_bound_json(
            canvas, props, assignments, expectations=_expectations(),
            canvas_validator=lambda jd: ["canvas bad"],
            binding_validator=lambda a: ["binding bad"],
        )
        assert result["bound_json"] is None
        assert any("Canvas Schema" in e for e in result["errors"])
        assert any("Binding Schema" in e for e in result["errors"])

    def test_invalid_expectation_id(self):
        canvas = _panel_canvas("状态面板")
        props = self._props()
        assignments = [
            {"panel_node_i": 0, "expectation_id": "ghost", "candidate": props[0]},
            {"panel_node_i": 0, "expectation_id": "press", "candidate": props[1]},
        ]
        result = build_bound_json(canvas, props, assignments, expectations=_expectations())
        assert result["bound_json"] is None
        assert any("不在 JSONL 注册表中" in e for e in result["errors"])


class TestSchemaFiles:
    def test_binding_schema_rejects_old_shape(self):
        import jsonschema
        from app.config import settings
        schema = json.loads(Path(settings.binding_schema_path).read_text(encoding="utf-8"))
        validator = jsonschema.Draft7Validator(schema)
        old = {"panel.list": [{"controlId": "x", "property": "status", "variable": "v", "dataType": "int16", "registerAddress": "1"}]}
        errors = list(validator.iter_errors(old))
        assert errors, "旧模型不应通过新 Binding Schema"

    def test_binding_schema_accepts_new_shape(self):
        import jsonschema
        from app.config import settings
        schema = json.loads(Path(settings.binding_schema_path).read_text(encoding="utf-8"))
        validator = jsonschema.Draft7Validator(schema)
        good = {"panel.list": [{
            "label": "温度",
            "bind": {
                "type": "designer",
                "path": "1#2#3",
                "key": "2#3",
                "label": "A . B . 温度 (°C)",
                "proj": {"id": "1", "name": "A"},
                "dev": {"id": "2", "name": "B"},
                "param": {"id": "3", "name": "温度", "unit": "°C", "writable": False, "dataType": "int", "dataTypeDesc": "整型"},
            },
        }]}
        errors = list(validator.iter_errors(good))
        assert errors == []


class TestTop1Accuracy:
    @pytest.mark.skipif(
        not Path(__file__).resolve().parent.joinpath("fixtures", "binding", "ground_truth.json").exists(),
        reason="真值集缺失，不得伪造 Top-1 结果",
    )
    def test_top1_on_fixed_truth_set(self):
        fixture_dir = Path(__file__).resolve().parent.joinpath("fixtures", "binding")
        ground_truth = json.loads((fixture_dir / "ground_truth.json").read_text(encoding="utf-8"))
        properties = _load_fixture_properties(fixture_dir)
        canvas = _build_canvas_from_truth(ground_truth)
        expectations = load_binding_registry(Path(__file__).resolve().parent.parent / "data" / "binding.jsonl")
        result = match_properties(canvas, expectations, properties)
        correct = 0
        total = 0
        for item in result["items"]:
            if item["suggested"] is None:
                continue
            total += 1
            cand = next(c for c in item["candidates"] if c["key"] == item["suggested"])
            truth = {
                "panelInstance": item["panel_instance"],
                "expectationId": item["expectation_id"],
                "projectId": cand["projectId"],
                "deviceId": cand["deviceId"],
                "propertyId": cand["propertyId"],
            }
            if truth in ground_truth["mappings"]:
                correct += 1
        assert total > 0
        assert correct / total >= 0.75


def _load_fixture_properties(fixture_dir: Path) -> list[dict]:
    csv_path = fixture_dir / "properties.csv"
    assert csv_path.exists()
    result = normalize_csv(csv_path.read_bytes(), _default_mapping())
    assert result["blocked"] is False
    return result["properties"]


def _build_canvas_from_truth(ground_truth: dict) -> dict:
    instances = sorted({m["panelInstance"] for m in ground_truth["mappings"]})
    names = ["状态面板"] + [f"状态面板{i}" for i in range(2, max(instances) + 1)]
    return _panel_canvas(*[names[i - 1] for i in instances])
