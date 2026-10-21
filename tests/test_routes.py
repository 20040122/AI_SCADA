from __future__ import annotations

import subprocess

import pytest
from fastapi.testclient import TestClient

import app.deps as deps_module
from app.main import app
from model.layout_agent import LayoutAgent
from model.refine_agent import RefineAgent
from model.validate_agent import ValidateAgent

deps_module._layout_agent = LayoutAgent(db=None)
deps_module._refine_agent = RefineAgent()
deps_module._validate_agent = ValidateAgent()

client = TestClient(app, raise_server_exceptions=False)


def test_layout_route_exists():
    resp = client.post("/api/canvas/layout", json={"query": "test", "title": "test", "canvas_width": 1920, "canvas_height": 1080})
    assert resp.status_code in (200, 422, 500, 502, 503, 504)


def test_refine_route_exists():
    resp = client.post("/api/canvas/refine", json={"instruction": "move left", "json_data": {"a": {}, "d": []}})
    assert resp.status_code in (200, 422, 500)


def test_refine_duplicate_selected_node_ids_rejected():
    resp = client.post(
        "/api/canvas/refine",
        json={
            "instruction": "add control",
            "json_data": {"a": {"width": 1920, "height": 1080}, "d": []},
            "selected_node_ids": [1, 1],
        },
    )
    assert resp.status_code == 422
    assert "unique" in resp.json()["detail"]


def test_validate_route_exists():
    resp = client.post("/api/validate", json={"category": "canvas", "json_data": {"v": "8.0.5"}})
    assert resp.status_code in (200, 422, 500)


def test_layout_image_route_uses_agent_i_without_text_generation(monkeypatch):
    from app.routers import canvas as canvas_module
    from model.layout_agent import LayoutAgent as AgentClass

    class FakeDB:
        def __init__(self):
            self.calls = 0

        async def list_query_results(self, query):
            self.calls += 1
            return [{"displayName": "泵"}]

    fake_db = FakeDB()

    class FakeResult:
        json_data = {"v": "8.0.5", "a": {}, "d": []}
        content_rect = {"x": 0, "y": 0, "width": 0, "height": 0}
        pipe_data = None
        missing_controls = ["未知阀"]
        quality_issues = [{"severity": "warning", "issue_type": "image_recognition", "message": "需要核验", "controls": []}]

    captured = {}

    def fake_generate_image_layout(image, materials, width, height, title):
        captured["image"] = image
        captured["materials"] = materials
        captured["size"] = (width, height)
        captured["title"] = title
        return FakeResult()

    async def fake_generate(*args, **kwargs):
        raise AssertionError("图片入口不能调用文字布局")

    monkeypatch.setattr(canvas_module, "generate_image_layout", fake_generate_image_layout)
    monkeypatch.setattr(AgentClass, "generate", fake_generate)
    app.dependency_overrides[deps_module.get_material_db] = lambda: fake_db
    app.dependency_overrides[deps_module.get_layout_agent] = lambda: AgentClass(db=None)
    try:
        resp = client.post(
            "/api/canvas/layout/image",
            files={"file": ("image01.png", b"fake-bytes", "image/png")},
            data={"title": "image-test", "canvas_width": "1920", "canvas_height": "1080"},
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert captured["image"] == b"fake-bytes"
    assert captured["materials"] == [{"displayName": "泵"}]
    assert fake_db.calls == 1
    assert captured["size"] == (1920, 1080)
    assert captured["title"] == "image-test"
    assert resp.json()["data"]["file_name"].startswith("image-test")
    assert resp.json()["data"]["missing_controls"] == ["未知阀"]
    assert resp.json()["data"]["quality_issues"][0]["message"] == "需要核验"


@pytest.mark.parametrize("error,status", [(ValueError("无效图片"), 422), (RuntimeError("识别失败"), 502), (FileNotFoundError("tesseract"), 503), (subprocess.TimeoutExpired("tesseract", 30), 504)])
def test_layout_image_route_returns_recognition_errors(monkeypatch, error, status):
    from app.routers import canvas as canvas_module

    class FakeDB:
        async def list_query_results(self, query):
            return [{"displayName": "泵"}]

    def fail(*args):
        raise error

    monkeypatch.setattr(canvas_module, "generate_image_layout", fail)
    app.dependency_overrides[deps_module.get_material_db] = lambda: FakeDB()
    try:
        response = client.post("/api/canvas/layout/image", files={"file": ("image.png", b"bytes", "image/png")})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == status


def test_layout_image_route_requires_materials(monkeypatch):
    class EmptyDB:
        async def list_query_results(self, query):
            return []

    app.dependency_overrides[deps_module.get_material_db] = lambda: EmptyDB()
    app.dependency_overrides[deps_module.get_layout_agent] = lambda: LayoutAgent(db=None)
    try:
        resp = client.post(
            "/api/canvas/layout/image",
            files={"file": ("image01.png", b"fake-bytes", "image/png")},
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 422
    assert resp.json()["detail"] == "query_results 表为空"
