from __future__ import annotations

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


def test_validate_route_exists():
    resp = client.post("/api/validate", json={"category": "canvas", "json_data": {"v": "8.0.5"}})
    assert resp.status_code in (200, 422, 500)
