from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.binding_config_service import (
    BindingConfigError,
    load_binding_registry,
)
from app.services.csv_service import (
    CsvEncodingError,
    CsvError,
    CsvTooLargeError,
    CsvTooManyRowsError,
    MAX_CSV_BYTES,
    MAX_CSV_ROWS,
    detect_encoding,
    preview_csv,
)
from model.binding_agent import BindingAgent, PanelListHandler, _panel_list_item

CSV_HEADER = "displayName,propertyName"


def _csv(rows: list[list[str]]) -> bytes:
    lines = [CSV_HEADER] + [",".join(r) for r in rows]
    return ("\n".join(lines) + "\n").encode("utf-8")


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


class FakeSimilarity:
    def __init__(self) -> None:
        self._map: dict[str, np.ndarray] = {}

    def set(self, text: str, vec) -> None:
        self._map[text.strip()] = np.asarray(vec, dtype=float)

    def _vec(self, text: str) -> np.ndarray:
        text = text.strip()
        if text not in self._map:
            seed = sum(ord(c) for c in text) % (2**32)
            self._map[text] = np.random.RandomState(seed).randn(24)
        return self._map[text]

    def encode(self, texts: list[str]) -> np.ndarray:
        out = []
        for t in texts:
            v = self._vec(t)
            norm = np.linalg.norm(v)
            out.append(v / norm if norm else v)
        return np.array(out)


def _rec(
    rec_id: str,
    property_name: str,
    data_type: str = "int",
    data_type_desc: str = "整型",
    unit: str = "",
    writable: bool = False,
    project_id: str = "2084524131092914178",
    project_name: str = "Agent",
    device_id: str = "2084937599679848450",
    device_name: str = "空气罐",
    property_id: str = "2084940408848506881",
    handler: str = "panel_list",
    display_name: str = "状态面板",
) -> dict:
    return {
        "id": rec_id,
        "handler": handler,
        "displayName": display_name,
        "propertyName": property_name,
        "projectId": project_id,
        "projectName": project_name,
        "deviceId": device_id,
        "deviceName": device_name,
        "propertyId": property_id,
        "dataType": data_type,
        "dataTypeDesc": data_type_desc,
        "writable": writable,
        "unit": unit,
    }


def _records() -> list[dict]:
    return [
        _rec(
            "air_tank_temperature", "空气罐温度",
            data_type="int", data_type_desc="整型", unit="°C",
            property_id="2084940408848506881",
        ),
        _rec(
            "air_tank_pressure", "空气罐压力",
            data_type="double", data_type_desc="双精度", unit="MPa",
            property_id="2084940512418455554",
        ),
    ]


def _requests() -> list[dict]:
    return [
        {"row_number": 2, "displayName": "状态面板", "propertyName": "空气罐温度"},
        {"row_number": 3, "displayName": "状态面板", "propertyName": "空气罐压力"},
    ]


def _assignments() -> list[dict]:
    return [
        {"row_number": 2, "binding_id": "air_tank_temperature"},
        {"row_number": 3, "binding_id": "air_tank_pressure"},
    ]


class TestCsvEncoding:
    def test_utf8(self):
        assert detect_encoding(_csv([["状态面板", "空气罐温度"]])) == "utf-8"

    def test_utf8_bom(self):
        data = b"\xef\xbb\xbf" + _csv([["状态面板", "空气罐温度"]])
        assert detect_encoding(data) == "utf-8-sig"

    def test_gb18030(self):
        text = "displayName,propertyName\n状态面板,空气罐温度\n"
        assert detect_encoding(text.encode("gb18030")) == "gb18030"

    def test_reject_unknown_encoding(self):
        data = bytes(range(256)) * 4
        with pytest.raises(CsvEncodingError):
            detect_encoding(data)

    def test_too_large(self):
        data = _csv([["状态面板", "空气罐温度"]]) + b"0" * (MAX_CSV_BYTES + 1)
        with pytest.raises(CsvTooLargeError):
            preview_csv(data)

    def test_too_many_rows(self):
        rows = [["状态面板", "空气罐温度"]] * (MAX_CSV_ROWS + 1)
        with pytest.raises(CsvTooManyRowsError):
            preview_csv(_csv(rows))

    def test_empty_csv(self):
        with pytest.raises(CsvError):
            preview_csv(b"")

    def test_blank_only_csv(self):
        with pytest.raises(CsvError):
            preview_csv("\n\n\n".encode("utf-8"))


class TestCsvPreview:
    def test_valid(self):
        result = preview_csv(_csv([["状态面板", "空气罐温度"], ["状态面板", "空气罐压力"]]))
        assert result["encoding"] == "utf-8"
        assert result["total_rows"] == 2
        assert result["requests"] == [
            {"row_number": 2, "displayName": "状态面板", "propertyName": "空气罐温度"},
            {"row_number": 3, "displayName": "状态面板", "propertyName": "空气罐压力"},
        ]

    def test_header_extra_column_rejected(self):
        data = "displayName,propertyName,unit\n状态面板,空气罐温度,°C\n".encode("utf-8")
        with pytest.raises(CsvError) as exc:
            preview_csv(data)
        assert "表头必须精确" in str(exc.value)

    def test_header_reordered_rejected(self):
        data = "propertyName,displayName\n空气罐温度,状态面板\n".encode("utf-8")
        with pytest.raises(CsvError):
            preview_csv(data)

    def test_header_missing_column_rejected(self):
        data = "displayName\n状态面板\n".encode("utf-8")
        with pytest.raises(CsvError):
            preview_csv(data)

    def test_bad_row_width_rejected(self):
        data = "displayName,propertyName\n状态面板,空气罐温度,extra\n".encode("utf-8")
        with pytest.raises(CsvError) as exc:
            preview_csv(data)
        assert "必须恰好 2 列" in str(exc.value)

    def test_empty_value_rejected(self):
        data = "displayName,propertyName\n状态面板,\n".encode("utf-8")
        with pytest.raises(CsvError) as exc:
            preview_csv(data)
        assert "均不能为空" in str(exc.value)

    def test_duplicate_row_rejected(self):
        data = "displayName,propertyName\n状态面板,空气罐温度\n状态面板,空气罐温度\n".encode("utf-8")
        with pytest.raises(CsvError) as exc:
            preview_csv(data)
        assert "重复的 displayName+propertyName" in str(exc.value)

    def test_values_trimmed(self):
        data = "displayName,propertyName\n  状态面板  ,  空气罐温度  \n".encode("utf-8")
        result = preview_csv(data)
        assert result["requests"][0]["displayName"] == "状态面板"
        assert result["requests"][0]["propertyName"] == "空气罐温度"

    def test_blank_lines_ignored_keep_physical_rows(self):
        data = "displayName,propertyName\n\n状态面板,空气罐温度\n\n\n状态面板,空气罐压力\n".encode("utf-8")
        result = preview_csv(data)
        assert [r["row_number"] for r in result["requests"]] == [3, 6]

    def test_quoted_fields(self):
        data = "displayName,propertyName\n\"状态,面板\",\"温度,值\"\n".encode("utf-8")
        result = preview_csv(data)
        assert result["requests"][0]["displayName"] == "状态,面板"
        assert result["requests"][0]["propertyName"] == "温度,值"


class TestBindingRegistry:
    def _line(self, **overrides) -> str:
        rec = {
            "id": "a",
            "handler": "panel_list",
            "displayName": "状态面板",
            "propertyName": "空气罐温度",
            "projectId": "1",
            "projectName": "Agent",
            "deviceId": "2",
            "deviceName": "空气罐",
            "propertyId": "3",
            "dataType": "int",
            "dataTypeDesc": "整型",
            "writable": False,
        }
        rec.update(overrides)
        return json.dumps(rec, ensure_ascii=False)

    def test_load_valid(self, tmp_path: Path):
        p = tmp_path / "binding.jsonl"
        p.write_text(self._line() + "\n" + self._line(id="b", propertyName="空气罐压力", propertyId="4", dataType="double", dataTypeDesc="双精度") + "\n", encoding="utf-8")
        reg = load_binding_registry(p)
        assert [r["id"] for r in reg] == ["a", "b"]
        assert reg[0]["unit"] == ""
        assert reg[0]["handler"] == "panel_list"

    def test_unit_present(self, tmp_path: Path):
        p = tmp_path / "binding.jsonl"
        p.write_text(self._line(unit="°C") + "\n", encoding="utf-8")
        reg = load_binding_registry(p)
        assert reg[0]["unit"] == "°C"

    def test_missing_field(self, tmp_path: Path):
        p = tmp_path / "binding.jsonl"
        rec = json.loads(self._line())
        del rec["writable"]
        p.write_text(json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8")
        with pytest.raises(BindingConfigError) as exc:
            load_binding_registry(p)
        assert any("缺少字段" in e for e in exc.value.errors)

    def test_non_digit_id(self, tmp_path: Path):
        p = tmp_path / "binding.jsonl"
        p.write_text(self._line(propertyId="abc") + "\n", encoding="utf-8")
        with pytest.raises(BindingConfigError) as exc:
            load_binding_registry(p)
        assert any("必须为数字字符串" in e for e in exc.value.errors)

    def test_illegal_datatype(self, tmp_path: Path):
        p = tmp_path / "binding.jsonl"
        p.write_text(self._line(dataType="int16") + "\n", encoding="utf-8")
        with pytest.raises(BindingConfigError) as exc:
            load_binding_registry(p)
        assert any("dataType 非法" in e for e in exc.value.errors)

    def test_non_bool_writable(self, tmp_path: Path):
        p = tmp_path / "binding.jsonl"
        p.write_text(self._line(writable="false") + "\n", encoding="utf-8")
        with pytest.raises(BindingConfigError) as exc:
            load_binding_registry(p)
        assert any("writable 必须为布尔值" in e for e in exc.value.errors)

    def test_empty_string_field(self, tmp_path: Path):
        p = tmp_path / "binding.jsonl"
        p.write_text(self._line(displayName="") + "\n", encoding="utf-8")
        with pytest.raises(BindingConfigError) as exc:
            load_binding_registry(p)
        assert any("非空字符串" in e for e in exc.value.errors)

    def test_unit_non_string(self, tmp_path: Path):
        p = tmp_path / "binding.jsonl"
        p.write_text(self._line(unit=5) + "\n", encoding="utf-8")
        with pytest.raises(BindingConfigError) as exc:
            load_binding_registry(p)
        assert any("unit 必须为字符串" in e for e in exc.value.errors)

    def test_duplicate_id(self, tmp_path: Path):
        p = tmp_path / "binding.jsonl"
        p.write_text(self._line() + "\n" + self._line(propertyName="空气罐压力", propertyId="4") + "\n", encoding="utf-8")
        with pytest.raises(BindingConfigError) as exc:
            load_binding_registry(p)
        assert any("id 重复" in e for e in exc.value.errors)

    def test_duplicate_physical_source(self, tmp_path: Path):
        p = tmp_path / "binding.jsonl"
        p.write_text(self._line() + "\n" + self._line(id="b") + "\n", encoding="utf-8")
        with pytest.raises(BindingConfigError) as exc:
            load_binding_registry(p)
        assert any("重复物理源" in e for e in exc.value.errors)

    def test_json_syntax_error(self, tmp_path: Path):
        p = tmp_path / "binding.jsonl"
        p.write_text('{"id": "a", broken\n', encoding="utf-8")
        with pytest.raises(BindingConfigError) as exc:
            load_binding_registry(p)
        assert any("JSON 解析失败" in e for e in exc.value.errors)

    def test_non_object_line(self, tmp_path: Path):
        p = tmp_path / "binding.jsonl"
        p.write_text("[1,2,3]\n", encoding="utf-8")
        with pytest.raises(BindingConfigError) as exc:
            load_binding_registry(p)
        assert any("不是 JSON 对象" in e for e in exc.value.errors)


class TestPanelListHandler:
    def test_matches(self):
        handler = PanelListHandler()
        assert handler.matches("状态面板") is True
        assert handler.matches("状态面板2") is True
        assert handler.matches("状态面板10") is True
        assert handler.matches("状态面板0") is False
        assert handler.matches("面板") is False
        assert handler.matches("阀门") is False

    def test_canonicalize(self):
        assert PanelListHandler().canonicalize("状态面板2") == "状态面板"

    def test_validate_target(self):
        handler = PanelListHandler()
        assert handler.validate_target({"c": "ht.Node", "a": {}}) == []
        assert handler.validate_target({"c": "ht.Shape"}) != []

    def test_read_existing(self):
        handler = PanelListHandler()
        assert handler.read_existing({"a": {"panel.list": [1, 2]}}) == [1, 2]
        assert handler.read_existing({"a": {}}) is None

    def test_render_matches_item_builder(self):
        rec = _records()[0]
        rendered = PanelListHandler().render([rec])
        assert rendered == [_panel_list_item(rec)]


class TestPanelListItem:
    def test_full_shape(self):
        item = _panel_list_item(_records()[0])
        assert item == {
            "label": "空气罐温度",
            "bind": {
                "type": "designer",
                "path": "2084524131092914178#2084937599679848450#2084940408848506881",
                "key": "2084937599679848450#2084940408848506881",
                "label": "Agent . 空气罐 . 空气罐温度 (°C)",
                "proj": {"id": "2084524131092914178", "name": "Agent"},
                "dev": {"id": "2084937599679848450", "name": "空气罐"},
                "param": {
                    "id": "2084940408848506881",
                    "name": "空气罐温度",
                    "unit": "°C",
                    "writable": False,
                    "dataType": "int",
                    "dataTypeDesc": "整型",
                },
            },
        }

    def test_no_unit_no_parens(self):
        rec = _records()[1]
        rec["unit"] = ""
        item = _panel_list_item(rec)
        assert item["bind"]["label"] == "Agent . 空气罐 . 空气罐压力"
        assert "()" not in item["bind"]["label"]

    def test_pressure_double_preserved(self):
        item = _panel_list_item(_records()[1])
        assert item["bind"]["param"]["dataType"] == "double"
        assert item["bind"]["param"]["dataTypeDesc"] == "双精度"


class TestBindingAgentRegistry:
    def test_unknown_handler_blocks_construction(self):
        with pytest.raises(BindingConfigError) as exc:
            BindingAgent(records=[_rec("x", "温度", handler="bogus")], similarity=FakeSimilarity())
        assert any("handler 未注册" in e for e in exc.value.errors)

    def test_registry_records_exposed(self):
        agent = BindingAgent(records=_records(), similarity=FakeSimilarity())
        assert [r["id"] for r in agent.registry] == ["air_tank_temperature", "air_tank_pressure"]


class TestConfidence:
    def test_confidence_for(self):
        agent = BindingAgent(records=_records(), similarity=FakeSimilarity())
        assert agent._confidence_for(1.0, 0.10) == "high"
        assert agent._confidence_for(0.90, 0.05) == "medium"
        assert agent._confidence_for(0.70, 0.06) == "medium"
        assert agent._confidence_for(0.70, 0.04) == "low"
        assert agent._confidence_for(0.60, 0.50) == "low"
        assert agent._confidence_for(0.50, 0.00) == "none"


class TestMatch:
    def _agent(self, records=None):
        return BindingAgent(records=records if records is not None else _records(), similarity=FakeSimilarity())

    def test_unique_exact_preselects_high(self):
        agent = self._agent()
        result = agent.match(_panel_canvas("状态面板"), [{"row_number": 2, "displayName": "状态面板", "propertyName": "空气罐温度"}])
        assert result["blocked"] is False
        assert result["errors"] == []
        item = result["items"][0]
        assert len(item["candidates"]) == 1
        assert item["candidates"][0]["binding_id"] == "air_tank_temperature"
        assert item["candidates"][0]["score"] == 1.0
        assert item["suggested_binding_id"] == "air_tank_temperature"
        assert item["confidence"] == "high"
        assert item["lead"] == 1.0
        assert item["target_node_i"] == 0
        assert result["targets"][0]["displayName"] == "状态面板"
        assert result["targets"][0]["handler"] == "panel_list"

    def test_multi_exact_no_preselect(self):
        records = [
            _rec("air_tank_temperature", "空气罐温度", device_id="d1", property_id="p1"),
            _rec("air_tank_temperature_b", "空气罐温度", device_id="d2", property_id="p2"),
        ]
        agent = self._agent(records)
        result = agent.match(_panel_canvas("状态面板"), [{"row_number": 2, "displayName": "状态面板", "propertyName": "空气罐温度"}])
        item = result["items"][0]
        assert len(item["candidates"]) == 2
        assert [c["score"] for c in item["candidates"]] == [1.0, 1.0]
        assert item["suggested_binding_id"] is None

    def test_semantic_scores_lead_confidence(self):
        sim = FakeSimilarity()
        sim.set("空气罐温度", [1.0, 0.0])
        sim.set("空气罐压力", [0.0, 1.0])
        sim.set("气罐温度", [0.8, 0.6])
        agent = BindingAgent(records=_records(), similarity=sim)
        result = agent.match(_panel_canvas("状态面板"), [{"row_number": 2, "displayName": "状态面板", "propertyName": "气罐温度"}])
        item = result["items"][0]
        assert [c["binding_id"] for c in item["candidates"]] == ["air_tank_temperature", "air_tank_pressure"]
        assert item["candidates"][0]["score"] == 0.8
        assert item["candidates"][1]["score"] == 0.6
        assert item["lead"] == 0.2
        assert item["confidence"] == "medium"
        assert item["suggested_binding_id"] == "air_tank_temperature"
        assert "相似度" in item["candidates"][0]["evidence"][0]

    def test_below_threshold_no_candidate(self):
        sim = FakeSimilarity()
        sim.set("唯一属性", [1.0, 0.0])
        sim.set("完全无关", [0.0, 1.0])
        agent = BindingAgent(records=[_rec("only", "唯一属性")], similarity=sim)
        result = agent.match(_panel_canvas("状态面板"), [{"row_number": 2, "displayName": "状态面板", "propertyName": "完全无关"}])
        assert result["blocked"] is True
        assert result["items"][0]["candidates"] == []
        assert any("未找到匹配属性" in e for e in result["errors"])

    def test_single_semantic_candidate_lead_equals_score(self):
        sim = FakeSimilarity()
        sim.set("唯一属性", [1.0, 0.0])
        sim.set("接近属性", [0.8, 0.6])
        agent = BindingAgent(records=[_rec("only", "唯一属性")], similarity=sim)
        result = agent.match(_panel_canvas("状态面板"), [{"row_number": 2, "displayName": "状态面板", "propertyName": "接近属性"}])
        item = result["items"][0]
        assert item["candidates"][0]["score"] == 0.8
        assert item["lead"] == 0.8
        assert item["confidence"] == "medium"

    def test_top5_cap(self):
        records = []
        sim = FakeSimilarity()
        sim.set("查询", [1.0, 0.0])
        for i in range(10):
            name = f"属性{i}"
            c = 0.95 - 0.1 * i
            sim.set(name, [c, np.sqrt(1 - c * c)])
            records.append(_rec(f"rec{i}", name))
        agent = BindingAgent(records=records, similarity=sim)
        result = agent.match(_panel_canvas("状态面板"), [{"row_number": 2, "displayName": "状态面板", "propertyName": "查询"}])
        item = result["items"][0]
        assert len(item["candidates"]) == 5
        assert [c["binding_id"] for c in item["candidates"]] == [f"rec{i}" for i in range(5)]
        assert item["candidates"][-1]["score"] == 0.55

    def test_stable_sort_by_id_on_equal_score(self):
        records = [
            _rec("zrec", "属性Z"),
            _rec("arec", "属性A"),
        ]
        sim = FakeSimilarity()
        sim.set("查询", [1.0, 0.0])
        sim.set("属性Z", [0.7, np.sqrt(1 - 0.49)])
        sim.set("属性A", [0.7, np.sqrt(1 - 0.49)])
        agent = BindingAgent(records=records, similarity=sim)
        result = agent.match(_panel_canvas("状态面板"), [{"row_number": 2, "displayName": "状态面板", "propertyName": "查询"}])
        item = result["items"][0]
        assert item["candidates"][0]["binding_id"] == "arec"
        assert item["candidates"][1]["binding_id"] == "zrec"

    def test_numbered_panel_uses_canonical_catalog(self):
        agent = self._agent()
        result = agent.match(_panel_canvas("状态面板2"), [{"row_number": 2, "displayName": "状态面板2", "propertyName": "空气罐温度"}])
        assert result["blocked"] is False
        item = result["items"][0]
        assert item["target_node_i"] == 0
        assert item["candidates"][0]["binding_id"] == "air_tank_temperature"
        assert result["targets"][0]["displayName"] == "状态面板2"

    def test_no_broadcast_to_numbered_panels(self):
        agent = self._agent()
        canvas = _panel_canvas("状态面板", "状态面板2")
        r1 = agent.match(canvas, [{"row_number": 2, "displayName": "状态面板", "propertyName": "空气罐温度"}])
        assert [t["node_i"] for t in r1["targets"]] == [0]
        r2 = agent.match(canvas, [{"row_number": 2, "displayName": "状态面板2", "propertyName": "空气罐温度"}])
        assert [t["node_i"] for t in r2["targets"]] == [1]

    def test_duplicate_name_blocks(self):
        agent = self._agent()
        result = agent.match(_panel_canvas("状态面板", "状态面板"), [{"row_number": 2, "displayName": "状态面板", "propertyName": "空气罐温度"}])
        assert result["blocked"] is True
        assert any("多个同名节点" in e for e in result["errors"])

    def test_missing_target_blocks(self):
        agent = self._agent()
        result = agent.match(_panel_canvas("其他控件"), [{"row_number": 2, "displayName": "状态面板", "propertyName": "空气罐温度"}])
        assert result["blocked"] is True
        assert any("未找到目标控件" in e for e in result["errors"])

    def test_unsupported_control_blocks(self):
        agent = self._agent()
        result = agent.match(_panel_canvas("阀门"), [{"row_number": 2, "displayName": "阀门", "propertyName": "空气罐温度"}])
        assert result["blocked"] is True
        assert any("不支持的控件" in e for e in result["errors"])

    def test_wrong_node_type_not_located_as_target(self):
        agent = self._agent()
        canvas = _panel_canvas("状态面板")
        canvas["d"][0]["c"] = "ht.Shape"
        result = agent.match(canvas, [{"row_number": 2, "displayName": "状态面板", "propertyName": "空气罐温度"}])
        assert result["blocked"] is True
        assert any("未找到目标控件" in e for e in result["errors"])

    def test_all_requested_fields_preserved(self):
        agent = self._agent()
        result = agent.match(_panel_canvas("状态面板"), _requests())
        assert len(result["items"]) == 2
        assert result["items"][0]["row_number"] == 2
        assert result["items"][0]["requested_displayName"] == "状态面板"
        assert result["items"][0]["requested_propertyName"] == "空气罐温度"

    def test_mixed_valid_invalid_not_blocked(self):
        agent = self._agent()
        requests = [
            {"row_number": 2, "displayName": "状态面板", "propertyName": "空气罐温度"},
            {"row_number": 3, "displayName": "状态面板", "propertyName": "不存在的属性"},
        ]
        result = agent.match(_panel_canvas("状态面板"), requests)
        assert result["blocked"] is False
        assert result["items"][0]["candidates"]
        assert any("未找到匹配属性" in e for e in result["errors"])

    def test_all_rows_unavailable_blocked(self):
        agent = self._agent()
        requests = [
            {"row_number": 2, "displayName": "状态面板", "propertyName": "不存在的属性"},
            {"row_number": 3, "displayName": "阀门", "propertyName": "空气罐压力"},
        ]
        result = agent.match(_panel_canvas("状态面板"), requests)
        assert result["blocked"] is True
        assert result["items"][0]["candidates"] == []
        assert result["items"][1]["candidates"] == []


class TestBuild:
    def _agent(self, records=None):
        return BindingAgent(records=records if records is not None else _records(), similarity=FakeSimilarity())

    def test_build_ok_panel_list_exact_structure(self):
        agent = self._agent()
        result = agent.build(_panel_canvas("状态面板"), _requests(), _assignments())
        assert result["errors"] == []
        assert result["warnings"] == []
        assert result["applied_count"] == 2
        assert result["skipped_count"] == 0
        bound = result["bound_json"]
        assert bound is not None
        panel_list = bound["d"][0]["a"]["panel.list"]
        assert panel_list[0] == {
            "label": "空气罐温度",
            "bind": {
                "type": "designer",
                "path": "2084524131092914178#2084937599679848450#2084940408848506881",
                "key": "2084937599679848450#2084940408848506881",
                "label": "Agent . 空气罐 . 空气罐温度 (°C)",
                "proj": {"id": "2084524131092914178", "name": "Agent"},
                "dev": {"id": "2084937599679848450", "name": "空气罐"},
                "param": {
                    "id": "2084940408848506881",
                    "name": "空气罐温度",
                    "unit": "°C",
                    "writable": False,
                    "dataType": "int",
                    "dataTypeDesc": "整型",
                },
            },
        }
        assert panel_list[1]["bind"]["param"]["dataType"] == "double"
        assert panel_list[1]["bind"]["param"]["dataTypeDesc"] == "双精度"
        assert panel_list[1]["bind"]["param"]["unit"] == "MPa"

    def test_full_old_list_replacement(self):
        agent = self._agent()
        canvas = _panel_canvas("状态面板")
        canvas["d"][0]["a"]["panel.list"] = [{"old": True}]
        result = agent.build(canvas, _requests(), _assignments())
        bound_list = result["bound_json"]["d"][0]["a"]["panel.list"]
        assert len(bound_list) == 2
        assert all("old" not in item for item in bound_list)

    def test_original_canvas_unchanged(self):
        agent = self._agent()
        canvas = _panel_canvas("状态面板")
        agent.build(canvas, _requests(), _assignments())
        assert "panel.list" not in canvas["d"][0]["a"]

    def test_non_target_nodes_unchanged(self):
        agent = self._agent()
        canvas = _panel_canvas("其他控件", "状态面板")
        result = agent.build(canvas, _requests(), _assignments())
        assert result["bound_json"]["d"][0] == canvas["d"][0]
        assert "panel.list" not in result["bound_json"]["d"][0]["a"]
        assert result["bound_json"]["d"][0]["p"]["displayName"] == "其他控件"

    def test_layout_metadata_preserved(self):
        agent = self._agent()
        canvas = _panel_canvas("状态面板")
        canvas["d"][0]["a"]["layout.group"] = "G"
        canvas["d"][0]["a"]["layout.materialName"] = "M"
        result = agent.build(canvas, _requests(), _assignments())
        a = result["bound_json"]["d"][0]["a"]
        assert a["layout.group"] == "G"
        assert a["layout.materialName"] == "M"
        assert a["panel.list"]

    def test_csv_row_order_in_panel_list(self):
        agent = self._agent()
        assignments = list(reversed(_assignments()))
        result = agent.build(_panel_canvas("状态面板"), _requests(), assignments)
        panel_list = result["bound_json"]["d"][0]["a"]["panel.list"]
        assert [p["label"] for p in panel_list] == ["空气罐温度", "空气罐压力"]

    def test_missing_assignment_blocks(self):
        agent = self._agent()
        result = agent.build(_panel_canvas("状态面板"), _requests(), [])
        assert result["bound_json"] is None
        assert result["errors"] == ["至少确认 1 条绑定"]
        assert result["applied_count"] == 0
        assert result["skipped_count"] == 2

    def test_duplicate_assignment_same_row_blocks(self):
        agent = self._agent()
        assignments = [
            {"row_number": 2, "binding_id": "air_tank_temperature"},
            {"row_number": 2, "binding_id": "air_tank_temperature"},
        ]
        result = agent.build(_panel_canvas("状态面板"), _requests(), assignments)
        assert result["bound_json"] is None
        assert any("同一行存在多个 assignment" in e for e in result["errors"])

    def test_assignment_unknown_row_blocks(self):
        agent = self._agent()
        assignments = [{"row_number": 99, "binding_id": "air_tank_temperature"}]
        result = agent.build(_panel_canvas("状态面板"), _requests(), assignments)
        assert result["bound_json"] is None
        assert any("assignment 对应的请求不存在" in e for e in result["errors"])

    def test_forged_binding_id_blocks(self):
        agent = self._agent()
        assignments = _assignments()
        assignments[0]["binding_id"] = "bogus"
        result = agent.build(_panel_canvas("状态面板"), _requests(), assignments)
        assert result["bound_json"] is None
        assert any("不在允许的候选集合中" in e for e in result["errors"])
        assert any("不存在于注册表" in e for e in result["errors"])

    def test_binding_id_in_registry_but_not_candidate_blocks(self):
        records = _records() + [_rec("water_level", "水位", device_id="d9", property_id="p9", display_name="阀门")]
        agent = self._agent(records)
        assignments = [{"row_number": 2, "binding_id": "water_level"}]
        result = agent.build(_panel_canvas("状态面板"), _requests()[:1], assignments)
        assert result["bound_json"] is None
        assert any("不在允许的候选集合中" in e for e in result["errors"])
        assert not any("不存在于注册表" in e for e in result["errors"])

    def test_same_target_dup_source_blocks(self):
        records = [
            _rec("air_tank_temperature", "空气罐温度", device_id="d1", property_id="p1"),
            _rec("air_tank_temperature_b", "空气罐温度", device_id="d2", property_id="p2"),
        ]
        agent = self._agent(records)
        requests = [
            {"row_number": 2, "displayName": "状态面板", "propertyName": "空气罐温度"},
            {"row_number": 3, "displayName": "状态面板", "propertyName": "空气罐温度"},
        ]
        assignments = [
            {"row_number": 2, "binding_id": "air_tank_temperature"},
            {"row_number": 3, "binding_id": "air_tank_temperature"},
        ]
        result = agent.build(_panel_canvas("状态面板"), requests, assignments)
        assert result["bound_json"] is None
        assert any("重复选择" in e for e in result["errors"])

    def test_cross_target_reuse_allowed(self):
        agent = self._agent()
        canvas = _panel_canvas("状态面板", "状态面板2")
        requests = [
            {"row_number": 2, "displayName": "状态面板", "propertyName": "空气罐温度"},
            {"row_number": 3, "displayName": "状态面板2", "propertyName": "空气罐温度"},
        ]
        assignments = [
            {"row_number": 2, "binding_id": "air_tank_temperature"},
            {"row_number": 3, "binding_id": "air_tank_temperature"},
        ]
        result = agent.build(canvas, requests, assignments)
        assert result["errors"] == []
        assert result["bound_json"] is not None
        assert result["bound_json"]["d"][0]["a"]["panel.list"][0]["label"] == "空气罐温度"
        assert result["bound_json"]["d"][1]["a"]["panel.list"][0]["label"] == "空气罐温度"

    def test_canvas_schema_failure_blocks(self):
        agent = self._agent()
        result = agent.build(
            _panel_canvas("状态面板"), _requests(), _assignments(),
            canvas_validator=lambda jd: ["canvas bad"],
        )
        assert result["bound_json"] is None
        assert any("Canvas Schema: canvas bad" in e for e in result["errors"])

    def test_binding_schema_failure_blocks(self):
        agent = self._agent()
        result = agent.build(
            _panel_canvas("状态面板"), _requests(), _assignments(),
            binding_validator=lambda a: ["binding bad"],
        )
        assert result["bound_json"] is None
        assert any("Binding Schema (状态面板): binding bad" in e for e in result["errors"])

    def test_previews_shape(self):
        agent = self._agent()
        canvas = _panel_canvas("状态面板")
        canvas["d"][0]["a"]["panel.list"] = [{"old": True}]
        result = agent.build(canvas, _requests(), _assignments())
        p = result["previews"][0]
        assert set(p.keys()) == {"node_i", "displayName", "handler", "before", "after"}
        assert p["node_i"] == 0
        assert p["displayName"] == "状态面板"
        assert p["handler"] == "panel_list"
        assert p["before"] == [{"old": True}]
        assert len(p["after"]) == 2

    def test_mixed_valid_invalid_atomic(self):
        agent = self._agent()
        assignments = [{"row_number": 2, "binding_id": "bogus"}]
        result = agent.build(_panel_canvas("状态面板"), _requests(), assignments)
        assert result["bound_json"] is None
        assert result["applied_count"] == 0
        assert result["skipped_count"] == 1
        assert any("不在允许的候选集合中" in e for e in result["errors"])
        assert not any("缺少 assignment" in e for e in result["errors"])


class TestPartialBuild:
    def _agent(self, records=None):
        return BindingAgent(records=records if records is not None else _records(), similarity=FakeSimilarity())

    def test_single_row_partial_generates_one_item(self):
        agent = self._agent()
        assignments = [{"row_number": 2, "binding_id": "air_tank_temperature"}]
        result = agent.build(_panel_canvas("状态面板"), _requests(), assignments)
        assert result["errors"] == []
        assert result["bound_json"] is not None
        panel_list = result["bound_json"]["d"][0]["a"]["panel.list"]
        assert len(panel_list) == 1
        assert panel_list[0]["label"] == "空气罐温度"
        assert result["applied_count"] == 1
        assert result["skipped_count"] == 1
        assert result["warnings"] == ["已跳过 1 条未确认的绑定行"]
        assert len(result["previews"]) == 1
        assert result["previews"][0]["node_i"] == 0
        assert len(result["previews"][0]["after"]) == 1

    def test_unsubmitted_row_no_candidate_does_not_block(self):
        agent = self._agent()
        requests = [
            {"row_number": 2, "displayName": "状态面板", "propertyName": "空气罐温度"},
            {"row_number": 3, "displayName": "状态面板", "propertyName": "不存在的属性"},
        ]
        assignments = [{"row_number": 2, "binding_id": "air_tank_temperature"}]
        result = agent.build(_panel_canvas("状态面板"), requests, assignments)
        assert result["errors"] == []
        assert result["bound_json"] is not None
        assert len(result["bound_json"]["d"][0]["a"]["panel.list"]) == 1
        assert result["applied_count"] == 1
        assert result["skipped_count"] == 1

    def test_unsubmitted_row_missing_target_does_not_block(self):
        agent = self._agent()
        requests = [
            {"row_number": 2, "displayName": "状态面板", "propertyName": "空气罐温度"},
            {"row_number": 3, "displayName": "状态面板2", "propertyName": "空气罐压力"},
        ]
        assignments = [{"row_number": 2, "binding_id": "air_tank_temperature"}]
        result = agent.build(_panel_canvas("状态面板"), requests, assignments)
        assert result["errors"] == []
        assert result["bound_json"] is not None
        assert result["applied_count"] == 1
        assert result["skipped_count"] == 1

    def test_unsubmitted_row_unsupported_control_does_not_block(self):
        agent = self._agent()
        requests = [
            {"row_number": 2, "displayName": "状态面板", "propertyName": "空气罐温度"},
            {"row_number": 3, "displayName": "阀门", "propertyName": "空气罐压力"},
        ]
        assignments = [{"row_number": 2, "binding_id": "air_tank_temperature"}]
        result = agent.build(_panel_canvas("状态面板"), requests, assignments)
        assert result["errors"] == []
        assert result["bound_json"] is not None
        assert result["applied_count"] == 1
        assert result["skipped_count"] == 1

    def test_multi_panel_partial_keeps_other_panel_untouched(self):
        agent = self._agent()
        canvas = _panel_canvas("状态面板", "状态面板2")
        canvas["d"][0]["a"]["panel.list"] = [{"old": "panel1"}]
        canvas["d"][1]["a"]["panel.list"] = [{"old": "panel2"}]
        requests = [
            {"row_number": 2, "displayName": "状态面板", "propertyName": "空气罐温度"},
            {"row_number": 3, "displayName": "状态面板2", "propertyName": "空气罐压力"},
        ]
        assignments = [{"row_number": 2, "binding_id": "air_tank_temperature"}]
        result = agent.build(canvas, requests, assignments)
        assert result["errors"] == []
        bound = result["bound_json"]
        assert bound is not None
        assert len(bound["d"][0]["a"]["panel.list"]) == 1
        assert bound["d"][0]["a"]["panel.list"][0]["label"] == "空气罐温度"
        assert bound["d"][1]["a"]["panel.list"] == [{"old": "panel2"}]
        assert len(result["previews"]) == 1
        assert result["previews"][0]["node_i"] == 0
        assert result["applied_count"] == 1
        assert result["skipped_count"] == 1

    def test_partial_build_replaces_old_list_entirely(self):
        agent = self._agent()
        canvas = _panel_canvas("状态面板")
        canvas["d"][0]["a"]["panel.list"] = [{"old": 1}, {"old": 2}]
        assignments = [{"row_number": 3, "binding_id": "air_tank_pressure"}]
        result = agent.build(canvas, _requests(), assignments)
        assert result["errors"] == []
        panel_list = result["bound_json"]["d"][0]["a"]["panel.list"]
        assert len(panel_list) == 1
        assert panel_list[0]["label"] == "空气罐压力"
        assert all("old" not in it for it in panel_list)
        assert result["applied_count"] == 1

    def test_submitted_row_invalid_still_atomic(self):
        agent = self._agent()
        canvas = _panel_canvas("状态面板")
        canvas["d"][0]["a"]["panel.list"] = [{"old": 1}]
        assignments = [
            {"row_number": 2, "binding_id": "air_tank_temperature"},
            {"row_number": 3, "binding_id": "bogus"},
        ]
        result = agent.build(canvas, _requests(), assignments)
        assert result["bound_json"] is None
        assert result["applied_count"] == 0
        assert result["skipped_count"] == 0
        assert any("不在允许的候选集合中" in e for e in result["errors"])
        assert any("不存在于注册表" in e for e in result["errors"])


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
    def test_top1_on_fixed_truth_set(self):
        fixture_dir = Path(__file__).resolve().parent.joinpath("fixtures", "binding")
        requests = preview_csv((fixture_dir / "properties.csv").read_bytes())["requests"]
        canvas = _panel_canvas("状态面板")
        agent = BindingAgent(registry_path=Path(__file__).resolve().parent.parent / "data" / "binding.jsonl")
        result = agent.match(canvas, requests)
        assert result["blocked"] is False, result["errors"]
        ground_truth = json.loads((fixture_dir / "ground_truth.json").read_text(encoding="utf-8"))
        expected = {m["row_number"]: m["binding_id"] for m in ground_truth["mappings"]}
        assert len(result["items"]) == 20
        correct = 0
        for item in result["items"]:
            assert item["candidates"][0]["score"] >= 0.55
            assert item["suggested_binding_id"] is not None
            if item["suggested_binding_id"] == expected[item["row_number"]]:
                correct += 1
        assert correct / len(result["items"]) >= 0.75
