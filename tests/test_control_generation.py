from __future__ import annotations

import asyncio
import base64
import json
import time

import httpx
import pytest

from app.services.generation_service import (
    AssetUploader,
    GenerationAPIError,
    GenerationManager,
    GenerationStatus,
    validate_name,
)
from data.sqlite.material_db import MaterialDB
from model.control_agent import ControlAgent
from model.control_tools.catalog import ControlCatalogManager
from picture.qwen import (
    GenerationError,
    ImageDecodeError,
    MissingApiKeyError,
    QwenResponseError,
    QwenTimeoutError,
    QwenUnavailableError,
)
from tests.conftest import FakeAsyncClient, FakeEmbedding, make_fake_completion

MINIMAL_MAPPINGS = json.dumps({"version": "1", "mappings": []}, ensure_ascii=False)


class FakeGenerator:
    def __init__(self, error: GenerationError | None = None, delay: float = 0.02):
        self.calls = 0
        self.active = 0
        self.max_active = 0
        self.seeds: list[int] = []
        self.error = error
        self.delay = delay

    def __call__(self, name: str, seed: int, output_path) -> None:
        self.calls += 1
        self.seeds.append(seed)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                time.sleep(self.delay)
            if self.error is not None:
                raise self.error
            output_path.write_bytes(b"fake-png-bytes")
        finally:
            self.active -= 1


class FakeUploader:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.uploads: list[tuple[str, bytes]] = []

    async def upload(self, name: str, png_path) -> None:
        if self.error is not None:
            raise self.error
        self.uploads.append((name, png_path.read_bytes()))


class FakeHttpxClient:
    def __init__(self, response: httpx.Response | None = None, error: Exception | None = None):
        self.response = response or httpx.Response(200)
        self.error = error
        self.calls: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, files=None, **kwargs):
        self.calls.append({"url": url, "files": files})
        if self.error is not None:
            raise self.error
        return self.response


BASE_CONTROL = {"displayName": "水泵", "image": "symbols/a/水泵.json", "width": 100, "height": 80}


async def _make_env(tmp_path, controls=None):
    jsonl = tmp_path / "control.jsonl"
    lines = [BASE_CONTROL]
    if controls:
        lines = list(controls)
    jsonl.write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in lines) + "\n",
        encoding="utf-8",
    )
    mappings = tmp_path / "control_mappings.json"
    mappings.write_text(MINIMAL_MAPPINGS, encoding="utf-8")
    catalog = ControlCatalogManager(
        chroma_dir=str(tmp_path / "chroma"),
        control_jsonl_path=str(jsonl),
        mappings_path=str(mappings),
        embedding_function=FakeEmbedding(),
    )
    snap = await catalog.acquire()
    catalog.release(snap)
    db = MaterialDB(db_path=str(tmp_path / "material.db"))
    await db.init_db()
    return jsonl, mappings, catalog, db


def _make_manager(tmp_path, catalog, db, generator=None, uploader=None, ttl=3600.0, cleanup_interval=30.0):
    return GenerationManager(
        temp_dir=tmp_path / "gen",
        ttl_seconds=ttl,
        generator=generator or FakeGenerator(),
        uploader=uploader or FakeUploader(),
        jsonl_path=tmp_path / "control.jsonl",
        catalog=catalog,
        db=db,
        cleanup_interval=cleanup_interval,
    )


async def _wait_status(mgr, generation_id, status, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        task = mgr.get(generation_id)
        if task is not None and task.status == status:
            return task
        await asyncio.sleep(0.01)
    raise AssertionError(f"task {generation_id} did not reach {status}")


def test_validate_name_rejects_invalid():
    with pytest.raises(GenerationAPIError) as exc:
        validate_name("   ")
    assert exc.value.status_code == 400
    assert exc.value.code == "invalid_name"
    with pytest.raises(GenerationAPIError):
        validate_name("x" * 65)
    with pytest.raises(GenerationAPIError):
        validate_name("a/b")
    with pytest.raises(GenerationAPIError):
        validate_name("a\\b")
    with pytest.raises(GenerationAPIError):
        validate_name(".")
    with pytest.raises(GenerationAPIError):
        validate_name("..")
    with pytest.raises(GenerationAPIError):
        validate_name("a\nb")
    with pytest.raises(GenerationAPIError):
        validate_name("a\x00b")
    assert validate_name("  阀门  ") == "阀门"
    assert len(validate_name("x" * 64)) == 64


@pytest.mark.asyncio
async def test_create_rejects_normalized_same_name(tmp_path):
    jsonl, mappings, catalog, db = await _make_env(
        tmp_path, controls=[{"displayName": "阀门", "image": "s/v.json", "width": 10, "height": 10}]
    )
    mgr = _make_manager(tmp_path, catalog, db)
    mgr.start()
    try:
        with pytest.raises(GenerationAPIError) as exc:
            mgr.create("查询", "  阀门 ")
        assert exc.value.status_code == 409
        assert exc.value.code == "conflict"
    finally:
        await mgr.stop()
        catalog.close()
        await db.close()


@pytest.mark.asyncio
async def test_worker_max_concurrency_is_one(tmp_path):
    jsonl, mappings, catalog, db = await _make_env(tmp_path)
    generator = FakeGenerator(delay=0.05)
    mgr = _make_manager(tmp_path, catalog, db, generator=generator)
    mgr.start()
    try:
        ids = [mgr.create("q", f"控件{i}").generation_id for i in range(3)]
        for gid in ids:
            await _wait_status(mgr, gid, GenerationStatus.READY)
        assert generator.calls == 3
        assert generator.max_active == 1
    finally:
        await mgr.stop()
        catalog.close()
        await db.close()


@pytest.mark.asyncio
async def test_regenerate_uses_new_seed_and_deletes_old_preview(tmp_path):
    jsonl, mappings, catalog, db = await _make_env(tmp_path)
    generator = FakeGenerator()
    mgr = _make_manager(tmp_path, catalog, db, generator=generator)
    mgr.start()
    try:
        task = mgr.create("q", "新控件")
        await _wait_status(mgr, task.generation_id, GenerationStatus.READY)
        old_preview = mgr.get(task.generation_id).preview_path
        assert old_preview is not None and old_preview.exists()
        old_seed = mgr.get(task.generation_id).seed
        regenerated = mgr.regenerate(task.generation_id)
        assert regenerated.status == GenerationStatus.QUEUED
        assert regenerated.seed != old_seed
        assert not old_preview.exists()
        assert len(generator.seeds) == 1
        await _wait_status(mgr, task.generation_id, GenerationStatus.READY)
        assert len(generator.seeds) == 2
        assert generator.seeds[1] == regenerated.seed
    finally:
        await mgr.stop()
        catalog.close()
        await db.close()


@pytest.mark.asyncio
async def test_seed_within_qwen_signed_int_range(tmp_path):
    jsonl, mappings, catalog, db = await _make_env(tmp_path)
    generator = FakeGenerator()
    mgr = _make_manager(tmp_path, catalog, db, generator=generator)
    mgr.start()
    try:
        task = mgr.create("q", "新控件")
        assert 0 <= task.seed <= 2 ** 31 - 1
        await _wait_status(mgr, task.generation_id, GenerationStatus.READY)
        old_seed = task.seed
        regenerated = mgr.regenerate(task.generation_id)
        assert 0 <= regenerated.seed <= 2 ** 31 - 1
        assert regenerated.seed != old_seed
    finally:
        await mgr.stop()
        catalog.close()
        await db.close()


@pytest.mark.asyncio
async def test_regenerate_conflicts_while_running_or_finished(tmp_path):
    jsonl, mappings, catalog, db = await _make_env(tmp_path)
    generator = FakeGenerator(delay=0.2)
    mgr = _make_manager(tmp_path, catalog, db, generator=generator)
    mgr.start()
    try:
        task = mgr.create("q", "新控件")
        with pytest.raises(GenerationAPIError) as exc:
            mgr.regenerate(task.generation_id)
        assert exc.value.status_code == 409
        await _wait_status(mgr, task.generation_id, GenerationStatus.READY)
        mgr.discard(task.generation_id)
        with pytest.raises(GenerationAPIError) as exc:
            mgr.regenerate(task.generation_id)
        assert exc.value.status_code == 409
    finally:
        await mgr.stop()
        catalog.close()
        await db.close()


@pytest.mark.asyncio
async def test_failed_generation_error_mapping(tmp_path):
    cases = [
        (QwenTimeoutError(), "qwen_timeout"),
        (QwenUnavailableError(), "qwen_unavailable"),
        (QwenResponseError(), "qwen_response"),
        (MissingApiKeyError(), "missing_api_key"),
        (ImageDecodeError(), "image_decode"),
    ]
    for error, expected_code in cases:
        jsonl, mappings, catalog, db = await _make_env(tmp_path)
        mgr = _make_manager(tmp_path, catalog, db, generator=FakeGenerator(error=error))
        mgr.start()
        try:
            task = mgr.create("q", "控件X")
            await _wait_status(mgr, task.generation_id, GenerationStatus.FAILED)
            assert mgr.get(task.generation_id).error_code == expected_code
            assert mgr.get(task.generation_id).preview_path is None
            with pytest.raises(GenerationAPIError) as exc:
                await mgr.confirm(task.generation_id)
            assert exc.value.status_code == 409
        finally:
            await mgr.stop()
            catalog.close()
            await db.close()


@pytest.mark.asyncio
async def test_ready_expired_discarded_status_and_410(tmp_path):
    jsonl, mappings, catalog, db = await _make_env(tmp_path)
    mgr = _make_manager(tmp_path, catalog, db, generator=FakeGenerator(), ttl=0.15)
    mgr.start()
    try:
        task = mgr.create("q", "新控件")
        await _wait_status(mgr, task.generation_id, GenerationStatus.READY)
        preview = mgr.get(task.generation_id).preview_path
        assert mgr.get_preview_path(task.generation_id) == preview
        await asyncio.sleep(0.2)
        with pytest.raises(GenerationAPIError) as exc:
            mgr.get_preview_path(task.generation_id)
        assert exc.value.status_code == 410
        assert mgr.get(task.generation_id).status == GenerationStatus.EXPIRED
        assert not preview.exists()
        with pytest.raises(GenerationAPIError) as exc:
            await mgr.confirm(task.generation_id)
        assert exc.value.status_code == 410
        mgr.discard(task.generation_id)
        assert mgr.get(task.generation_id).status == GenerationStatus.DISCARDED
        with pytest.raises(GenerationAPIError) as exc:
            mgr.get_preview_path(task.generation_id)
        assert exc.value.status_code == 404
    finally:
        await mgr.stop()
        catalog.close()
        await db.close()


@pytest.mark.asyncio
async def test_cleanup_task_expires_ready_tasks(tmp_path):
    jsonl, mappings, catalog, db = await _make_env(tmp_path)
    mgr = _make_manager(tmp_path, catalog, db, generator=FakeGenerator(), ttl=0.1, cleanup_interval=0.1)
    mgr.start()
    try:
        task = mgr.create("q", "新控件")
        await _wait_status(mgr, task.generation_id, GenerationStatus.READY)
        preview = mgr.get(task.generation_id).preview_path
        await _wait_status(mgr, task.generation_id, GenerationStatus.EXPIRED, timeout=3.0)
        assert not preview.exists()
    finally:
        await mgr.stop()
        catalog.close()
        await db.close()


@pytest.mark.asyncio
async def test_asset_uploader_multipart_contract(tmp_path, monkeypatch):
    class FakeHttpx:
        def __init__(self, response=None, error=None):
            self.response = response or httpx.Response(200)
            self.error = error
            self.calls = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, data=None, files=None, **kwargs):
            self.calls.append({"url": url, "data": data, "files": files, **kwargs})
            if self.error is not None:
                raise self.error
            return self.response

    png_bytes = b"\x89PNG\r\n\x1a\nfake-payload"
    png = tmp_path / "preview.png"
    png.write_bytes(png_bytes)
    fake = FakeHttpx()
    monkeypatch.setattr("httpx.AsyncClient", lambda timeout=None: fake)
    uploader = AssetUploader(base_url="http://daoscada.local/hmi-ui/upload/", timeout=5)
    await uploader.upload("冷却塔", png)
    call = fake.calls[0]
    assert call["url"] == "http://daoscada.local/hmi-ui/upload"
    assert call.get("data") is None
    assert call["files"] is not None
    entries = call["files"]
    assert isinstance(entries, (list, tuple))
    file_map = {item[0]: item for item in entries if isinstance(item, (list, tuple)) and len(item) >= 2}
    assert set(file_map.keys()) == {"path", "content"}
    path_part = file_map["path"][1]
    content_part = file_map["content"][1]
    assert isinstance(path_part, (list, tuple))
    assert isinstance(content_part, (list, tuple))
    assert path_part[0] is None
    assert content_part[0] is None
    assert path_part[1] == "assets/Agent/冷却塔.png"
    content = content_part[1]
    assert isinstance(content, str)
    assert content.startswith("data:image/png;base64,")
    prefix_len = len("data:image/png;base64,")
    decoded = base64.b64decode(content[prefix_len:])
    assert decoded == png_bytes


@pytest.mark.asyncio
async def test_asset_uploader_timeout_and_reject_mapping(tmp_path, monkeypatch):
    png = tmp_path / "preview.png"
    png.write_bytes(b"png")

    fake = FakeHttpxClient(error=httpx.TimeoutException("slow"))
    monkeypatch.setattr("httpx.AsyncClient", lambda timeout=None: fake)
    uploader = AssetUploader(base_url="http://daoscada.local/hmi-ui/upload/", timeout=1)
    with pytest.raises(GenerationAPIError) as exc:
        await uploader.upload("阀门", png)
    assert exc.value.status_code == 504
    assert exc.value.code == "upload_timeout"

    fake = FakeHttpxClient(error=httpx.ConnectError("refused"))
    monkeypatch.setattr("httpx.AsyncClient", lambda timeout=None: fake)
    with pytest.raises(GenerationAPIError) as exc:
        await uploader.upload("阀门", png)
    assert exc.value.status_code == 502
    assert exc.value.code == "upload_failed"

    fake = FakeHttpxClient(response=httpx.Response(500))
    monkeypatch.setattr("httpx.AsyncClient", lambda timeout=None: fake)
    with pytest.raises(GenerationAPIError) as exc:
        await uploader.upload("阀门", png)
    assert exc.value.status_code == 502
    assert exc.value.code == "upload_failed"


@pytest.mark.asyncio
async def test_confirm_appends_to_jsonl_without_trailing_newline(tmp_path):
    jsonl, mappings, catalog, db = await _make_env(tmp_path)
    jsonl.write_bytes(jsonl.read_bytes().rstrip(b"\n"))
    assert not jsonl.read_bytes().endswith(b"\n")
    uploader = FakeUploader()
    mgr = _make_manager(tmp_path, catalog, db, uploader=uploader)
    mgr.start()
    try:
        task = mgr.create("q", "新控件")
        await _wait_status(mgr, task.generation_id, GenerationStatus.READY)
        record = await mgr.confirm(task.generation_id)
        assert record["displayName"] == "新控件"
        assert mgr.get(task.generation_id).status == GenerationStatus.CONFIRMED
        lines = jsonl.read_text(encoding="utf-8").splitlines()
        parsed = [json.loads(line) for line in lines]
        assert parsed[-1]["displayName"] == "新控件"
        assert all(isinstance(o, dict) and "displayName" in o for o in parsed)
    finally:
        await mgr.stop()
        catalog.close()
        await db.close()


@pytest.mark.asyncio
async def test_upload_failure_leaves_jsonl_sqlite_unchanged(tmp_path):
    jsonl, mappings, catalog, db = await _make_env(tmp_path)
    uploader = FakeUploader(error=GenerationAPIError("上传失败", 502, "upload_failed"))
    mgr = _make_manager(tmp_path, catalog, db, uploader=uploader)
    mgr.start()
    try:
        task = mgr.create("q", "新控件")
        await _wait_status(mgr, task.generation_id, GenerationStatus.READY)
        before = jsonl.read_text(encoding="utf-8")
        with pytest.raises(GenerationAPIError) as exc:
            await mgr.confirm(task.generation_id)
        assert exc.value.status_code == 502
        assert jsonl.read_text(encoding="utf-8") == before
        assert await db.search_by_name("新控件") == []
        assert await db.list_query_results() == []
        assert mgr.get(task.generation_id).status == GenerationStatus.READY
    finally:
        await mgr.stop()
        catalog.close()
        await db.close()


@pytest.mark.asyncio
async def test_confirm_success_consistency_and_retrieval(tmp_path):
    jsonl, mappings, catalog, db = await _make_env(tmp_path)
    uploader = FakeUploader()
    mgr = _make_manager(tmp_path, catalog, db, uploader=uploader)
    mgr.start()
    try:
        task = mgr.create("我的查询", "离心泵")
        await _wait_status(mgr, task.generation_id, GenerationStatus.READY)
        record = await mgr.confirm(task.generation_id)
        assert record == {
            "displayName": "离心泵",
            "image": "assets/Agent/离心泵.png",
            "width": 128,
            "height": 128,
            "source": "ai-generated",
            "similarity": 1.0,
        }
        assert mgr.get(task.generation_id).status == GenerationStatus.CONFIRMED
        lines = [json.loads(line) for line in jsonl.read_text(encoding="utf-8").splitlines()]
        assert lines[-1] == {"displayName": "离心泵", "image": "assets/Agent/离心泵.png", "width": 128, "height": 128}
        assert "source" not in lines[-1]
        assert "similarity" not in lines[-1]
        controls = await db.search_by_name("离心泵")
        assert len(controls) == 1
        assert controls[0]["source"] == "ai-generated"
        assert controls[0]["width"] == 128 and controls[0]["height"] == 128
        results = await db.list_query_results()
        assert len(results) == 1
        assert results[0]["displayName"] == "离心泵"
        assert results[0]["query"] == "我的查询"
        assert results[0]["similarity"] == 1.0
        assert results[0]["source"] == "ai-generated"

        fake = FakeAsyncClient([make_fake_completion('{"controls": ["离心泵"]}')])
        agent = ControlAgent(manager=catalog, client=fake, model="test-model")
        await agent.init()
        result = await agent.process_query("离心泵")
        assert result.missed == []
        assert result.keywords[0].candidates[0].displayName == "离心泵"
        assert result.keywords[0].candidates[0].source == "exact"
        assert result.keywords[0].candidates[0].image == "assets/Agent/离心泵.png"
    finally:
        await mgr.stop()
        catalog.close()
        await db.close()


@pytest.mark.asyncio
async def test_confirmed_control_survives_restart(tmp_path):
    jsonl, mappings, catalog, db = await _make_env(tmp_path)
    uploader = FakeUploader()
    mgr = _make_manager(tmp_path, catalog, db, uploader=uploader)
    mgr.start()
    try:
        task = mgr.create("q", "冷却塔")
        await _wait_status(mgr, task.generation_id, GenerationStatus.READY)
        await mgr.confirm(task.generation_id)
    finally:
        await mgr.stop()
        catalog.close()
        await db.close()

    catalog2 = ControlCatalogManager(
        chroma_dir=str(tmp_path / "chroma"),
        control_jsonl_path=str(jsonl),
        mappings_path=str(mappings),
        embedding_function=FakeEmbedding(),
    )
    db2 = MaterialDB(db_path=str(tmp_path / "material.db"))
    await db2.init_db()
    try:
        fake = FakeAsyncClient([make_fake_completion('{"controls": ["冷却塔"]}')])
        agent = ControlAgent(manager=catalog2, client=fake, model="test-model")
        await agent.init()
        result = await agent.process_query("冷却塔")
        assert result.missed == []
        assert result.keywords[0].candidates[0].displayName == "冷却塔"
        assert await db2.search_by_name("冷却塔")
        results = await db2.list_query_results()
        assert any(r["displayName"] == "冷却塔" for r in results)
    finally:
        catalog2.close()
        await db2.close()


@pytest.mark.asyncio
async def test_duplicate_and_concurrent_same_name_confirm_conflicts(tmp_path):
    jsonl, mappings, catalog, db = await _make_env(tmp_path)
    uploader = FakeUploader()
    mgr = _make_manager(tmp_path, catalog, db, uploader=uploader)
    mgr.start()
    try:
        task = mgr.create("q", "新控件")
        await _wait_status(mgr, task.generation_id, GenerationStatus.READY)
        await mgr.confirm(task.generation_id)
        with pytest.raises(GenerationAPIError) as exc:
            await mgr.confirm(task.generation_id)
        assert exc.value.status_code == 409
    finally:
        await mgr.stop()
        catalog.close()
        await db.close()


@pytest.mark.asyncio
async def test_existing_directory_same_name_rejected_on_confirm(tmp_path):
    jsonl, mappings, catalog, db = await _make_env(tmp_path)
    uploader = FakeUploader()
    mgr = _make_manager(tmp_path, catalog, db, uploader=uploader)
    mgr.start()
    try:
        task = mgr.create("q", "新控件")
        await _wait_status(mgr, task.generation_id, GenerationStatus.READY)
        jsonl.write_text(
            json.dumps({"displayName": "新控件", "image": "s/n.png", "width": 10, "height": 10}, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        with pytest.raises(GenerationAPIError) as exc:
            await mgr.confirm(task.generation_id)
        assert exc.value.status_code == 409
        assert exc.value.code == "conflict"
    finally:
        await mgr.stop()
        catalog.close()
        await db.close()


@pytest.mark.asyncio
async def test_confirmed_task_cannot_be_discarded(tmp_path):
    jsonl, mappings, catalog, db = await _make_env(tmp_path)
    uploader = FakeUploader()
    mgr = _make_manager(tmp_path, catalog, db, uploader=uploader)
    mgr.start()
    try:
        task = mgr.create("q", "新控件")
        await _wait_status(mgr, task.generation_id, GenerationStatus.READY)
        await mgr.confirm(task.generation_id)
        with pytest.raises(GenerationAPIError) as exc:
            mgr.discard(task.generation_id)
        assert exc.value.status_code == 409
    finally:
        await mgr.stop()
        catalog.close()
        await db.close()


@pytest.mark.asyncio
async def test_discard_deletes_preview(tmp_path):
    jsonl, mappings, catalog, db = await _make_env(tmp_path)
    mgr = _make_manager(tmp_path, catalog, db, generator=FakeGenerator())
    mgr.start()
    try:
        task = mgr.create("q", "新控件")
        await _wait_status(mgr, task.generation_id, GenerationStatus.READY)
        preview = mgr.get(task.generation_id).preview_path
        mgr.discard(task.generation_id)
        assert not preview.exists()
        assert mgr.get(task.generation_id).status == GenerationStatus.DISCARDED
    finally:
        await mgr.stop()
        catalog.close()
        await db.close()


@pytest.mark.asyncio
async def test_start_cleans_previous_run_temp_files(tmp_path):
    jsonl, mappings, catalog, db = await _make_env(tmp_path)
    (tmp_path / "gen").mkdir(parents=True, exist_ok=True)
    (tmp_path / "gen" / "stale.png").write_bytes(b"old")
    mgr = _make_manager(tmp_path, catalog, db, generator=FakeGenerator())
    mgr.start()
    try:
        assert not (tmp_path / "gen" / "stale.png").exists()
    finally:
        await mgr.stop()
        catalog.close()
        await db.close()


@pytest.mark.asyncio
async def test_generation_survives_no_preview_before_ready(tmp_path):
    jsonl, mappings, catalog, db = await _make_env(tmp_path)
    mgr = _make_manager(tmp_path, catalog, db, generator=FakeGenerator(delay=0.2))
    mgr.start()
    try:
        task = mgr.create("q", "新控件")
        with pytest.raises(GenerationAPIError) as exc:
            mgr.get_preview_path(task.generation_id)
        assert exc.value.status_code == 409
        assert exc.value.code == "not_ready"
    finally:
        await mgr.stop()
        catalog.close()
        await db.close()
