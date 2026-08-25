from __future__ import annotations

import io
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi.testclient import TestClient

import app.deps as deps_module
from app.main import app
from model.binding_agent import BindingAgent

from test_binding import FakeSimilarity, _panel_canvas, _records, _requests

deps_module._binding_agent = BindingAgent(records=_records(), similarity=FakeSimilarity())

client = TestClient(app, raise_server_exceptions=False)

CSV_HEADER = "displayName,propertyName"


def _csv_file(content: str = "") -> tuple[str, io.BytesIO, str]:
    if not content:
        content = CSV_HEADER + "\n状态面板,空气罐温度\n状态面板,空气罐压力\n"
    return ("props.csv", io.BytesIO(content.encode("utf-8")), "text/csv")


class TestBindingRoutes:
    def test_preview_ok(self):
        r = client.post("/api/binding/csv/preview", files={"file": _csv_file()})
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["encoding"] == "utf-8"
        assert data["total_rows"] == 2
        assert data["requests"] == [
            {"row_number": 2, "displayName": "状态面板", "propertyName": "空气罐温度"},
            {"row_number": 3, "displayName": "状态面板", "propertyName": "空气罐压力"},
        ]

    def test_preview_rejects_non_csv(self):
        r = client.post("/api/binding/csv/preview", files={"file": ("x.txt", io.BytesIO(b"a"), "text/plain")})
        assert r.status_code == 422

    def test_preview_rejects_bad_encoding(self):
        r = client.post("/api/binding/csv/preview", files={"file": ("x.csv", io.BytesIO(bytes(range(256)) * 4), "text/csv")})
        assert r.status_code == 422

    def test_preview_too_large(self):
        big = (CSV_HEADER + "\n" + ("状态面板,空气罐温度\n" * 60000)).encode("utf-8")
        r = client.post("/api/binding/csv/preview", files={"file": ("x.csv", io.BytesIO(big), "text/csv")})
        assert r.status_code == 413

    def test_preview_rejects_bad_header(self):
        content = "displayName,propertyName,unit\n状态面板,空气罐温度,°C\n"
        r = client.post("/api/binding/csv/preview", files={"file": _csv_file(content)})
        assert r.status_code == 422

    def test_preview_rejects_empty_value(self):
        content = "displayName,propertyName\n状态面板,\n"
        r = client.post("/api/binding/csv/preview", files={"file": _csv_file(content)})
        assert r.status_code == 422

    def test_normalize_route_absent(self):
        r = client.post("/api/binding/csv/normalize", files={"file": _csv_file()})
        assert r.status_code == 404

    def test_match_ok(self):
        preview = client.post("/api/binding/csv/preview", files={"file": _csv_file()}).json()["data"]
        r = client.post("/api/binding/match", json={"json_data": _panel_canvas("状态面板"), "requests": preview["requests"]})
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["blocked"] is False
        assert data["errors"] == []
        assert data["targets"][0]["displayName"] == "状态面板"
        assert data["targets"][0]["handler"] == "panel_list"
        assert len(data["items"]) == 2
        for item in data["items"]:
            assert item["candidates"]
            assert item["suggested_binding_id"] is not None

    def test_match_blocked_unsupported_control(self):
        requests = [{"row_number": 2, "displayName": "阀门", "propertyName": "空气罐温度"}]
        r = client.post("/api/binding/match", json={"json_data": _panel_canvas("阀门"), "requests": requests})
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["blocked"] is True
        assert any("不支持的控件" in e for e in data["errors"])

    def test_match_rejects_extra_fields(self):
        requests = [{"row_number": 2, "displayName": "状态面板", "propertyName": "空气罐温度", "foo": 1}]
        r = client.post("/api/binding/match", json={"json_data": _panel_canvas("状态面板"), "requests": requests})
        assert r.status_code == 422

    def test_build_ok(self):
        canvas = _panel_canvas("状态面板")
        requests = _requests()
        assignments = [
            {"row_number": 2, "binding_id": "air_tank_temperature"},
            {"row_number": 3, "binding_id": "air_tank_pressure"},
        ]
        r = client.post("/api/binding/build", json={"json_data": canvas, "requests": requests, "assignments": assignments})
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["errors"] == []
        assert data["warnings"] == []
        assert data["bound_json"] is not None
        panel_list = data["bound_json"]["d"][0]["a"]["panel.list"]
        assert len(panel_list) == 2
        assert panel_list[0]["bind"]["type"] == "designer"
        assert data["previews"][0]["displayName"] == "状态面板"
        assert data["previews"][0]["handler"] == "panel_list"

    def test_build_missing_assignment_blocks(self):
        canvas = _panel_canvas("状态面板")
        r = client.post("/api/binding/build", json={"json_data": canvas, "requests": _requests(), "assignments": []})
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["bound_json"] is None
        assert data["errors"] == ["至少确认 1 条绑定"]
        assert data["applied_count"] == 0
        assert data["skipped_count"] == 2

    def test_build_partial_ok(self):
        canvas = _panel_canvas("状态面板")
        requests = _requests()
        assignments = [{"row_number": 2, "binding_id": "air_tank_temperature"}]
        r = client.post("/api/binding/build", json={"json_data": canvas, "requests": requests, "assignments": assignments})
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["errors"] == []
        assert data["bound_json"] is not None
        assert len(data["bound_json"]["d"][0]["a"]["panel.list"]) == 1
        assert data["applied_count"] == 1
        assert data["skipped_count"] == 1
        assert len(data["warnings"]) == 1
        assert len(data["previews"]) == 1

    def test_build_forged_binding_id_blocks(self):
        canvas = _panel_canvas("状态面板")
        assignments = [{"row_number": 2, "binding_id": "bogus"}]
        r = client.post("/api/binding/build", json={"json_data": canvas, "requests": _requests(), "assignments": assignments})
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["bound_json"] is None
        assert any("不在允许的候选集合中" in e for e in data["errors"])

    def test_build_canvas_schema_failure(self):
        canvas = _panel_canvas("状态面板")
        del canvas["contentRect"]
        r = client.post("/api/binding/build", json={"json_data": canvas, "requests": _requests(), "assignments": [
            {"row_number": 2, "binding_id": "air_tank_temperature"},
            {"row_number": 3, "binding_id": "air_tank_pressure"},
        ]})
        assert r.status_code == 422

    def test_build_rejects_invalid_assignment_shape(self):
        canvas = _panel_canvas("状态面板")
        assignments = [{"row_number": 2}]
        r = client.post("/api/binding/build", json={"json_data": canvas, "requests": _requests(), "assignments": assignments})
        assert r.status_code == 422

    def test_old_preview_payload_rejected(self):
        content = "projectId,projectName,deviceId,deviceName,propertyId,propertyName,dataType,writable,unit\n1,Agent,2,空气罐,3,空气罐温度,int,只读,°C\n"
        r = client.post("/api/binding/csv/preview", files={"file": _csv_file(content)})
        assert r.status_code == 422
