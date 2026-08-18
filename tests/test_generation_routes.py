from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.deps as deps_module
from app.main import app
from app.services.generation_service import GenerationAPIError, GenerationTask

client = TestClient(app, raise_server_exceptions=False)


class FakeGenerationManager:
    def __init__(self):
        self.create_result = None
        self.create_error = None
        self.get_result = None
        self.to_dict_result = {}
        self.preview_path = None
        self.preview_error = None
        self.regenerate_result = None
        self.regenerate_error = None
        self.confirm_result = None
        self.confirm_error = None
        self.discard_error = None

    def create(self, query, name):
        if self.create_error is not None:
            raise self.create_error
        return self.create_result

    def get(self, generation_id):
        return self.get_result

    def to_dict(self, task):
        return self.to_dict_result

    def get_preview_path(self, generation_id):
        if self.preview_error is not None:
            raise self.preview_error
        return self.preview_path

    def regenerate(self, generation_id):
        if self.regenerate_error is not None:
            raise self.regenerate_error
        return self.regenerate_result

    async def confirm(self, generation_id):
        if self.confirm_error is not None:
            raise self.confirm_error
        return self.confirm_result

    def discard(self, generation_id):
        if self.discard_error is not None:
            raise self.discard_error


@pytest.fixture
def fake_manager():
    mgr = FakeGenerationManager()
    deps_module._generation_manager = mgr
    yield mgr
    deps_module._generation_manager = None


def _make_task(**overrides):
    defaults = {
        "generation_id": "abc123",
        "query": "离心泵",
        "name": "离心泵",
        "seed": 42,
    }
    defaults.update(overrides)
    return GenerationTask(**defaults)


def test_create_generation_returns_202(fake_manager):
    fake_manager.create_result = _make_task()
    resp = client.post(
        "/api/control/generations",
        json={"query": "离心泵", "name": "离心泵"},
    )
    assert resp.status_code == 202
    data = resp.json()["data"]
    assert data["generation_id"] == "abc123"
    assert data["status"] == "queued"


def test_create_generation_invalid_name_400(fake_manager):
    fake_manager.create_error = GenerationAPIError("名称非法", 400, "invalid_name")
    resp = client.post(
        "/api/control/generations",
        json={"query": "x", "name": ""},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "名称非法"


def test_create_generation_conflict_409(fake_manager):
    fake_manager.create_error = GenerationAPIError("同名控件已存在", 409, "conflict")
    resp = client.post(
        "/api/control/generations",
        json={"query": "阀门", "name": "阀门"},
    )
    assert resp.status_code == 409


def test_get_generation_returns_status(fake_manager):
    task = _make_task(status="running")
    fake_manager.get_result = task
    fake_manager.to_dict_result = {
        "generation_id": "abc123",
        "name": "离心泵",
        "status": "running",
        "seed": 42,
        "created_at": "2026-01-01T00:00:00+00:00",
        "expires_at": None,
        "preview_url": None,
        "error": None,
        "error_code": None,
    }
    resp = client.get("/api/control/generations/abc123")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "running"
    assert data["seed"] == 42
    assert data["preview_url"] is None


def test_get_generation_missing_404(fake_manager):
    fake_manager.get_result = None
    resp = client.get("/api/control/generations/unknown")
    assert resp.status_code == 404


def test_preview_returns_png(fake_manager, tmp_path):
    png = tmp_path / "preview.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    fake_manager.preview_path = png
    resp = client.get("/api/control/generations/abc123/preview")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content == b"\x89PNG\r\n\x1a\nfake"


def test_preview_not_ready_409(fake_manager):
    fake_manager.preview_error = GenerationAPIError("尚未就绪", 409, "not_ready")
    resp = client.get("/api/control/generations/abc123/preview")
    assert resp.status_code == 409


def test_preview_expired_410(fake_manager):
    fake_manager.preview_error = GenerationAPIError("已过期", 410, "expired")
    resp = client.get("/api/control/generations/abc123/preview")
    assert resp.status_code == 410


def test_regenerate_success(fake_manager):
    fake_manager.regenerate_result = _make_task(status="queued", seed=777)
    resp = client.post("/api/control/generations/abc123/regenerate")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "queued"
    assert data["generation_id"] == "abc123"


def test_regenerate_conflict_409(fake_manager):
    fake_manager.regenerate_error = GenerationAPIError("状态冲突", 409, "conflict")
    resp = client.post("/api/control/generations/abc123/regenerate")
    assert resp.status_code == 409


def test_regenerate_expired_410(fake_manager):
    fake_manager.regenerate_error = GenerationAPIError("已过期", 410, "expired")
    resp = client.post("/api/control/generations/abc123/regenerate")
    assert resp.status_code == 410


def test_confirm_success(fake_manager):
    fake_manager.confirm_result = {
        "displayName": "离心泵",
        "image": "assets/Agent/离心泵.png",
        "width": 128,
        "height": 128,
        "source": "ai-generated",
        "similarity": 1.0,
    }
    resp = client.post("/api/control/generations/abc123/confirm")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["displayName"] == "离心泵"
    assert data["image"] == "assets/Agent/离心泵.png"


def test_confirm_conflict_409(fake_manager):
    fake_manager.confirm_error = GenerationAPIError("同名冲突", 409, "conflict")
    resp = client.post("/api/control/generations/abc123/confirm")
    assert resp.status_code == 409


def test_confirm_expired_410(fake_manager):
    fake_manager.confirm_error = GenerationAPIError("已过期", 410, "expired")
    resp = client.post("/api/control/generations/abc123/confirm")
    assert resp.status_code == 410


def test_discard_success(fake_manager):
    resp = client.delete("/api/control/generations/abc123")
    assert resp.status_code == 200
    assert resp.json()["data"] is None


def test_discard_confirmed_409(fake_manager):
    fake_manager.discard_error = GenerationAPIError("已确认任务不能放弃", 409, "conflict")
    resp = client.delete("/api/control/generations/abc123")
    assert resp.status_code == 409
