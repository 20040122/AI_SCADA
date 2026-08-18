from __future__ import annotations

from fastapi.testclient import TestClient

import app.deps as deps_module
from app.main import app
from model.control_agent import ControlAgentResult, KeywordResult
from model.control_tools.catalog import CatalogCorruptError
from model.control_tools.extract import (
    ControlModelOutputError,
    ControlModelTimeoutError,
    ControlModelUnavailableError,
)

client = TestClient(app, raise_server_exceptions=False)


class FakeControlAgent:
    def __init__(self, result=None, exc=None):
        self._result = result
        self._exc = exc

    async def process_query(self, query):
        if self._exc is not None:
            raise self._exc
        return self._result


def _install(exc=None, result=None):
    deps_module._control_agent = FakeControlAgent(result=result, exc=exc)


def test_search_success_response_structure():
    result = ControlAgentResult(
        keywords=[KeywordResult(keyword="飞机", candidates=[])],
        missed=["飞机"],
    )
    _install(result=result)
    resp = client.post("/api/control/search", json={"query": "飞机"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    data = body["data"]
    assert data["missed"] == ["飞机"]
    assert len(data["keywords"]) == 1
    kw = data["keywords"][0]
    assert kw["keyword"] == "飞机"
    assert kw["candidates"] == []


def test_search_model_output_error_maps_to_502():
    _install(exc=ControlModelOutputError("bad output"))
    resp = client.post("/api/control/search", json={"query": "飞机"})
    assert resp.status_code == 502


def test_search_unavailable_maps_to_503():
    _install(exc=ControlModelUnavailableError("conn down"))
    resp = client.post("/api/control/search", json={"query": "飞机"})
    assert resp.status_code == 503


def test_search_catalog_corrupt_maps_to_503():
    _install(exc=CatalogCorruptError("collection incomplete"))
    resp = client.post("/api/control/search", json={"query": "温度"})
    assert resp.status_code == 503


def test_search_timeout_maps_to_504():
    _install(exc=ControlModelTimeoutError("timeout"))
    resp = client.post("/api/control/search", json={"query": "飞机"})
    assert resp.status_code == 504
