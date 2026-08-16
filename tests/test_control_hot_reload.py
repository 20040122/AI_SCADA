from __future__ import annotations

import asyncio
import hashlib
import json

import pytest

from model.control_tools.catalog import ControlCatalogManager
from tests.conftest import FakeEmbedding

BASE_CONTROLS = [
    {"displayName": "水泵", "image": "symbols/a/水泵.json", "width": 100, "height": 80},
    {"displayName": "仪表盘", "image": "symbols/a/仪表盘.json", "width": 200, "height": 200},
]

BASE_MAPPINGS = {
    "version": "1",
    "mappings": [
        {"term": "温度", "targets": ["仪表盘"]},
    ],
}


def _write_jsonl(path, controls):
    path.write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in controls),
        encoding="utf-8",
    )


def _write_mappings(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _append_control(path, control):
    with path.open("a", encoding="utf-8") as fh:
        fh.write("\n" + json.dumps(control, ensure_ascii=False) + "\n")


def _make_manager(tmp_path):
    jsonl = tmp_path / "control.jsonl"
    mappings = tmp_path / "control_mappings.json"
    _write_jsonl(jsonl, BASE_CONTROLS)
    _write_mappings(mappings, BASE_MAPPINGS)
    manager = ControlCatalogManager(
        chroma_dir=str(tmp_path / "chroma"),
        control_jsonl_path=str(jsonl),
        mappings_path=str(mappings),
        embedding_function=FakeEmbedding(),
    )
    return jsonl, mappings, manager


def _collection_exists(manager, name):
    try:
        manager._client.get_collection(name=name)
        return True
    except Exception:
        return False


@pytest.mark.asyncio
async def test_hot_reload_picks_up_new_control_and_retires_old(tmp_path):
    jsonl, _, manager = _make_manager(tmp_path)
    manager.load_initial()
    old = await manager.acquire()
    old_names = list(old.names)
    manager.release(old)
    _append_control(jsonl, {"displayName": "新设备", "image": "symbols/a/新设备.json", "width": 50, "height": 50})
    snap = await manager.acquire()
    try:
        assert "新设备" in snap.names
        assert snap is not old
        assert old.retired is True
        assert snap.collection.name != old.collection.name
        assert "新设备" not in old_names
        assert not _collection_exists(manager, old.collection.name)
    finally:
        manager.release(snap)
        manager.close()


@pytest.mark.asyncio
async def test_hot_reload_keeps_old_snapshot_on_invalid_jsonl(tmp_path):
    jsonl, _, manager = _make_manager(tmp_path)
    manager.load_initial()
    old = await manager.acquire()
    manager.release(old)
    jsonl.write_text("not json", encoding="utf-8")
    snap = await manager.acquire()
    try:
        assert snap is old
        assert snap.names == [c["displayName"] for c in BASE_CONTROLS]
    finally:
        manager.release(snap)
    _write_jsonl(jsonl, BASE_CONTROLS + [
        {"displayName": "新设备", "image": "symbols/a/新设备.json", "width": 50, "height": 50},
    ])
    snap2 = await manager.acquire()
    try:
        assert "新设备" in snap2.names
    finally:
        manager.release(snap2)
        manager.close()


@pytest.mark.asyncio
async def test_hot_reload_keeps_old_snapshot_on_invalid_mapping(tmp_path):
    _, mappings, manager = _make_manager(tmp_path)
    manager.load_initial()
    old = await manager.acquire()
    manager.release(old)
    _write_mappings(mappings, {
        "version": "1",
        "mappings": [{"term": "温度", "targets": ["不存在的控件"]}],
    })
    snap = await manager.acquire()
    try:
        assert snap is old
        assert "温度" in snap.mappings
    finally:
        manager.release(snap)
        manager.close()


@pytest.mark.asyncio
async def test_mapping_only_change_reuses_current_collection(tmp_path):
    _, mappings, manager = _make_manager(tmp_path)
    manager.load_initial()
    snap1 = await manager.acquire()
    collection1 = snap1.collection
    manager.release(snap1)
    _write_mappings(mappings, {
        "version": "1",
        "mappings": [
            {"term": "温度", "targets": ["仪表盘"]},
            {"term": "湿度", "targets": ["水泵"]},
        ],
    })
    snap2 = await manager.acquire()
    try:
        assert snap2.collection is collection1
        assert "湿度" in snap2.mappings
        assert snap2.mappings["湿度"] == ["水泵"]
        assert _collection_exists(manager, collection1.name)
    finally:
        manager.release(snap2)
        manager.close()


@pytest.mark.asyncio
async def test_retired_collection_cleaned_after_last_reader_releases(tmp_path):
    jsonl, _, manager = _make_manager(tmp_path)
    manager.load_initial()
    snap_a = await manager.acquire()
    _append_control(jsonl, {"displayName": "新设备", "image": "symbols/a/新设备.json", "width": 50, "height": 50})
    snap_b = await manager.acquire()
    try:
        assert snap_a.retired is True
        assert _collection_exists(manager, snap_a.collection.name)
    finally:
        manager.release(snap_b)
    assert _collection_exists(manager, snap_a.collection.name)
    manager.release(snap_a)
    assert not _collection_exists(manager, snap_a.collection.name)
    manager.close()


@pytest.mark.asyncio
async def test_concurrent_requests_see_complete_old_or_new_snapshot(tmp_path):
    jsonl, _, manager = _make_manager(tmp_path)
    manager.load_initial()
    snap_old = await manager.acquire()
    _append_control(jsonl, {"displayName": "新设备", "image": "symbols/a/新设备.json", "width": 50, "height": 50})
    snap_new = await manager.acquire()
    try:
        old_names = [meta["displayName"] for meta in snap_old.collection.get(include=["metadatas"])["metadatas"]]
        new_names = [meta["displayName"] for meta in snap_new.collection.get(include=["metadatas"])["metadatas"]]
        assert "新设备" not in old_names
        assert "新设备" in new_names
        assert snap_old.collection.count() == 2
        assert snap_new.collection.count() == 3
    finally:
        manager.release(snap_old)
        assert not _collection_exists(manager, snap_old.collection.name)
        manager.release(snap_new)
        manager.close()


@pytest.mark.asyncio
async def test_concurrent_acquire_returns_single_consistent_version(tmp_path):
    jsonl, _, manager = _make_manager(tmp_path)
    manager.load_initial()
    _append_control(jsonl, {"displayName": "新设备", "image": "symbols/a/新设备.json", "width": 50, "height": 50})
    snaps = await asyncio.gather(*[manager.acquire() for _ in range(4)])
    try:
        names_sets = [set(s.names) for s in snaps]
        assert all(names_sets[0] == names for names in names_sets)
        assert "新设备" in names_sets[0]
    finally:
        for snap in snaps:
            manager.release(snap)
        manager.close()


@pytest.mark.asyncio
async def test_versioned_collection_name_uses_control_hash(tmp_path):
    jsonl, _, manager = _make_manager(tmp_path)
    manager.load_initial()
    snap = await manager.acquire()
    try:
        expected = "control_chunks_v_" + hashlib.sha256(jsonl.read_bytes()).hexdigest()
        assert snap.collection.name == expected
    finally:
        manager.release(snap)
        manager.close()


@pytest.mark.asyncio
async def test_legacy_collection_is_not_deleted_by_manager(tmp_path):
    jsonl, _, manager = _make_manager(tmp_path)
    manager.load_initial()
    legacy = manager._client.create_collection(name="control_chunks", embedding_function=FakeEmbedding())
    legacy.upsert(ids=["old"], documents=["old doc"], metadatas=[{"displayName": "旧"}])
    old = await manager.acquire()
    manager.release(old)
    _append_control(jsonl, {"displayName": "新设备", "image": "symbols/a/新设备.json", "width": 50, "height": 50})
    snap = await manager.acquire()
    try:
        assert not _collection_exists(manager, old.collection.name)
        assert _collection_exists(manager, "control_chunks")
    finally:
        manager.release(snap)
        manager.close()
