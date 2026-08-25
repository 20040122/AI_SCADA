from __future__ import annotations

import json
from typing import Any, Callable, Optional

import httpx
import pytest
from fastapi.testclient import TestClient

import app.deps as deps_module
from app.main import app
from app.services.canvas_upload_service import (
    CanvasUploadService,
    UploadBlockedError,
    UploadResult,
    UploadTimeoutError,
    UploadUpstreamError,
)
from model.layout_tools.pipe_serializer import PipeConversionError, PipeTemplateError

LIBRARY = [
    {"displayName": "液压泵", "image": "symbols/pump.json", "width": 154, "height": 70},
    {"displayName": "冷水机", "image": "symbols/chiller.json", "width": 232, "height": 136},
]


def _canvas_json(controls: list[dict]) -> dict:
    return {
        "v": "1",
        "p": {"layers": [], "autoAdjustIndex": False, "hierarchicalRendering": False},
        "a": {
            "width": 1920,
            "height": 1080,
            "fitContent": False,
            "rectSelectable": False,
            "pannable": False,
            "zoomable": False,
        },
        "d": controls,
        "contentRect": {"x": 0, "y": 0, "width": 0, "height": 0},
    }


def _control(
    node_i: int,
    display_name: str,
    image: str,
    x: float,
    y: float,
    w: float,
    h: float,
    attrs: Optional[dict] = None,
) -> dict:
    a = {"layout.node": True, "layout.group": "g1", "layout.instance": 0}
    if attrs:
        a.update(attrs)
    return {
        "c": "ht.Node",
        "i": node_i,
        "p": {
            "displayName": display_name,
            "image": image,
            "position": {"x": x, "y": y},
            "width": w,
            "height": h,
        },
        "a": a,
    }


def _label(node_i: int, label_for: int, text: str, x: float, y: float, w: float, h: float) -> dict:
    return {
        "c": "ht.Text",
        "i": node_i,
        "p": {
            "displayName": text,
            "position": {"x": x, "y": y},
            "width": w,
            "height": h,
        },
        "s": {"text": text},
        "a": {"layout.role": "control-label", "layout.labelFor": label_for},
    }


def _mock_client(handler: Callable) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def _upload(
    json_data: dict,
    library: Optional[list[dict]] = None,
    client: Optional[httpx.AsyncClient] = None,
    file_name: str = "画面.json",
    pipe_data: Optional[dict] = None,
) -> UploadResult:
    if client is None:
        client = _mock_client(lambda request: httpx.Response(200, text="ok"))
    service = CanvasUploadService(client=client)
    return await service.upload_canvas(file_name, json_data, library or LIBRARY, pipe_data=pipe_data)


async def _ok_handler(request: httpx.Request) -> httpx.Response:
    body = request.read().decode("utf-8")
    assert "multipart/form-data" in request.headers["content-type"]
    assert 'name="path"' in body
    assert "displays/dutzcm/画面.json" in body
    assert '"displayName": "液压泵"' in body
    return httpx.Response(200, text="ok")


def _pipe_edge(edge_i: int, source_i: int, target_i: int) -> dict:
    return {
        "c": "ht.Edge",
        "i": edge_i,
        "p": {"source": {"__i": source_i}, "target": {"__i": target_i}},
        "s": {"edge.width": 5, "edge.color": "#60acfc"},
        "a": {"layout.role": "pipe"},
    }


def _plain_edge(edge_i: int, source_i: int, target_i: int) -> dict:
    return {
        "c": "ht.Edge",
        "i": edge_i,
        "p": {"source": {"__i": source_i}, "target": {"__i": target_i}},
        "s": {"edge.width": 1},
        "a": {"owner": "manual"},
    }


def _conn(sg: str, sn: str, si: int, tg: str, tn: str, ti: int) -> dict:
    return {
        "id": f"pipe-{sn}-{tn}",
        "source": {"group": sg, "node": sn, "instance": si, "port": "out"},
        "target": {"group": tg, "node": tn, "instance": ti, "port": "in"},
    }


class TestHistoryCorrection:
    @pytest.mark.asyncio
    async def test_inscribes_ratio_keeps_center_shrinks_only(self):
        controls = [_control(1, "液压泵", "symbols/pump.json", 300, 300, 200, 100)]
        result = await _upload(_canvas_json(controls))
        node = result.json_data["d"][0]
        assert node["p"]["position"]["x"] == 300
        assert node["p"]["position"]["y"] == 300
        assert node["p"]["width"] == 200
        assert node["p"]["height"] == pytest.approx(90.91, abs=0.01)
        assert abs(200 / 90.91 - 154 / 70) / (154 / 70) <= 0.001
        assert len(result.corrections) == 1
        correction = result.corrections[0]
        assert correction["node_i"] == 1
        assert correction["before"] == {"width": 200, "height": 100}
        assert correction["after"]["width"] == 200
        assert correction["after"]["height"] == pytest.approx(90.91, abs=0.01)
        assert result.warnings == []

    @pytest.mark.asyncio
    async def test_metadata_wins_over_library(self):
        attrs = {"layout.sourceWidth": 154, "layout.sourceHeight": 70}
        controls = [_control(1, "未知控件", "symbols/unknown.json", 100, 100, 300, 150, attrs)]
        result = await _upload(_canvas_json(controls))
        node = result.json_data["d"][0]
        assert node["p"]["width"] == 300
        assert node["p"]["height"] == pytest.approx(136.36, abs=0.01)

    @pytest.mark.asyncio
    async def test_library_name_image_match(self):
        controls = [_control(1, "冷水机", "symbols/chiller.json", 500, 500, 120, 80)]
        result = await _upload(_canvas_json(controls))
        node = result.json_data["d"][0]
        assert node["p"]["height"] == pytest.approx(70.34, abs=0.01)

    @pytest.mark.asyncio
    async def test_suffix_strip_resolution(self):
        controls = [_control(1, "液压泵2", "symbols/pump.json", 400, 400, 154, 70)]
        result = await _upload(_canvas_json(controls))
        assert len(result.corrections) == 0

    @pytest.mark.asyncio
    async def test_unchanged_control_has_no_correction(self):
        controls = [_control(1, "液压泵", "symbols/pump.json", 400, 400, 154, 70)]
        result = await _upload(_canvas_json(controls))
        assert result.corrections == []

    @pytest.mark.asyncio
    async def test_content_rect_recomputed(self):
        controls = [
            _control(1, "液压泵", "symbols/pump.json", 200, 200, 200, 100),
            _control(2, "冷水机", "symbols/chiller.json", 800, 600, 120, 80),
        ]
        result = await _upload(_canvas_json(controls))
        rect = result.json_data["contentRect"]
        assert rect["x"] == pytest.approx(100, abs=0.01)
        assert rect["y"] == pytest.approx(154.55, abs=0.01)
        assert rect["width"] == pytest.approx(760, abs=0.01)
        assert rect["height"] == pytest.approx(480.63, abs=0.01)

    @pytest.mark.asyncio
    async def test_label_repositioned_after_correction(self):
        controls = [
            _control(1, "液压泵", "symbols/pump.json", 300, 300, 200, 100),
            _label(2, 1, "液压泵", 300, 226, 200, 32),
        ]
        result = await _upload(_canvas_json(controls))
        label = result.json_data["d"][1]
        assert label["p"]["position"]["y"] == pytest.approx(230.55, abs=0.01)
        assert label["p"]["width"] == 200
        assert label["p"]["height"] == 32

    @pytest.mark.asyncio
    async def test_legacy_label_repositioned_after_correction_mocked(self):
        controls = [
            _control(1, "液压泵", "symbols/pump.json", 300, 300, 200, 100),
            _label(2, 1, "液压泵", 300, 226, 200, 32),
        ]
        result = await _upload(
            _canvas_json(controls), client=_mock_client(_ok_handler)
        )
        label = result.json_data["d"][1]
        assert label["p"]["position"]["y"] == pytest.approx(230.55, abs=0.01)
        assert label["p"]["width"] == 200
        assert label["p"]["height"] == 32

    @pytest.mark.asyncio
    async def test_inline_label_fields_preserved_after_correction(self):
        controls = [
            _control(1, "液压泵", "symbols/pump.json", 300, 300, 200, 100),
        ]
        controls[0]["s"] = {
            "label": "泵",
            "label.color": "rgb(255,255,255)",
            "label.font": "18px arial, sans-serif",
        }
        result = await _upload(
            _canvas_json(controls), client=_mock_client(_ok_handler)
        )
        node = result.json_data["d"][0]
        assert node["s"] == {
            "label": "泵",
            "label.color": "rgb(255,255,255)",
            "label.font": "18px arial, sans-serif",
        }
        assert node["p"]["height"] == pytest.approx(90.91, abs=0.01)
        assert len(result.corrections) == 1

    @pytest.mark.asyncio
    async def test_upload_keeps_both_inline_and_legacy_label(self):
        controls = [
            _control(1, "液压泵", "symbols/pump.json", 300, 300, 200, 100),
            _label(2, 1, "液压泵", 300, 226, 200, 32),
        ]
        controls[0]["s"] = {
            "label": "泵",
            "label.color": "rgb(255,255,255)",
            "label.font": "18px arial, sans-serif",
        }
        result = await _upload(
            _canvas_json(controls), client=_mock_client(_ok_handler)
        )
        assert result.json_data["d"][0]["s"]["label"] == "泵"
        assert result.json_data["d"][1]["a"]["layout.role"] == "control-label"
        assert result.json_data["d"][1]["p"]["width"] == 200

    @pytest.mark.asyncio
    async def test_plain_title_text_unaffected(self):
        title = {
            "c": "ht.Text",
            "i": 3,
            "p": {
                "displayName": "标题",
                "position": {"x": 100, "y": 100},
                "width": 200,
                "height": 40,
            },
            "s": {"text": "标题"},
            "a": {"layout.role": "title"},
        }
        controls = [
            _control(1, "液压泵", "symbols/pump.json", 300, 300, 200, 100),
            title,
        ]
        result = await _upload(
            _canvas_json(controls), client=_mock_client(_ok_handler)
        )
        assert result.json_data["d"][1]["s"]["text"] == "标题"

    @pytest.mark.asyncio
    async def test_existing_overlap_returns_warning(self):
        controls = [
            _control(1, "液压泵", "symbols/pump.json", 300, 300, 200, 100),
            _control(2, "冷水机", "symbols/chiller.json", 350, 320, 120, 80),
        ]
        result = await _upload(_canvas_json(controls))
        assert result.corrections != []
        assert any("overlap" in warning for warning in result.warnings)

    def test_collision_warnings_detect_new_and_enlarged(self):
        a = {"x": 100, "y": 100, "width": 100, "height": 100}
        b = {"x": 180, "y": 100, "width": 100, "height": 100}
        with pytest.raises(UploadBlockedError):
            CanvasUploadService._collision_warnings([a], [a, b])
        with pytest.raises(UploadBlockedError):
            CanvasUploadService._collision_warnings([a, b], [a, {**b, "width": 150}])


class TestBlockedUploads:
    @pytest.mark.asyncio
    async def test_missing_size_blocks(self):
        controls = [_control(1, "液压泵", "symbols/pump.json", 100, 100, 0, 100)]
        with pytest.raises(UploadBlockedError) as exc_info:
            await _upload(_canvas_json(controls))
        assert "non-positive size" in str(exc_info.value)
        assert "1" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_no_match_blocks_listing_controls(self):
        controls = [_control(1, "不存在", "symbols/none.json", 100, 100, 100, 100)]
        with pytest.raises(UploadBlockedError) as exc_info:
            await _upload(_canvas_json(controls))
        assert "不存在" in str(exc_info.value)
        assert "symbols/none.json" in str(exc_info.value)
        assert "1" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_duplicate_image_path_ambiguous_blocks(self):
        library = [
            {"displayName": "阀门", "image": "symbols/valve.json", "width": 64, "height": 64},
            {"displayName": "阀门", "image": "symbols/valve.json", "width": 100, "height": 50},
        ]
        controls = [_control(1, "阀门", "symbols/valve.json", 100, 100, 64, 64)]
        with pytest.raises(UploadBlockedError) as exc_info:
            await _upload(_canvas_json(controls), library=library)
        assert "cannot be resolved" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_suffix_strip_ambiguous_blocks(self):
        library = [
            {"displayName": "阀门", "image": "symbols/valve.json", "width": 64, "height": 64},
            {"displayName": "阀门", "image": "symbols/valve.json", "width": 100, "height": 50},
        ]
        controls = [_control(1, "阀门3", "symbols/valve.json", 100, 100, 64, 64)]
        with pytest.raises(UploadBlockedError):
            await _upload(_canvas_json(controls), library=library)

    @pytest.mark.asyncio
    async def test_invalid_file_name_blocks(self):
        controls = [_control(1, "液压泵", "symbols/pump.json", 100, 100, 154, 70)]
        for bad in ["", "a.txt", "dir/画面.json", "../画面.json"]:
            with pytest.raises(UploadBlockedError):
                await _upload(_canvas_json(controls), file_name=bad)

    @pytest.mark.asyncio
    async def test_schema_invalid_blocks(self):
        data = _canvas_json([])
        del data["a"]["width"]
        with pytest.raises(UploadBlockedError):
            await _upload(data)

    @pytest.mark.asyncio
    async def test_input_json_not_mutated(self):
        data = _canvas_json([_control(1, "液压泵", "symbols/pump.json", 300, 300, 200, 100)])
        original = json.dumps(data, ensure_ascii=False)
        await _upload(data)
        assert json.dumps(data, ensure_ascii=False) == original


class TestUploadPipeMerge:
    def _pipe_controls(self) -> list[dict]:
        return [
            _control(1, "液压泵", "symbols/pump.json", 300, 300, 154, 70, attrs={"layout.node": "泵1"}),
            _control(2, "液压泵", "symbols/pump.json", 700, 300, 154, 70, attrs={"layout.node": "泵2"}),
            _control(3, "液压泵", "symbols/pump.json", 1100, 300, 154, 70, attrs={"layout.node": "泵3"}),
        ]

    def _managed(self) -> list[dict]:
        return [_pipe_edge(20, 1, 2), _pipe_edge(21, 2, 3)]

    async def _upload_with_edges(
        self, edges: list[dict], pipe_data: Optional[dict], handler: Callable = _ok_handler
    ) -> UploadResult:
        data = _canvas_json(self._pipe_controls() + edges)
        return await _upload(data, client=_mock_client(handler), pipe_data=pipe_data)

    @pytest.mark.asyncio
    async def test_omitted_pipe_data_leaves_edges_untouched(self):
        edges = self._managed() + [_plain_edge(30, 1, 2)]
        result = await _upload(_canvas_json(self._pipe_controls() + edges), client=_mock_client(_ok_handler))
        by_id = {item["i"]: item for item in result.json_data["d"] if item["c"] == "ht.Edge"}
        assert set(by_id) == {20, 21, 30}

    @pytest.mark.asyncio
    async def test_empty_connections_clears_managed_edges(self):
        edges = self._managed() + [_plain_edge(30, 1, 2)]
        result = await self._upload_with_edges(edges, {"connections": []})
        by_id = {item["i"]: item for item in result.json_data["d"] if item["c"] == "ht.Edge"}
        assert set(by_id) == {30}
        assert by_id[30]["a"] == {"owner": "manual"}

    @pytest.mark.asyncio
    async def test_merges_remaps_and_dedupes(self):
        pipe_data = {
            "connections": [
                _conn("g1", "泵1", 0, "g1", "泵2", 0),
                _conn("g1", "泵1", 0, "g1", "泵2", 0),
                _conn("g1", "泵2", 0, "g1", "泵1", 0),
            ]
        }
        result = await self._upload_with_edges(self._managed(), pipe_data)
        edges = [item for item in result.json_data["d"] if item["c"] == "ht.Edge"]
        assert len(edges) == 2
        first, second = edges
        assert first["i"] == 4
        assert second["i"] == 5
        assert first["p"]["source"] == {"__i": 1}
        assert first["p"]["target"] == {"__i": 2}
        assert second["p"]["source"] == {"__i": 2}
        assert second["p"]["target"] == {"__i": 1}
        assert first["a"] == {"layout.role": "pipe"}
        assert first["s"]["edge.width"] == 5
        assert first["s"]["edge.color"] == "#60acfc"
        payload = json.dumps(edges, ensure_ascii=False)
        for forbidden in ("port", "layout.group", "layout.node", "layout.instance", "instance"):
            assert forbidden not in payload
        assert '"__i"' in payload

    @pytest.mark.asyncio
    async def test_edge_ids_start_after_max_existing_i(self):
        data = _canvas_json(self._pipe_controls() + [_label(50, 1, "泵1", 300, 200, 200, 32)])
        pipe_data = {"connections": [_conn("g1", "泵1", 0, "g1", "泵2", 0)]}
        result = await _upload(data, client=_mock_client(_ok_handler), pipe_data=pipe_data)
        edges = [item for item in result.json_data["d"] if item["c"] == "ht.Edge"]
        assert [item["i"] for item in edges] == [51]

    @pytest.mark.asyncio
    async def test_repeated_upload_no_accumulation(self):
        pipe_data = {"connections": [_conn("g1", "泵1", 0, "g1", "泵2", 0)]}
        first = await self._upload_with_edges(self._managed(), pipe_data)
        second = await _upload(
            first.json_data, client=_mock_client(_ok_handler), pipe_data=pipe_data
        )
        first_edges = [item for item in first.json_data["d"] if item["c"] == "ht.Edge"]
        second_edges = [item for item in second.json_data["d"] if item["c"] == "ht.Edge"]
        assert len(first_edges) == len(second_edges) == 1
        assert second_edges[0]["i"] == first_edges[0]["i"]

    @pytest.mark.asyncio
    async def test_plain_edges_survive_merge(self):
        pipe_data = {"connections": [_conn("g1", "泵1", 0, "g1", "泵2", 0)]}
        result = await self._upload_with_edges(
            self._managed() + [_plain_edge(30, 1, 2)], pipe_data
        )
        edges = [item for item in result.json_data["d"] if item["c"] == "ht.Edge"]
        assert len(edges) == 2
        ids = sorted(item["i"] for item in edges)
        assert ids == [30, 31]

    @pytest.mark.asyncio
    async def test_missing_endpoint_raises_without_upload(self):
        pipe_data = {
            "connections": [
                _conn("g1", "泵1", 0, "g1", "已删除泵", 0),
            ]
        }
        async def fail_handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("upload must not be attempted")
        with pytest.raises(PipeConversionError) as exc_info:
            await _upload(
                _canvas_json(self._pipe_controls()),
                client=_mock_client(fail_handler),
                pipe_data=pipe_data,
            )
        assert "端点不存在" in str(exc_info.value)
        assert "已删除泵" in str(exc_info.value)


class TestDaoScadaUpload:
    @pytest.mark.asyncio
    async def test_success_multipart_path_and_content(self):
        controls = [_control(1, "液压泵", "symbols/pump.json", 300, 300, 200, 100)]
        result = await _upload(_canvas_json(controls), client=_mock_client(_ok_handler))
        assert len(result.corrections) == 1

    @pytest.mark.asyncio
    async def test_upstream_reject_maps_to_502(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="boom")

        with pytest.raises(UploadUpstreamError):
            await _upload(
                _canvas_json([_control(1, "液压泵", "symbols/pump.json", 300, 300, 154, 70)]),
                client=_mock_client(handler),
            )

    @pytest.mark.asyncio
    async def test_connect_error_maps_to_502(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=request)

        with pytest.raises(UploadUpstreamError):
            await _upload(
                _canvas_json([_control(1, "液压泵", "symbols/pump.json", 300, 300, 154, 70)]),
                client=_mock_client(handler),
            )

    @pytest.mark.asyncio
    async def test_timeout_maps_to_504(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("slow", request=request)

        with pytest.raises(UploadTimeoutError):
            await _upload(
                _canvas_json([_control(1, "液压泵", "symbols/pump.json", 300, 300, 154, 70)]),
                client=_mock_client(handler),
            )


class FakeMaterialDB:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    async def list_all(self) -> list[dict]:
        return self._rows


class FakeUploadService:
    result: Optional[UploadResult] = None
    error: Optional[Exception] = None
    received_pipe_data: Optional[dict] = None

    def __init__(self) -> None:
        self._result = type(self).result
        self._error = type(self).error

    async def upload_canvas(
        self,
        file_name: str,
        json_data: dict,
        library: list[dict],
        pipe_data: Optional[dict] = None,
    ) -> Any:
        if self._error is not None:
            raise self._error
        assert library == LIBRARY
        type(self).received_pipe_data = pipe_data
        return self._result


class TestUploadRoute:
    def _post(self, payload: dict) -> httpx.Response:
        return TestClient(app).post("/api/canvas/upload", json=payload)

    def test_route_success(self, monkeypatch):
        monkeypatch.setattr(deps_module, "_material_db", FakeMaterialDB(LIBRARY))
        result = UploadResult(
            json_data=_canvas_json([]),
            corrections=[
                {
                    "node_i": 1,
                    "display_name": "液压泵",
                    "image": "symbols/pump.json",
                    "before": {"width": 200, "height": 100},
                    "after": {"width": 200, "height": 90.91},
                }
            ],
            warnings=[],
        )
        monkeypatch.setattr(FakeUploadService, "result", result)
        monkeypatch.setattr("app.routers.canvas.CanvasUploadService", FakeUploadService)
        response = self._post({"file_name": "画面.json", "json_data": _canvas_json([])})
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["file_name"] == "画面.json"
        assert data["corrections"][0]["node_i"] == 1
        assert data["corrections"][0]["after"]["height"] == pytest.approx(90.91, abs=0.01)
        assert data["warnings"] == []

    def test_route_forwards_pipe_data(self, monkeypatch):
        monkeypatch.setattr(deps_module, "_material_db", FakeMaterialDB(LIBRARY))
        result = UploadResult(json_data=_canvas_json([]), corrections=[], warnings=[])
        monkeypatch.setattr(FakeUploadService, "result", result)
        monkeypatch.setattr(FakeUploadService, "received_pipe_data", None)
        monkeypatch.setattr("app.routers.canvas.CanvasUploadService", FakeUploadService)
        pipe_data = {
            "connections": [
                {
                    "id": "pipe-1",
                    "source": {"group": "g1", "node": "泵1", "instance": 0, "port": "out"},
                    "target": {"group": "g1", "node": "泵2", "instance": 0, "port": "in"},
                }
            ]
        }
        response = self._post(
            {"file_name": "画面.json", "json_data": _canvas_json([]), "pipe_data": pipe_data}
        )
        assert response.status_code == 200
        assert FakeUploadService.received_pipe_data == pipe_data

    def test_route_omitted_pipe_data_passes_none(self, monkeypatch):
        monkeypatch.setattr(deps_module, "_material_db", FakeMaterialDB(LIBRARY))
        result = UploadResult(json_data=_canvas_json([]), corrections=[], warnings=[])
        monkeypatch.setattr(FakeUploadService, "result", result)
        monkeypatch.setattr(FakeUploadService, "received_pipe_data", None)
        monkeypatch.setattr("app.routers.canvas.CanvasUploadService", FakeUploadService)
        response = self._post({"file_name": "画面.json", "json_data": _canvas_json([])})
        assert response.status_code == 200
        assert FakeUploadService.received_pipe_data is None

    @pytest.mark.parametrize(
        ("error", "status"),
        [
            (UploadBlockedError("blocked"), 422),
            (UploadUpstreamError("upstream"), 502),
            (UploadTimeoutError("timeout"), 504),
            (PipeConversionError("端点不存在"), 422),
            (PipeTemplateError("template invalid"), 422),
        ],
    )
    def test_route_error_mapping(self, monkeypatch, error: Exception, status: int):
        monkeypatch.setattr(deps_module, "_material_db", FakeMaterialDB(LIBRARY))
        monkeypatch.setattr(FakeUploadService, "error", error)
        monkeypatch.setattr("app.routers.canvas.CanvasUploadService", FakeUploadService)
        response = self._post({"file_name": "画面.json", "json_data": _canvas_json([])})
        assert response.status_code == status
