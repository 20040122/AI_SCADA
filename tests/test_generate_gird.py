import json
from pathlib import Path

import pytest

from model.generate_gird import (
    Connection,
    Endpoint,
    LayoutFile,
    LayoutGroup,
    LayoutIntent,
    LayoutUnit,
    DeviceNode,
    AttachmentNode,
    validate_layout_file,
    _build_system_prompt,
)


def _make_group(
    gid="g1",
    region="left",
    root_id="root",
    root_type="水泵",
    attachments=None,
    count=1,
    arrangement=None,
    columns=None,
    rows=None,
    order=None,
):
    return LayoutGroup(
        id=gid,
        region=region,
        unit=LayoutUnit(root=DeviceNode(id=root_id, deviceType=root_type), attachments=attachments or []),
        count=count,
        arrangement=arrangement,
        columns=columns,
        rows=rows,
        order=order,
    )


def _make_file(groups, connections=None):
    return LayoutFile(layoutIntent=LayoutIntent(groups=groups, connections=connections or []))


def _errors(file):
    errs, _ = validate_layout_file(file)
    return errs


def _warns(file):
    _, ws = validate_layout_file(file)
    return ws


def test_backward_compat_existing_files():
    for p in ["layout/intent.json", "layout/ir.json"]:
        data = json.loads((Path(p)).read_text(encoding="utf-8"))
        lf = LayoutFile.model_validate(data)
        assert _errors(lf) == []


def test_grid_valid_columns_only():
    g = _make_group(count=12, arrangement="grid", columns=4)
    assert _errors(_make_file([g])) == []


def test_grid_valid_rows_only():
    g = _make_group(count=12, arrangement="grid", rows=3)
    assert _errors(_make_file([g])) == []


def test_grid_valid_rows_and_columns_exact():
    g = _make_group(count=12, arrangement="grid", columns=4, rows=3)
    assert _errors(_make_file([g])) == []


def test_grid_valid_rows_columns_extra_capacity():
    g = _make_group(count=10, arrangement="grid", columns=4, rows=3)
    assert _errors(_make_file([g])) == []


def test_grid_missing_both_columns_and_rows():
    g = _make_group(count=12, arrangement="grid")
    errs = _errors(_make_file([g]))
    assert any("columns" in e.path for e in errs)


def test_grid_capacity_insufficient():
    g = _make_group(count=13, arrangement="grid", columns=4, rows=3)
    errs = _errors(_make_file([g]))
    assert any("容量不足" in e.message for e in errs)


def test_grid_columns_zero():
    g = _make_group(count=12, arrangement="grid", columns=0)
    errs = _errors(_make_file([g]))
    assert any("columns" in e.path for e in errs)


def test_grid_rows_zero():
    g = _make_group(count=12, arrangement="grid", rows=0)
    errs = _errors(_make_file([g]))
    assert any("rows" in e.path for e in errs)


def test_non_grid_columns_warns():
    g = _make_group(count=2, arrangement="vertical", columns=4)
    ws = _warns(_make_file([g]))
    assert any("columns" in w for w in ws)


def test_non_grid_rows_warns():
    g = _make_group(count=2, arrangement="horizontal", rows=3)
    ws = _warns(_make_file([g]))
    assert any("rows" in w for w in ws)


def test_non_grid_order_warns():
    g = _make_group(count=2, arrangement="vertical", order="row-major")
    ws = _warns(_make_file([g]))
    assert any("order" in w for w in ws)


def test_grid_order_accepted():
    g = _make_group(count=12, arrangement="grid", columns=4, order="col-major")
    assert _errors(_make_file([g])) == []


def test_connection_valid_cross_group():
    g1 = _make_group(gid="ga", root_id="pump1")
    g2 = _make_group(gid="gb", root_id="tank1")
    conn = Connection(
        id="c1",
        source=Endpoint(group="ga", node="pump1"),
        target=Endpoint(group="gb", node="tank1"),
    )
    assert _errors(_make_file([g1, g2], [conn])) == []


def test_connection_with_port():
    g1 = _make_group(gid="ga", root_id="pump1")
    g2 = _make_group(gid="gb", root_id="tank1")
    conn = Connection(
        id="c1",
        source=Endpoint(group="ga", node="pump1", port="outlet"),
        target=Endpoint(group="gb", node="tank1", port="inlet"),
    )
    assert _errors(_make_file([g1, g2], [conn])) == []


def test_connection_to_attachment_node():
    g1 = _make_group(
        gid="ga",
        root_id="pump1",
        attachments=[AttachmentNode(id="valve", deviceType="阀门", relativeTo="pump1", side="top")],
    )
    g2 = _make_group(gid="gb", root_id="tank1")
    conn = Connection(
        id="c1",
        source=Endpoint(group="ga", node="valve"),
        target=Endpoint(group="gb", node="tank1"),
    )
    assert _errors(_make_file([g1, g2], [conn])) == []


def test_connection_duplicate_id():
    g1 = _make_group(gid="ga", root_id="pump1")
    g2 = _make_group(gid="gb", root_id="tank1")
    conn = Connection(
        id="c1",
        source=Endpoint(group="ga", node="pump1"),
        target=Endpoint(group="gb", node="tank1"),
    )
    errs = _errors(_make_file([g1, g2], [conn, conn]))
    assert any("connection id 重复" in e.message for e in errs)


def test_connection_unknown_group():
    g1 = _make_group(gid="ga", root_id="pump1")
    conn = Connection(
        id="c1",
        source=Endpoint(group="ga", node="pump1"),
        target=Endpoint(group="nope", node="tank1"),
    )
    errs = _errors(_make_file([g1], [conn]))
    assert any("不存在的 group" in e.message for e in errs)


def test_connection_unknown_node_in_group():
    g1 = _make_group(gid="ga", root_id="pump1")
    g2 = _make_group(gid="gb", root_id="tank1")
    conn = Connection(
        id="c1",
        source=Endpoint(group="ga", node="pump1"),
        target=Endpoint(group="gb", node="ghost"),
    )
    errs = _errors(_make_file([g1, g2], [conn]))
    assert any("不存在的节点" in e.message for e in errs)


def test_connection_same_group_cross_node():
    g1 = _make_group(
        gid="ga",
        root_id="pump1",
        attachments=[AttachmentNode(id="valve", deviceType="阀门", relativeTo="pump1", side="top")],
    )
    conn = Connection(
        id="c1",
        source=Endpoint(group="ga", node="pump1"),
        target=Endpoint(group="ga", node="valve"),
    )
    assert _errors(_make_file([g1], [conn])) == []


def test_empty_connections_ok():
    g = _make_group()
    assert _errors(_make_file([g], [])) == []


def test_arrangement_grid_literal_accepted_by_pydantic():
    g = _make_group(count=4, arrangement="grid", columns=2)
    assert g.arrangement == "grid"


def test_invalid_arrangement_rejected():
    with pytest.raises(Exception):
        LayoutGroup(
            id="g1",
            region="left",
            unit=LayoutUnit(root=DeviceNode(id="r", deviceType="x"), attachments=[]),
            count=1,
            arrangement="diagonal",
        )


def test_system_prompt_contains_new_schema():
    prompt = _build_system_prompt(["水泵", "阀门"], None)
    assert "Connection" in prompt
    assert "Endpoint" in prompt
    assert "grid" in prompt
    assert "columns" in prompt
    assert "rows" in prompt


def test_system_prompt_no_vocab_still_has_schema():
    prompt = _build_system_prompt([], None)
    assert "Connection" in prompt
    assert "grid" in prompt


def test_system_prompt_with_example():
    prompt = _build_system_prompt(["水泵"], '{"layoutIntent":{"groups":[]}}')
    assert "示例" in prompt


def test_model_dump_excludes_none():
    g = _make_group(count=1)
    dumped = g.model_dump(exclude_none=True)
    assert "columns" not in dumped
    assert "rows" not in dumped
    assert "order" not in dumped
    assert "arrangement" not in dumped


def test_layout_intent_default_connections_empty():
    li = LayoutIntent(groups=[_make_group()])
    assert li.connections == []
