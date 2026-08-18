from __future__ import annotations

import json

import pytest

from model.control_tools.catalog import (
    ControlCatalogManager,
    CatalogConfigError,
    load_canonical_controls,
    parse_mappings,
)
from tests.conftest import FakeEmbedding


def _write_jsonl(path, controls):
    path.write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in controls),
        encoding="utf-8",
    )


def _write_mappings(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_duplicate_display_name_last_entry_is_canonical(tmp_path):
    jsonl = tmp_path / "control.jsonl"
    _write_jsonl(jsonl, [
        {"displayName": "表格", "image": "symbols/ht/ui/table.json", "width": 100, "height": 50},
        {"displayName": "表格", "image": "symbols/ht/tables/table.json", "width": 420, "height": 300},
        {"displayName": "水泵", "image": "symbols/a/水泵.json", "width": 131, "height": 116},
    ])
    controls = load_canonical_controls(jsonl)
    names = [c["displayName"] for c in controls]
    assert names == ["表格", "水泵"]
    table = [c for c in controls if c["displayName"] == "表格"][0]
    assert table["image"] == "symbols/ht/tables/table.json"
    assert table["width"] == 420


def test_parse_mappings_accepts_valid_config(tmp_path):
    mappings = tmp_path / "m.json"
    _write_mappings(mappings, {
        "version": "1",
        "mappings": [
            {"term": "温度", "targets": ["仪表盘", "参数值"]},
            {"term": "压力", "targets": ["仪表盘", "参数值"]},
        ],
    })
    result = parse_mappings(mappings, ["仪表盘", "参数值", "水泵"])
    assert result == {
        "温度": ["仪表盘", "参数值"],
        "压力": ["仪表盘", "参数值"],
    }


def test_parse_mappings_duplicate_key_rejected(tmp_path):
    mappings = tmp_path / "m.json"
    _write_mappings(mappings, {
        "version": "1",
        "mappings": [
            {"term": "温度", "targets": ["仪表盘"]},
            {"term": "温度", "targets": ["参数值"]},
        ],
    })
    with pytest.raises(CatalogConfigError, match="重复映射键"):
        parse_mappings(mappings, ["仪表盘", "参数值"])


def test_parse_mappings_empty_targets_rejected(tmp_path):
    mappings = tmp_path / "m.json"
    _write_mappings(mappings, {
        "version": "1",
        "mappings": [{"term": "温度", "targets": []}],
    })
    with pytest.raises(CatalogConfigError, match="不能为空"):
        parse_mappings(mappings, ["仪表盘", "参数值"])


def test_parse_mappings_missing_term_rejected(tmp_path):
    mappings = tmp_path / "m.json"
    _write_mappings(mappings, {
        "version": "1",
        "mappings": [{"term": "", "targets": ["仪表盘"]}],
    })
    with pytest.raises(CatalogConfigError, match="非空 term"):
        parse_mappings(mappings, ["仪表盘", "参数值"])


def test_parse_mappings_over_five_targets_rejected(tmp_path):
    mappings = tmp_path / "m.json"
    _write_mappings(mappings, {
        "version": "1",
        "mappings": [{"term": "温度", "targets": ["a", "b", "c", "d", "e", "f"]}],
    })
    with pytest.raises(CatalogConfigError, match="超过 5 个"):
        parse_mappings(mappings, ["a", "b", "c", "d", "e", "f"])


def test_parse_mappings_unknown_target_rejected(tmp_path):
    mappings = tmp_path / "m.json"
    _write_mappings(mappings, {
        "version": "1",
        "mappings": [{"term": "温度", "targets": ["仪表盘", "不存在"]}],
    })
    with pytest.raises(CatalogConfigError, match="未知目标"):
        parse_mappings(mappings, ["仪表盘", "参数值"])


def test_parse_mappings_duplicate_targets_rejected(tmp_path):
    mappings = tmp_path / "m.json"
    _write_mappings(mappings, {
        "version": "1",
        "mappings": [{"term": "温度", "targets": ["仪表盘", "仪表盘"]}],
    })
    with pytest.raises(CatalogConfigError, match="必须唯一"):
        parse_mappings(mappings, ["仪表盘", "参数值"])


def test_parse_mappings_key_conflicts_with_control_name_rejected(tmp_path):
    mappings = tmp_path / "m.json"
    _write_mappings(mappings, {
        "version": "1",
        "mappings": [{"term": "水泵", "targets": ["仪表盘"]}],
    })
    with pytest.raises(CatalogConfigError, match="与控件名冲突"):
        parse_mappings(mappings, ["仪表盘", "水泵"])


def test_parse_mappings_missing_version_rejected(tmp_path):
    mappings = tmp_path / "m.json"
    _write_mappings(mappings, {"mappings": [{"term": "温度", "targets": ["仪表盘"]}]})
    with pytest.raises(CatalogConfigError, match="version"):
        parse_mappings(mappings, ["仪表盘", "参数值"])


def test_parse_mappings_non_array_rejected(tmp_path):
    mappings = tmp_path / "m.json"
    _write_mappings(mappings, {"version": "1", "mappings": "温度"})
    with pytest.raises(CatalogConfigError, match="数组"):
        parse_mappings(mappings, ["仪表盘", "参数值"])


def test_load_initial_invalid_mapping_fails_startup(tmp_path):
    jsonl = tmp_path / "control.jsonl"
    _write_jsonl(jsonl, [
        {"displayName": "仪表盘", "image": "symbols/a/仪表盘.json", "width": 200, "height": 200},
    ])
    mappings = tmp_path / "control_mappings.json"
    _write_mappings(mappings, {
        "version": "1",
        "mappings": [{"term": "温度", "targets": ["未知控件"]}],
    })
    manager = ControlCatalogManager(
        chroma_dir=str(tmp_path / "chroma"),
        control_jsonl_path=str(jsonl),
        mappings_path=str(mappings),
        embedding_function=FakeEmbedding(),
    )
    try:
        with pytest.raises(CatalogConfigError):
            manager.load_initial()
    finally:
        manager.close()


def test_load_initial_invalid_jsonl_fails_startup(tmp_path):
    jsonl = tmp_path / "control.jsonl"
    jsonl.write_text("not json", encoding="utf-8")
    mappings = tmp_path / "control_mappings.json"
    _write_mappings(mappings, {"version": "1", "mappings": []})
    manager = ControlCatalogManager(
        chroma_dir=str(tmp_path / "chroma"),
        control_jsonl_path=str(jsonl),
        mappings_path=str(mappings),
        embedding_function=FakeEmbedding(),
    )
    try:
        with pytest.raises(Exception):
            manager.load_initial()
    finally:
        manager.close()
