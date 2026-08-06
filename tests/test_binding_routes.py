from __future__ import annotations

import io
import json
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)

BASIC_HEADER = "projectId,projectName,deviceId,deviceName,propertyId,propertyName,dataType,writable,unit"
MAPPING = json.dumps([
    {"field": f, "column": i}
    for i, f in enumerate(["projectId", "projectName", "deviceId", "deviceName", "propertyId", "propertyName", "dataType", "writable", "unit"])
])


def _csv_file(content: str = "") -> tuple[str, io.BytesIO, str]:
    if not content:
        content = (
            BASIC_HEADER
            + "\n2084524131092914178,Agent,2084937599679848450,空气罐,2084940408848506881,空气罐温度,integer,只读,°C\n"
            + "2084524131092914178,Agent,2084937599679848450,空气罐,2084940512418455554,空气罐压力,float,只读,MPa\n"
        )
    return ("props.csv", io.BytesIO(content.encode("utf-8")), "text/csv")


def _panel_canvas() -> dict:
    return {
        "v": "1",
        "p": {"layers": [], "autoAdjustIndex": True, "hierarchicalRendering": False},
        "a": {"width": 1920, "fitContent": True, "rectSelectable": True, "pannable": True, "zoomable": True, "height": 1080},
        "contentRect": {"x": 0, "y": 0, "width": 1920, "height": 1080},
        "d": [
            {"c": "ht.Node", "i": "n0", "p": {"displayName": "状态面板"}, "a": {"layout.node": 0}},
        ],
    }


class TestBindingRoutes:
    def test_preview_ok(self):
        r = client.post("/api/binding/csv/preview", files={"file": _csv_file()})
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["encoding"] == "utf-8"
        assert data["total_rows"] == 2
        assert len(data["rows"]) == 2
        assert data["mapping"]["suggestions"]

    def test_preview_rejects_non_csv(self):
        r = client.post("/api/binding/csv/preview", files={"file": ("x.txt", io.BytesIO(b"a"), "text/plain")})
        assert r.status_code == 422

    def test_preview_rejects_bad_encoding(self):
        r = client.post("/api/binding/csv/preview", files={"file": ("x.csv", io.BytesIO(bytes(range(256)) * 4), "text/csv")})
        assert r.status_code == 422

    def test_preview_too_large(self):
        big = ("a,b\n" + ("1,2\n" * 60000)).encode("utf-8")
        r = client.post("/api/binding/csv/preview", files={"file": ("x.csv", io.BytesIO(big), "text/csv")})
        assert r.status_code == 413

    def test_normalize_ok(self):
        r = client.post(
            "/api/binding/csv/normalize",
            files={"file": _csv_file()},
            data={"mapping": MAPPING},
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["blocked"] is False
        assert len(data["properties"]) == 2
        assert data["properties"][0]["dataType"] == "int"
        assert data["properties"][0]["writable"] is False

    def test_normalize_bad_mapping_json(self):
        r = client.post(
            "/api/binding/csv/normalize",
            files={"file": _csv_file()},
            data={"mapping": "not-json"},
        )
        assert r.status_code == 422

    def test_normalize_row_error(self):
        content = BASIC_HEADER + "\n1,Agent,2,空气罐,3,温度,hex,否,°C\n"
        r = client.post(
            "/api/binding/csv/normalize",
            files={"file": _csv_file(content)},
            data={"mapping": MAPPING},
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["properties"] == []
        assert any("第 2 行" in e and "dataType" in e for e in data["errors"])

    def test_match_ok(self):
        norm = client.post(
            "/api/binding/csv/normalize",
            files={"file": _csv_file()},
            data={"mapping": MAPPING},
        ).json()["data"]
        r = client.post("/api/binding/match", json={"json_data": _panel_canvas(), "properties": norm["properties"]})
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["panels"][0]["displayName"] == "状态面板"
        assert len(data["items"]) == 2
        for item in data["items"]:
            assert item["confirmed"] is False
            assert item["candidates"]

    def test_match_invalid_registry_not_tested_here(self):
        pass

    def test_build_ok(self):
        norm = client.post(
            "/api/binding/csv/normalize",
            files={"file": _csv_file()},
            data={"mapping": MAPPING},
        ).json()["data"]
        props = norm["properties"]
        canvas = _panel_canvas()
        match = client.post("/api/binding/match", json={"json_data": canvas, "properties": props}).json()["data"]
        assignments = [
            {
                "panel_node_i": item["panel_node_i"],
                "expectation_id": item["expectation_id"],
                "candidate": next(c for c in item["candidates"] if c["key"] == item["suggested"]),
            }
            for item in match["items"]
        ]
        r = client.post("/api/binding/build", json={"json_data": canvas, "properties": props, "assignments": assignments})
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["errors"] == []
        assert data["warnings"] == []
        assert data["bound_json"] is not None
        panel_list = data["bound_json"]["d"][0]["a"]["panel.list"]
        assert len(panel_list) == 2
        assert panel_list[0]["bind"]["type"] == "designer"

    def test_build_required_missing_blocks(self):
        norm = client.post(
            "/api/binding/csv/normalize",
            files={"file": _csv_file()},
            data={"mapping": MAPPING},
        ).json()["data"]
        props = norm["properties"]
        canvas = _panel_canvas()
        r = client.post("/api/binding/build", json={"json_data": canvas, "properties": props, "assignments": []})
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["bound_json"] is None
        assert any("必绑项" in e for e in data["errors"])

    def test_build_readonly_reuse_warns(self):
        norm = client.post(
            "/api/binding/csv/normalize",
            files={"file": _csv_file()},
            data={"mapping": MAPPING},
        ).json()["data"]
        props = norm["properties"]
        canvas = _panel_canvas()
        assignments = [
            {"panel_node_i": 0, "expectation_id": "air_tank_temperature", "candidate": props[0]},
            {"panel_node_i": 0, "expectation_id": "air_tank_pressure", "candidate": props[0]},
        ]
        r = client.post("/api/binding/build", json={"json_data": canvas, "properties": props, "assignments": assignments})
        assert r.status_code == 200
        data = r.json()["data"]
        assert any("只读属性" in w for w in data["warnings"])
