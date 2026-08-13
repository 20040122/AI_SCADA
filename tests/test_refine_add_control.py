from __future__ import annotations

from typing import Any, Optional

import pytest

from model.layout_agent import LayoutAgent
from model.layout_tools.get_intent import (
    DeviceNode,
    LayoutFile,
    LayoutGroup,
    LayoutIntent,
    LayoutUnit,
)
from model.refine_agent import RefineAgent, RefineInputError
from tests.conftest import FakeAsyncClient, make_fake_completion

MATERIALS = [
    {"displayName": "状态面板", "image": "symbols/panel.json", "width": 162, "height": 60},
]


def _json(
    anchor_x: float = 960,
    anchor_y: float = 540,
    anchor_w: float = 120,
    anchor_h: float = 44.44,
    snapshot: bool = True,
    extra: Optional[list[dict]] = None,
    canvas_w: int = 1920,
    canvas_h: int = 1080,
) -> dict:
    entries = [
        {
            "c": "ht.Node",
            "i": 20399,
            "a": {
                "layout.node": True,
                "layout.group": "g1",
                "layout.instance": 1,
                "layout.sourceWidth": 162,
                "layout.sourceHeight": 60,
            },
            "p": {
                "displayName": "状态面板",
                "image": "symbols/panel.json",
                "position": {"x": anchor_x, "y": anchor_y},
                "width": anchor_w,
                "height": anchor_h,
            },
        }
    ]
    if extra:
        entries.extend(extra)
    attributes: dict[str, Any] = {"width": canvas_w, "height": canvas_h}
    if snapshot:
        attributes["layout.materials"] = [dict(m) for m in MATERIALS]
    return {"a": attributes, "d": entries}


def _control(node_i: int, name: str, x: float, y: float, w: float, h: float) -> dict:
    return {
        "c": "ht.Node",
        "i": node_i,
        "a": {"layout.node": True},
        "p": {
            "displayName": name,
            "image": "symbols/x.png",
            "position": {"x": x, "y": y},
            "width": w,
            "height": h,
        },
    }


async def _refine(
    actions_json: str, json_data: dict, selected: list[int]
):
    fake = FakeAsyncClient(
        [make_fake_completion('{"actions": ' + actions_json + ', "message": "ok"}')]
    )
    agent = RefineAgent(client=fake)
    return await agent.refine("添加控件", json_data, selected_node_ids=selected)


def _added(patch: list[dict]) -> list[dict]:
    return [op["value"] for op in patch if op.get("path") == "/d/-"]


def _content_rect_ops(patch: list[dict]) -> list[dict]:
    return [op for op in patch if op.get("path") == "/contentRect"]


@pytest.mark.asyncio
async def test_left_add_creates_one_node_with_geometry():
    result = await _refine(
        '[{"type":"add_control","target_ids":[20399],"material_candidates":["状态面板"],"sides":["left"]}]',
        _json(),
        [20399],
    )
    nodes = _added(result.patch)
    assert len(nodes) == 1
    node = nodes[0]
    assert node["c"] == "ht.Node"
    assert node["p"]["position"]["x"] == 800
    assert node["p"]["position"]["y"] == 540
    assert node["p"]["width"] == 120
    assert node["p"]["height"] == 44.44
    assert "缩放 100%" in result.message
    assert "左侧" in result.message
    assert "状态面板" in result.message


@pytest.mark.asyncio
async def test_left_add_keeps_40px_gap_to_anchor():
    result = await _refine(
        '[{"type":"add_control","target_ids":[20399],"material_candidates":["状态面板"],"sides":["left"]}]',
        _json(),
        [20399],
    )
    node = _added(result.patch)[0]
    anchor_left = 960 - 60
    new_right = node["p"]["position"]["x"] + node["p"]["width"] / 2
    assert abs((anchor_left - new_right) - 40) <= 0.02


@pytest.mark.asyncio
async def test_left_right_adds_two_same_size_nodes():
    result = await _refine(
        '[{"type":"add_control","target_ids":[20399],"material_candidates":["状态面板"],"sides":["left","right"]}]',
        _json(),
        [20399],
    )
    nodes = _added(result.patch)
    assert len(nodes) == 2
    assert nodes[0]["p"]["width"] == nodes[1]["p"]["width"]
    assert nodes[0]["p"]["height"] == nodes[1]["p"]["height"]
    assert nodes[0]["p"]["position"]["x"] == 800
    assert nodes[1]["p"]["position"]["x"] == 1120
    assert nodes[0]["p"]["position"]["y"] == 540
    assert "左右两侧" in result.message


@pytest.mark.asyncio
async def test_top_bottom_adds_two_nodes():
    result = await _refine(
        '[{"type":"add_control","target_ids":[20399],"material_candidates":["状态面板"],"sides":["top","bottom"]}]',
        _json(),
        [20399],
    )
    nodes = _added(result.patch)
    assert len(nodes) == 2
    assert nodes[0]["p"]["position"]["x"] == 960
    assert nodes[1]["p"]["position"]["x"] == 960
    assert nodes[0]["p"]["position"]["y"] < 540
    assert nodes[1]["p"]["position"]["y"] > 540
    assert "上下两侧" in result.message


@pytest.mark.asyncio
async def test_scale_down_when_obstacle_blocks():
    obstacle = _control(20400, "阀门", 720, 540, 60, 60)
    result = await _refine(
        '[{"type":"add_control","target_ids":[20399],"material_candidates":["状态面板"],"sides":["left"]}]',
        _json(extra=[obstacle]),
        [20399],
    )
    node = _added(result.patch)[0]
    assert node["p"]["width"] == 69.6
    assert node["p"]["height"] == 25.78
    assert "缩放 58%" in result.message


@pytest.mark.asyncio
async def test_obstacle_gap_at_least_40px():
    obstacle = _control(20400, "阀门", 720, 540, 60, 60)
    result = await _refine(
        '[{"type":"add_control","target_ids":[20399],"material_candidates":["状态面板"],"sides":["left"]}]',
        _json(extra=[obstacle]),
        [20399],
    )
    node = _added(result.patch)[0]
    new_left = node["p"]["position"]["x"] - node["p"]["width"] / 2
    obstacle_right = 720 + 30
    assert new_left - obstacle_right >= 40 - 0.02


@pytest.mark.asyncio
async def test_pair_uses_unified_smaller_scale():
    obstacle = _control(20400, "阀门", 1200, 540, 60, 60)
    result = await _refine(
        '[{"type":"add_control","target_ids":[20399],"material_candidates":["状态面板"],"sides":["left","right"]}]',
        _json(extra=[obstacle]),
        [20399],
    )
    nodes = _added(result.patch)
    assert len(nodes) == 2
    assert nodes[0]["p"]["width"] == nodes[1]["p"]["width"]
    assert nodes[0]["p"]["width"] == 69.6
    assert "缩放 58%" in result.message


@pytest.mark.asyncio
async def test_below_50_percent_rejected():
    obstacle = _control(20400, "阀门", 820, 540, 60, 60)
    result = await _refine(
        '[{"type":"add_control","target_ids":[20399],"material_candidates":["状态面板"],"sides":["left"]}]',
        _json(extra=[obstacle]),
        [20399],
    )
    assert result.patch == []
    assert "没有足够的空间" in result.message


@pytest.mark.asyncio
async def test_unique_display_name_when_occupied():
    result = await _refine(
        '[{"type":"add_control","target_ids":[20399],"material_candidates":["状态面板"],"sides":["left"]}]',
        _json(),
        [20399],
    )
    node = _added(result.patch)[0]
    assert node["p"]["displayName"] == "状态面板2"


@pytest.mark.asyncio
async def test_pair_names_assigned_left_to_right():
    result = await _refine(
        '[{"type":"add_control","target_ids":[20399],"material_candidates":["状态面板"],"sides":["left","right"]}]',
        _json(),
        [20399],
    )
    nodes = _added(result.patch)
    assert nodes[0]["p"]["displayName"] == "状态面板2"
    assert nodes[1]["p"]["displayName"] == "状态面板3"
    assert nodes[0]["i"] == 20400
    assert nodes[1]["i"] == 20401


@pytest.mark.asyncio
async def test_ambiguous_candidates_rejected():
    result = await _refine(
        '[{"type":"add_control","target_ids":[20399],"material_candidates":["状态面板","阀门"],"sides":["left"]}]',
        _json(),
        [20399],
    )
    assert result.patch == []
    assert "歧义" in result.message
    assert "状态面板" in result.message
    assert "阀门" in result.message


@pytest.mark.asyncio
async def test_material_not_in_snapshot_rejected():
    result = await _refine(
        '[{"type":"add_control","target_ids":[20399],"material_candidates":["水泵"],"sides":["left"]}]',
        _json(),
        [20399],
    )
    assert result.patch == []
    assert "不在该画布的素材快照中" in result.message


@pytest.mark.asyncio
async def test_missing_snapshot_rejected():
    result = await _refine(
        '[{"type":"add_control","target_ids":[20399],"material_candidates":["状态面板"],"sides":["left"]}]',
        _json(snapshot=False),
        [20399],
    )
    assert result.patch == []
    assert "缺少素材快照" in result.message


@pytest.mark.asyncio
async def test_no_selection_rejected():
    result = await _refine(
        '[{"type":"add_control","target_ids":[20399],"material_candidates":["状态面板"],"sides":["left"]}]',
        _json(),
        [],
    )
    assert result.patch == []
    assert "单选" in result.message


@pytest.mark.asyncio
async def test_multi_selection_rejected():
    extra = [_control(20400, "阀门", 300, 300, 60, 60)]
    result = await _refine(
        '[{"type":"add_control","target_ids":[20399],"material_candidates":["状态面板"],"sides":["left"]}]',
        _json(extra=extra),
        [20399, 20400],
    )
    assert result.patch == []
    assert "单选" in result.message


@pytest.mark.asyncio
async def test_target_mismatch_rejected():
    extra = [_control(20400, "阀门", 300, 300, 60, 60)]
    result = await _refine(
        '[{"type":"add_control","target_ids":[20400],"material_candidates":["状态面板"],"sides":["left"]}]',
        _json(extra=extra),
        [20399],
    )
    assert result.patch == []
    assert "不能通过文字点名" in result.message


@pytest.mark.asyncio
async def test_missing_sides_rejected():
    result = await _refine(
        '[{"type":"add_control","target_ids":[20399],"material_candidates":["状态面板"]}]',
        _json(),
        [20399],
    )
    assert result.patch == []
    assert "缺少放置方位" in result.message


@pytest.mark.asyncio
async def test_invalid_sides_rejected():
    result = await _refine(
        '[{"type":"add_control","target_ids":[20399],"material_candidates":["状态面板"],"sides":["left","top"]}]',
        _json(),
        [20399],
    )
    assert result.patch == []
    assert "成对" in result.message


@pytest.mark.asyncio
async def test_mixed_actions_rejected():
    result = await _refine(
        '[{"type":"add_control","target_ids":[20399],"material_candidates":["状态面板"],"sides":["left"]},{"type":"move","target_ids":[20399],"dx":10}]',
        _json(),
        [20399],
    )
    assert result.patch == []
    assert "独占" in result.message


@pytest.mark.asyncio
async def test_new_node_metadata_matches_layout_nodes():
    result = await _refine(
        '[{"type":"add_control","target_ids":[20399],"material_candidates":["状态面板"],"sides":["left"]}]',
        _json(),
        [20399],
    )
    node = _added(result.patch)[0]
    assert node["a"]["layout.node"] == "refine_20400"
    assert node["a"]["layout.group"] == "g1"
    assert node["a"]["layout.instance"] == 1
    assert node["a"]["layout.materialName"] == "状态面板"
    assert node["a"]["layout.sourceWidth"] == 162
    assert node["a"]["layout.sourceHeight"] == 60
    assert "panel.list" not in node
    assert "panel" not in node.get("p", {})
    assert "s" not in node


@pytest.mark.asyncio
async def test_group_instance_fallback_when_anchor_missing():
    jd = _json()
    jd["d"][0]["a"] = {"layout.node": True}
    result = await _refine(
        '[{"type":"add_control","target_ids":[20399],"material_candidates":["状态面板"],"sides":["left"]}]',
        jd,
        [20399],
    )
    node = _added(result.patch)[0]
    assert node["a"]["layout.group"] == "refine_group_20399"
    assert node["a"]["layout.instance"] == 1


@pytest.mark.asyncio
async def test_content_rect_replaced():
    jd = _json()
    jd["contentRect"] = {"x": 0, "y": 0, "width": 100, "height": 100}
    result = await _refine(
        '[{"type":"add_control","target_ids":[20399],"material_candidates":["状态面板"],"sides":["left"]}]',
        jd,
        [20399],
    )
    ops = _content_rect_ops(result.patch)
    assert len(ops) == 1
    assert ops[0]["op"] == "replace"
    assert ops[0]["value"]["width"] == 280
    assert ops[0]["value"]["x"] == 740
    assert ops[0]["value"]["y"] == round(540 - 44.44 / 2, 5)


@pytest.mark.asyncio
async def test_content_rect_added_when_missing():
    result = await _refine(
        '[{"type":"add_control","target_ids":[20399],"material_candidates":["状态面板"],"sides":["left"]}]',
        _json(),
        [20399],
    )
    ops = _content_rect_ops(result.patch)
    assert len(ops) == 1
    assert ops[0]["op"] == "add"


@pytest.mark.asyncio
async def test_snapshot_structure_invalid_raises():
    jd = _json()
    jd["a"]["layout.materials"] = "not-a-list"
    with pytest.raises(RefineInputError):
        await _refine(
            '[{"type":"add_control","target_ids":[20399],"material_candidates":["状态面板"],"sides":["left"]}]',
            jd,
            [20399],
        )


@pytest.mark.asyncio
async def test_snapshot_entry_invalid_raises():
    jd = _json()
    jd["a"]["layout.materials"] = [{"image": "x.png"}]
    with pytest.raises(RefineInputError):
        await _refine(
            '[{"type":"add_control","target_ids":[20399],"material_candidates":["状态面板"],"sides":["left"]}]',
            jd,
            [20399],
        )


@pytest.mark.asyncio
async def test_move_still_works_without_snapshot():
    fake = FakeAsyncClient(
        [make_fake_completion(
            '{"actions": [{"type":"move","target_ids":[20399],"dx":10}], "message": "ok"}'
        )]
    )
    agent = RefineAgent(client=fake)
    result = await agent.refine(
        "移动", _json(snapshot=False), selected_node_ids=[20399]
    )
    assert any(op["path"] == "/d/0/p/position/x" for op in result.patch)


@pytest.mark.asyncio
async def test_material_candidates_not_array_is_model_error():
    from model.refine_agent import RefineModelError

    fake = FakeAsyncClient(
        [make_fake_completion(
            '{"actions": [{"type":"add_control","target_ids":[20399],"material_candidates":"状态面板","sides":["left"]}], "message": "ok"}'
        )]
    )
    agent = RefineAgent(client=fake)
    with pytest.raises(RefineModelError):
        await agent.refine("添加", _json(), selected_node_ids=[20399])


@pytest.mark.asyncio
async def test_material_candidates_over_five_is_model_error():
    from model.refine_agent import RefineModelError

    fake = FakeAsyncClient(
        [make_fake_completion(
            '{"actions": [{"type":"add_control","target_ids":[20399],"material_candidates":["a","b","c","d","e","f"],"sides":["left"]}], "message": "ok"}'
        )]
    )
    agent = RefineAgent(client=fake)
    with pytest.raises(RefineModelError):
        await agent.refine("添加", _json(), selected_node_ids=[20399])


@pytest.mark.asyncio
async def test_sides_not_array_is_model_error():
    from model.refine_agent import RefineModelError

    fake = FakeAsyncClient(
        [make_fake_completion(
            '{"actions": [{"type":"add_control","target_ids":[20399],"material_candidates":["状态面板"],"sides":123}], "message": "ok"}'
        )]
    )
    agent = RefineAgent(client=fake)
    with pytest.raises(RefineModelError):
        await agent.refine("添加", _json(), selected_node_ids=[20399])


@pytest.mark.asyncio
async def test_sides_string_accepted_as_single_side():
    result = await _refine(
        '[{"type":"add_control","target_ids":[20399],"material_candidates":["状态面板"],"sides":"right"}]',
        _json(),
        [20399],
    )
    node = _added(result.patch)[0]
    assert node["p"]["position"]["x"] == 1120
    assert node["p"]["position"]["y"] == 540
    assert "右侧" in result.message


@pytest.mark.asyncio
async def test_top_add_respects_title_safe_zone():
    result = await _refine(
        '[{"type":"add_control","target_ids":[20399],"material_candidates":["状态面板"],"sides":["top"]}]',
        _json(),
        [20399],
    )
    node = _added(result.patch)[0]
    node_top = node["p"]["position"]["y"] - node["p"]["height"] / 2
    assert node_top >= 115 - 0.02


@pytest.mark.asyncio
async def test_left_add_respects_side_safe_zone():
    result = await _refine(
        '[{"type":"add_control","target_ids":[20399],"material_candidates":["状态面板"],"sides":["left"]}]',
        _json(),
        [20399],
    )
    node = _added(result.patch)[0]
    node_left = node["p"]["position"]["x"] - node["p"]["width"] / 2
    assert node_left >= 58 - 0.02


@pytest.mark.asyncio
async def test_rounding_keeps_gap_valid():
    jd = _json(anchor_x=960, anchor_y=540)
    jd["d"][0]["p"]["width"] = 120.005
    jd["d"][0]["p"]["height"] = 44.44
    result = await _refine(
        '[{"type":"add_control","target_ids":[20399],"material_candidates":["状态面板"],"sides":["left"]}]',
        jd,
        [20399],
    )
    node = _added(result.patch)[0]
    anchor_left = 960 - 120.005 / 2
    new_right = node["p"]["position"]["x"] + node["p"]["width"] / 2
    assert abs((anchor_left - new_right) - 40) <= 0.02


class FakeDB:
    def __init__(self, rows: list[dict]):
        self._rows = rows

    async def list_query_results(self, query: str = "") -> list[dict]:
        return self._rows


def _layout_file() -> LayoutFile:
    return LayoutFile(
        layoutIntent=LayoutIntent(
            groups=[
                LayoutGroup(
                    id="g1",
                    region="center",
                    count=1,
                    unit=LayoutUnit(root=DeviceNode(id="r", deviceType="泵")),
                )
            ]
        )
    )


@pytest.mark.asyncio
async def test_layout_generate_writes_material_snapshot(monkeypatch, tmp_path):
    rows = [
        {"displayName": "状态面板", "image": "symbols/panel.json", "width": 162, "height": 60},
        {"displayName": "状态面板", "image": "symbols/panel2.json", "width": 100, "height": 50},
        {"displayName": "阀门", "image": "symbols/valve.json", "width": 64, "height": 64},
    ]

    async def fake_intent(query, materials, client, model):
        return _layout_file()

    def fake_convert(data, controls, width, height):
        return [
            {
                "c": "ht.Node",
                "i": 1,
                "p": {
                    "displayName": "泵",
                    "image": "symbols/pump.json",
                    "position": {"x": 300, "y": 300},
                    "width": 100,
                    "height": 50,
                },
                "a": {"layout.node": True},
            }
        ]

    async def fake_connections(query, nodes, client, model, ir_data):
        return None

    async def fake_schema_validate(json_data):
        return []

    monkeypatch.setattr(
        "model.layout_tools.get_intent.generate_intent", fake_intent
    )
    monkeypatch.setattr(
        "model.layout_tools.compute_position.convert_layout_file", fake_convert
    )
    monkeypatch.setattr(
        "model.layout_tools.get_connection.generate_connections", fake_connections
    )
    monkeypatch.setattr("model.layout_agent._schema_validate", fake_schema_validate)
    monkeypatch.setattr("model.layout_agent.LAYOUT_DIR", tmp_path)

    agent = LayoutAgent(db=FakeDB(rows), client=FakeAsyncClient(), model="test")
    canvas = {"a": {"width": 1920, "height": 1080}, "d": [], "contentRect": {"x": 0, "y": 0, "width": 0, "height": 0}}

    async def fake_create_canvas(title, width, height):
        return canvas

    agent.create_canvas = fake_create_canvas

    result = await agent.generate("测试", 1920, 1080, title="测试")
    snapshot = result.json_data["a"]["layout.materials"]
    assert [item["displayName"] for item in snapshot] == ["状态面板", "阀门"]
    assert snapshot[0]["image"] == "symbols/panel.json"
    assert snapshot[0]["width"] == 162
    assert snapshot[0]["height"] == 60
