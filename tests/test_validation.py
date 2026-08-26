from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.deps as deps_module
from app.main import app
from app.services.validation_service import SchemaLoadError, ValidationService
from model.validate_agent import ValidateAgent

from tests.conftest import FakeAsyncClient, make_fake_completion

REPO = Path(__file__).resolve().parent.parent


def _canvas_binding_valid() -> dict:
    return {
        "v": "1",
        "p": {"layers": [{"name": "0", "visible": True, "selectable": True, "movable": True, "editable": True}], "autoAdjustIndex": True, "hierarchicalRendering": True},
        "a": {"width": 1920, "height": 1080, "fitContent": True, "rectSelectable": True, "pannable": True, "zoomable": True},
        "d": [
            {
                "c": "ht.Node",
                "a": {
                    "panel.list": [
                        {
                            "label": "空气罐温度",
                            "bind": {
                                "type": "designer",
                                "path": "1#2#3",
                                "key": "2#3",
                                "label": "p . d . n (u)",
                                "proj": {"id": "1", "name": "p"},
                                "dev": {"id": "2", "name": "d"},
                                "param": {"id": "3", "name": "n", "unit": "u", "writable": False, "dataType": "int", "dataTypeDesc": "整型"},
                            },
                        }
                    ]
                },
                "p": {"displayName": "状态面板", "width": 100, "height": 50, "position": {"x": 100, "y": 100}},
            }
        ],
        "contentRect": {"x": 0, "y": 0, "width": 1920, "height": 1080},
    }


class TestSchemaSelfCheck:
    def test_all_schemas_are_draft07_and_loadable(self):
        service = ValidationService.instance()
        assert len(service.rules_meta()) == 4

    def test_missing_schema_blocks_startup(self, tmp_path: Path, monkeypatch):
        from app.services import validation_service as module

        module._SCHEMA_SOURCES["control"] = str(tmp_path / "missing.json")
        module.ValidationService._instance = None
        with pytest.raises(SchemaLoadError):
            module.ValidationService()
        module._SCHEMA_SOURCES["control"] = module.settings.control_schema_path
        module.ValidationService._instance = None

    def test_invalid_schema_blocks_startup(self, tmp_path: Path, monkeypatch):
        from app.services import validation_service as module

        bad = tmp_path / "bad.json"
        bad.write_text("not json", encoding="utf-8")
        module._SCHEMA_SOURCES["control"] = str(bad)
        module.ValidationService._instance = None
        with pytest.raises(SchemaLoadError):
            module.ValidationService()
        module._SCHEMA_SOURCES["control"] = module.settings.control_schema_path
        module.ValidationService._instance = None


class TestValidSamples:
    def test_control_jsonl_full_passes(self):
        service = ValidationService.instance()
        errors_total = 0
        for line in (REPO / "data" / "control.jsonl").read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            errors, _ = service.validate("control", json.loads(line))
            errors_total += len(errors)
        assert errors_total == 0

    def test_data_canvas_passes(self):
        service = ValidationService.instance()
        canvas = json.loads((REPO / "data" / "canvas.json").read_text(encoding="utf-8"))
        errors, _ = service.validate("canvas", canvas)
        assert errors == []

    def test_layout_valid_passes(self):
        service = ValidationService.instance()
        data = {
            "layoutIntent": {
                "groups": [
                    {
                        "id": "g1",
                        "region": "center",
                        "unit": {"root": {"id": "r", "deviceType": "电动调节阀"}},
                        "count": 1,
                    }
                ]
            }
        }
        errors, _ = service.validate("layout", data)
        assert errors == []

    def test_binding_wrapper_passes(self):
        service = ValidationService.instance()
        data = {
            "panel.list": [
                {
                    "label": "空气罐温度",
                    "bind": {
                        "type": "designer",
                        "path": "1#2#3",
                        "key": "2#3",
                        "label": "p . d . n (u)",
                        "proj": {"id": "1", "name": "p"},
                        "dev": {"id": "2", "name": "d"},
                        "param": {"id": "3", "name": "n", "unit": "u", "writable": False, "dataType": "int", "dataTypeDesc": "整型"},
                    },
                }
            ]
        }
        errors, _ = service.validate("binding", data)
        assert errors == []

    def test_binding_full_canvas_passes(self):
        service = ValidationService.instance()
        errors, _ = service.validate("binding", _canvas_binding_valid())
        assert errors == []


class TestInvalidSamples:
    def test_forward_four_invalid_categories(self):
        service = ValidationService.instance()
        control_bad = {"displayName": "", "image": "unknown/valve.png", "width": -1, "height": "abc"}
        errors, _ = service.validate("control", control_bad)
        assert errors

        canvas_bad = {"v": 123, "p": None, "a": {"width": -100, "height": 0}, "d": "not array", "contentRect": {"x": 0, "y": 0}}
        errors, _ = service.validate("canvas", canvas_bad)
        assert errors

        layout_bad = {"layoutIntent": {"groups": []}}
        errors, _ = service.validate("layout", layout_bad)
        assert errors

        binding_bad = {
            "panel.list": [
                {
                    "label": "",
                    "bind": {
                        "type": "unknown",
                        "path": "abc#xyz",
                        "key": "",
                        "label": "",
                        "proj": {},
                        "dev": {},
                        "param": {"id": "", "name": "", "unit": "", "writable": "yes", "dataType": "int16", "dataTypeDesc": ""},
                    },
                }
            ]
        }
        errors, _ = service.validate("binding", binding_bad)
        assert errors

    def test_layout_duplicate_node_id_rejected(self):
        service = ValidationService.instance()
        data = {
            "layoutIntent": {
                "groups": [
                    {
                        "id": "g1",
                        "region": "center",
                        "unit": {"root": {"id": "r", "deviceType": "a"}, "attachments": [{"id": "r", "deviceType": "b", "relativeTo": "r", "side": "right"}]},
                        "count": 1,
                    }
                ]
            }
        }
        errors, _ = service.validate("layout", data)
        assert any("重复" in e.message for e in errors)

    def test_layout_unknown_field_rejected(self):
        service = ValidationService.instance()
        data = {"layoutIntent": {"groups": [], "extra": 1}}
        errors, _ = service.validate("layout", data)
        assert any("未知字段" in e.message for e in errors)


class TestSchemaErrorsAreJsonPointer:
    def test_control_path_is_pointer(self):
        service = ValidationService.instance()
        errors, _ = service.validate("control", {"displayName": "", "image": "x.png", "width": 0})
        paths = {e.path for e in errors}
        assert "/displayName" in paths
        assert "/image" in paths


class TestValidationRoute:
    def _client(self, agent: ValidateAgent):
        deps_module._validate_agent = agent
        return TestClient(app, raise_server_exceptions=False)

    def test_rules_endpoint(self):
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/api/validate/rules")
        assert r.status_code == 200
        categories = r.json()["data"]["categories"]
        assert {c["category"] for c in categories} == {"control", "canvas", "layout", "binding"}
        for c in categories:
            assert "derived_rules" in c
            assert "sample_valid" in c

    def test_deterministic_error_does_not_call_ai(self):
        fake = FakeAsyncClient()
        agent = ValidateAgent(client=fake)
        client = self._client(agent)
        r = client.post("/api/validate", json={"category": "control", "json_data": {"displayName": "", "image": "x.png"}})
        data = r.json()["data"]
        assert data["valid"] is False
        assert fake._call_count == 0
        assert data["errors"]
        for e in data["errors"]:
            assert e["source"] in ("schema", "semantic")

    def test_ai_findings_become_warning(self):
        canvas = json.loads((REPO / "data" / "canvas.json").read_text(encoding="utf-8"))
        fake = FakeAsyncClient([make_fake_completion(
            '{"valid": false, "errors": [], "warnings": [{"path": "/d", "message": "ai hint", "error_type": "ai"}]}'
        )])
        agent = ValidateAgent(client=fake)
        client = self._client(agent)
        r = client.post("/api/validate", json={"category": "canvas", "json_data": canvas})
        data = r.json()["data"]
        assert data["valid"] is True
        assert any(w["source"] == "ai" for w in data["warnings"])


class TestValidateAgentRegressions:
    @pytest.mark.asyncio
    async def test_no_model_config_produces_warning(self):
        agent = ValidateAgent(client=None, model="")
        result = await agent.validate("canvas", {"a": 1})
        assert any("未配置模型" in w["message"] for w in result["warnings"])

    @pytest.mark.asyncio
    async def test_large_input_skipped_with_warning(self):
        fake = FakeAsyncClient()
        agent = ValidateAgent(client=fake)
        big = {"pad": "x" * (66 * 1024)}
        result = await agent.validate("canvas", big)
        assert any("64 KiB" in w["message"] for w in result["warnings"])
        assert fake._call_count == 0

    @pytest.mark.asyncio
    async def test_invalid_ai_response_finds_warning(self):
        fake = FakeAsyncClient([make_fake_completion("not json at all {{")])
        agent = ValidateAgent(client=fake)
        result = await agent.validate("canvas", {"a": 1})
        assert any("解析失败" in w["message"] for w in result["warnings"])

    @pytest.mark.asyncio
    async def test_ai_error_becomes_warning(self):
        fake = FakeAsyncClient()
        fake.set_failure(0, Exception("boom"))
        agent = ValidateAgent(client=fake)
        result = await agent.validate("canvas", {"a": 1})
        assert any("boom" in w["message"] for w in result["warnings"])
