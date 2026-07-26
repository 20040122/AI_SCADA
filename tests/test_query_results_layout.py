import json
import sqlite3

import pytest

from app.schemas import CanvasLayoutRequest
import data.sqlite.material_db as material_db_module
from data.sqlite.material_db import MaterialDB
from model.compute_position import MissingMaterialError, convert_layout_file
from model.generate_gird import LayoutFile, _load_vocab
from model.layout_agent import LayoutAgent


@pytest.mark.asyncio
async def test_query_results_db_initialization_does_not_seed_controls(tmp_path):
    db = MaterialDB(str(tmp_path / "material.db"))

    await db.init_query_results_db()
    await db.save_query_result("布局", [{"displayName": "水泵", "image": "pump.json"}])

    assert await db.list_query_results("")
    with pytest.raises(sqlite3.OperationalError, match="no such table: controls"):
        await db.list_all()
    await db.close()


@pytest.mark.asyncio
async def test_query_results_initialization_does_not_read_control_jsonl(tmp_path, monkeypatch):
    def fail_if_read():
        raise AssertionError("control.jsonl must not be read")

    class ForbiddenPath:
        def exists(self):
            return False

        def read_bytes(self):
            return fail_if_read()

    monkeypatch.setattr(material_db_module, "CONTROL_JSONL", ForbiddenPath())
    db = MaterialDB(str(tmp_path / "material.db"))

    await db.init_query_results_db()
    await db.close()


def test_load_vocab_uses_the_query_results_snapshot():
    materials = [
        {"displayName": "水泵"},
        {"displayName": "水泵"},
        {"displayName": "阀门"},
    ]

    assert _load_vocab(materials) == ["水泵", "阀门"]


def test_layout_rejects_device_type_without_query_result_material():
    layout = {
        "layoutIntent": {
            "groups": [
                {
                    "id": "pump-group",
                    "region": "center",
                    "count": 1,
                    "unit": {
                        "root": {"id": "pump", "deviceType": "水泵"},
                        "attachments": [],
                    },
                }
            ]
        }
    }

    with pytest.raises(ValueError, match="水泵"):
        convert_layout_file(layout, [{"displayName": "阀门", "image": "valve.json"}])


def test_layout_places_related_groups_in_separate_equal_height_columns():
    layout = {
        "layoutIntent": {
            "groups": [
                {
                    "id": "tower",
                    "region": "left",
                    "count": 3,
                    "arrangement": "vertical",
                    "unit": {"root": {"id": "root", "deviceType": "冷却塔"}},
                },
                {
                    "id": "cooling-pump",
                    "region": "center",
                    "relativeTo": "tower",
                    "side": "right",
                    "count": 3,
                    "arrangement": "vertical",
                    "unit": {"root": {"id": "root", "deviceType": "冷却泵"}},
                },
                {
                    "id": "chiller",
                    "region": "center",
                    "relativeTo": "cooling-pump",
                    "side": "right",
                    "count": 3,
                    "arrangement": "vertical",
                    "unit": {"root": {"id": "root", "deviceType": "冷水机"}},
                },
                {
                    "id": "freeze-pump",
                    "region": "right",
                    "relativeTo": "chiller",
                    "side": "right",
                    "count": 4,
                    "arrangement": "vertical",
                    "unit": {"root": {"id": "root", "deviceType": "冷冻泵"}},
                },
            ],
        }
    }
    controls = [
        {"displayName": name, "image": f"{name}.json", "width": 100, "height": 100}
        for name in ("冷却塔", "冷却泵", "冷水机", "冷冻泵")
    ]

    nodes = convert_layout_file(layout, controls)
    positions = {}
    for node in nodes:
        positions.setdefault(node["a"]["layout.group"], []).append(node["p"]["position"])

    columns = [positions[group_id] for group_id in ("tower", "cooling-pump", "chiller", "freeze-pump")]
    assert [column[0]["x"] for column in columns] == sorted(column[0]["x"] for column in columns)
    assert len({column[0]["x"] for column in columns}) == 4
    assert all(len({point["x"] for point in column}) == 1 for column in columns)
    assert all(column[0]["y"] < column[-1]["y"] for column in columns)
    assert [round((column[0]["y"] + column[-1]["y"]) / 2, 2) for column in columns] == [565.0] * 4
    assert all(
        len({round(column[index + 1]["y"] - column[index]["y"], 2) for index in range(len(column) - 1)}) == 1
        for column in columns
    )


def test_canvas_layout_request_rejects_controls_field():
    with pytest.raises(ValueError):
        CanvasLayoutRequest.model_validate({
            "query": "水泵",
            "title": "测试",
            "controls": [],
        })


@pytest.mark.asyncio
async def test_layout_agent_rejects_empty_query_results():
    class EmptyDB:
        async def list_query_results(self, query):
            return []

    with pytest.raises(MissingMaterialError, match="query_results 表为空"):
        await LayoutAgent(db=EmptyDB()).generate("水泵", 1920, 1080)


@pytest.mark.asyncio
async def test_layout_agent_writes_it_ir_unconditionally(monkeypatch):
    class DB:
        async def list_query_results(self, query):
            return [{"displayName": "水泵", "image": "pump.json"}]

    async def fake_generate_intent(prompt, materials, client, model):
        return LayoutFile.model_validate({
            "layoutIntent": {
                "groups": [{
                    "id": "pump-group",
                    "region": "center",
                    "count": 1,
                    "unit": {"root": {"id": "pump", "deviceType": "水泵"}},
                }]
            }
        })

    def fake_convert_layout_file(data, controls, width, height):
        return []

    async def fake_schema_validate(data):
        return []

    async def fake_create_canvas(self, title, width, height):
        return {"d": []}

    writes = {}

    writes = {}
    replaced = {}

    def fake_write_text(self, text, encoding):
        writes[self.name] = text
        assert encoding == "utf-8"
        return len(text)

    def fake_replace(self, target):
        replaced[target.name] = writes.pop(self.name, None)

    monkeypatch.setattr("model.generate_gird.generate_intent", fake_generate_intent)
    monkeypatch.setattr("model.compute_position.convert_layout_file", fake_convert_layout_file)
    monkeypatch.setattr("model.layout_agent._schema_validate", fake_schema_validate)
    monkeypatch.setattr("model.layout_agent.Path.write_text", fake_write_text)
    monkeypatch.setattr("model.layout_agent.Path.replace", fake_replace)
    monkeypatch.setattr(LayoutAgent, "create_canvas", fake_create_canvas)

    result = await LayoutAgent(db=DB(), client=object(), model="test-model").generate(
        "控件：1台水泵。\n流程：水泵。\n结构：水泵位于页面中部。\n管道：对齐。",
        1920,
        1080,
    )

    ir_writes = {p: c for p, c in replaced.items() if p.endswith("it_ir.json")}
    pt_writes = {p: c for p, c in replaced.items() if p.endswith("pt_ir.json")}
    assert len(ir_writes) == 1, f"expected it_ir.json, got: {list(replaced)}"
    assert len(pt_writes) == 1, f"expected pt_ir.json, got: {list(replaced)}"
    assert json.loads(list(ir_writes.values())[0]) == result.ir_data


def test_validate_selector_all():
    from model.get_connection import _validate_selector
    nodes = [
        {"a": {"layout.group": "g1", "layout.node": "n1", "layout.instance": 1}},
        {"a": {"layout.group": "g1", "layout.node": "n1", "layout.instance": 2}},
    ]
    assert _validate_selector("all", ("g1", "n1"), nodes) is None


def test_validate_selector_valid_array():
    from model.get_connection import _validate_selector
    nodes = [
        {"a": {"layout.group": "g1", "layout.node": "n1", "layout.instance": 1}},
        {"a": {"layout.group": "g1", "layout.node": "n1", "layout.instance": 2}},
    ]
    assert _validate_selector([1, 2], ("g1", "n1"), nodes) is None


def test_validate_selector_invalid_type():
    from model.get_connection import _validate_selector
    nodes = [
        {"a": {"layout.group": "g1", "layout.node": "n1", "layout.instance": 1}},
    ]
    assert _validate_selector("invalid", ("g1", "n1"), nodes) is not None
    assert _validate_selector(123, ("g1", "n1"), nodes) is not None


def test_validate_selector_empty_array():
    from model.get_connection import _validate_selector
    nodes = [
        {"a": {"layout.group": "g1", "layout.node": "n1", "layout.instance": 1}},
    ]
    err = _validate_selector([], ("g1", "n1"), nodes)
    assert err is not None
    assert "不能为空" in err


def test_validate_selector_duplicate():
    from model.get_connection import _validate_selector
    nodes = [
        {"a": {"layout.group": "g1", "layout.node": "n1", "layout.instance": 1}},
        {"a": {"layout.group": "g1", "layout.node": "n1", "layout.instance": 2}},
    ]
    err = _validate_selector([1, 1], ("g1", "n1"), nodes)
    assert err is not None
    assert "重复" in err


def test_validate_selector_nonexistent():
    from model.get_connection import _validate_selector
    nodes = [
        {"a": {"layout.group": "g1", "layout.node": "n1", "layout.instance": 1}},
    ]
    err = _validate_selector([999], ("g1", "n1"), nodes)
    assert err is not None
    assert "不存在" in err


def test_deduplicate_templates_removes_duplicates():
    from model.get_connection import ConnectionTemplate, TemplateEnd, _deduplicate_templates
    tmpl = ConnectionTemplate(
        source=TemplateEnd(group="g1", node="n1", port="right", selector="all"),
        target=TemplateEnd(group="g2", node="n2", port="left", selector="all"),
    )
    result = _deduplicate_templates([tmpl, tmpl])
    assert len(result) == 1


def test_expand_templates_single_instance():
    from model.get_connection import (
        ConnectionTemplate, TemplateEnd, _expand_templates,
    )
    tmpl = ConnectionTemplate(
        source=TemplateEnd(group="g1", node="n1", port="right", selector="all"),
        target=TemplateEnd(group="g2", node="n2", port="left", selector="all"),
    )
    instances = {("g1", "n1"): {1}, ("g2", "n2"): {1}}
    result = _expand_templates([tmpl], instances)
    assert len(result) == 1
    assert result[0].source.instance == 1
    assert result[0].target.instance == 1


def test_expand_templates_multi_instance_cartesian():
    from model.get_connection import (
        ConnectionTemplate, TemplateEnd, _expand_templates,
    )
    tmpl = ConnectionTemplate(
        source=TemplateEnd(group="g1", node="n1", port="right", selector="all"),
        target=TemplateEnd(group="g2", node="n2", port="left", selector="all"),
    )
    instances = {("g1", "n1"): {1, 2, 3}, ("g2", "n2"): {1, 2, 3}}
    result = _expand_templates([tmpl], instances)
    assert len(result) == 9


def test_expand_templates_with_selector_array():
    from model.get_connection import (
        ConnectionTemplate, TemplateEnd, _expand_templates,
    )
    tmpl = ConnectionTemplate(
        source=TemplateEnd(group="g1", node="n1", port="right", selector=[1, 2]),
        target=TemplateEnd(group="g2", node="n2", port="left", selector=[1]),
    )
    instances = {("g1", "n1"): {1, 2, 3}, ("g2", "n2"): {1, 2}}
    result = _expand_templates([tmpl], instances)
    assert len(result) == 2
    assert result[0].source.instance == 1
    assert result[0].target.instance == 1
    assert result[1].source.instance == 2
    assert result[1].target.instance == 1


def test_expand_templates_order():
    from model.get_connection import (
        ConnectionTemplate, TemplateEnd, _expand_templates,
    )
    tmpl = ConnectionTemplate(
        source=TemplateEnd(group="g1", node="n1", port="right", selector="all"),
        target=TemplateEnd(group="g2", node="n2", port="left", selector="all"),
    )
    instances = {("g1", "n1"): {3, 1, 2}, ("g2", "n2"): {3, 1, 2}}
    result = _expand_templates([tmpl], instances)
    assert [spec.id for spec in result] == ["pipe-1", "pipe-2", "pipe-3", "pipe-4", "pipe-5", "pipe-6", "pipe-7", "pipe-8", "pipe-9"]
    assert [(spec.source.instance, spec.target.instance) for spec in result] == [
        (1, 1), (1, 2), (1, 3),
        (2, 1), (2, 2), (2, 3),
        (3, 1), (3, 2), (3, 3),
    ]


def test_validate_connections_invalid_selector():
    from model.get_connection import _validate_connections
    nodes = [
        {"a": {"layout.group": "g1", "layout.node": "n1", "layout.instance": 1}},
    ]
    raw = [
        {"source": {"group": "g1", "node": "n1", "selector": [999], "port": "right"},
         "target": {"group": "g1", "node": "n1", "selector": "all", "port": "left"}},
    ]
    _, errors = _validate_connections(raw, nodes)
    assert errors


def test_integration_27_connections():
    from model.get_connection import (
        _validate_connections, _deduplicate_templates, _expand_templates, _group_instances,
    )
    nodes = []
    for group, node, count in [
        ("cooling-tower", "root", 3),
        ("cooling-pump", "root", 3),
        ("chiller", "root", 3),
        ("chilled-pump", "root", 4),
    ]:
        for i in range(1, count + 1):
            nodes.append({
                "a": {"layout.group": group, "layout.node": node, "layout.instance": i},
                "p": {"displayName": group, "position": {"x": 0, "y": 0}},
            })

    raw = [
        {"source": {"group": "cooling-tower", "node": "root", "selector": "all", "port": "right"},
         "target": {"group": "cooling-pump", "node": "root", "selector": "all", "port": "left"}},
        {"source": {"group": "cooling-pump", "node": "root", "selector": "all", "port": "right"},
         "target": {"group": "chiller", "node": "root", "selector": "all", "port": "left"}},
        {"source": {"group": "chiller", "node": "root", "selector": "all", "port": "right"},
         "target": {"group": "chilled-pump", "node": "root", "selector": [1, 2, 3], "port": "left"}},
    ]

    templates, errors = _validate_connections(raw, nodes)
    assert not errors, errors
    templates = _deduplicate_templates(templates)
    instances = _group_instances(nodes)
    expanded = _expand_templates(templates, instances)

    assert len(expanded) == 27
    assert expanded[0].id == "pipe-1"
    assert expanded[-1].id == "pipe-27"

    tower_pump = [c for c in expanded if c.source.group == "cooling-tower"]
    assert len(tower_pump) == 9
    assert all(t.source.instance in {1, 2, 3} for t in tower_pump)
    assert all(t.target.instance in {1, 2, 3} for t in tower_pump)

    pump_chiller = [c for c in expanded if c.source.group == "cooling-pump"]
    assert len(pump_chiller) == 9
    assert all(s.source.instance in {1, 2, 3} for s in pump_chiller)
    assert all(s.target.instance in {1, 2, 3} for s in pump_chiller)

    chiller_chilled = [c for c in expanded if c.source.group == "chiller"]
    assert len(chiller_chilled) == 9

    chilled_pump_4_connections = [c for c in expanded if c.target.group == "chilled-pump" and c.target.instance == 4]
    assert len(chilled_pump_4_connections) == 0


def test_deduplicate_specs_keeps_different_selectors():
    from model.get_connection import (
        ConnectionTemplate, TemplateEnd, _expand_templates, _deduplicate_specs,
    )
    instances = {
        ("g2", "n2"): {1, 2},
        ("g2", "n2_v"): {1, 2},
        ("g2", "n2_f"): {1, 2},
        ("g2", "n2_p"): {1, 2},
    }

    templates = [
        ConnectionTemplate(
            source=TemplateEnd(group="g2", node="n2", port="right", selector=[1]),
            target=TemplateEnd(group="g2", node="n2_v", port="left", selector=[1]),
        ),
        ConnectionTemplate(
            source=TemplateEnd(group="g2", node="n2", port="right", selector=[2]),
            target=TemplateEnd(group="g2", node="n2_v", port="left", selector=[2]),
        ),
        ConnectionTemplate(
            source=TemplateEnd(group="g2", node="n2_v", port="right", selector=[1]),
            target=TemplateEnd(group="g2", node="n2_f", port="left", selector=[1]),
        ),
        ConnectionTemplate(
            source=TemplateEnd(group="g2", node="n2_v", port="right", selector=[2]),
            target=TemplateEnd(group="g2", node="n2_f", port="left", selector=[2]),
        ),
        ConnectionTemplate(
            source=TemplateEnd(group="g2", node="n2_f", port="right", selector=[1]),
            target=TemplateEnd(group="g2", node="n2_p", port="left", selector=[1]),
        ),
        ConnectionTemplate(
            source=TemplateEnd(group="g2", node="n2_f", port="right", selector=[2]),
            target=TemplateEnd(group="g2", node="n2_p", port="left", selector=[2]),
        ),
    ]

    expanded = _expand_templates(templates, instances)
    assert len(expanded) == 6

    deduped = _deduplicate_specs(expanded)
    assert len(deduped) == 6

    inst_pairs = [(s.source.instance, s.target.instance) for s in deduped]
    assert inst_pairs.count((1, 1)) == 3
    assert inst_pairs.count((2, 2)) == 3


def test_deduplicate_specs_removes_duplicates():
    from model.get_connection import (
        ConnectionSpec, ConnectionEnd, _deduplicate_specs,
    )
    specs = [
        ConnectionSpec(id="", source=ConnectionEnd(group="g", node="n", instance=1, port="right"),
                       target=ConnectionEnd(group="g", node="n", instance=2, port="left")),
        ConnectionSpec(id="", source=ConnectionEnd(group="g", node="n", instance=1, port="right"),
                       target=ConnectionEnd(group="g", node="n", instance=2, port="left")),
    ]
    deduped = _deduplicate_specs(specs)
    assert len(deduped) == 1


def _node(group, node, instance, x, y, w=160, h=240, dn=None):
    return {
        "a": {"layout.group": group, "layout.node": node, "layout.instance": instance},
        "p": {
            "displayName": dn or node,
            "position": {"x": x, "y": y},
            "width": w,
            "height": h,
        },
    }


def _ir_data():
    return {
        "layoutIntent": {
            "groups": [
                {
                    "id": "g1",
                    "count": 1,
                    "unit": {
                        "root": {"id": "空气罐1", "deviceType": "空气罐"},
                        "attachments": [
                            {"id": "空气罐1_阀门", "deviceType": "阀门"},
                            {"id": "空气罐1_流量计1", "deviceType": "流量计"},
                            {"id": "空气罐1_压力传感器", "deviceType": "压力传感器"},
                            {"id": "空气罐1_流量计2", "deviceType": "流量计"},
                        ],
                    },
                },
                {
                    "id": "g2",
                    "count": 2,
                    "unit": {
                        "root": {"id": "氮气罐1", "deviceType": "氮气罐"},
                        "attachments": [
                            {"id": "氮气罐1_阀门", "deviceType": "阀门"},
                            {"id": "氮气罐1_流量计", "deviceType": "流量计"},
                            {"id": "氮气罐1_压力传感器", "deviceType": "压力传感器"},
                        ],
                    },
                },
            ],
        },
    }


def test_build_device_directory():
    from model.get_connection import _build_device_directory
    ir = _ir_data()
    nodes = [
        _node("g1", "空气罐1", 1, 386, 623.5, dn="空气罐"),
        _node("g1", "空气罐1_阀门", 1, 386, 431.5, w=64, h=64, dn="阀门"),
        _node("g1", "空气罐1_流量计1", 1, 483, 431.5, w=50, h=68.75, dn="流量计"),
        _node("g1", "空气罐1_压力传感器", 1, 573, 431.5, w=50, h=90, dn="压力传感器"),
        _node("g1", "空气罐1_流量计2", 1, 663, 431.5, w=50, h=68.75, dn="流量计2"),
        _node("g2", "氮气罐1", 1, 1357, 388.5, dn="氮气罐"),
        _node("g2", "氮气罐1_阀门", 1, 1357, 196.5, w=64, h=64, dn="阀门2"),
        _node("g2", "氮气罐1_流量计", 1, 1454, 196.5, w=50, h=68.75, dn="流量计3"),
        _node("g2", "氮气罐1_压力传感器", 1, 1544, 196.5, w=50, h=90, dn="压力传感器2"),
        _node("g2", "氮气罐1", 2, 1357, 858.5, dn="氮气罐2"),
        _node("g2", "氮气罐1_阀门", 2, 1357, 666.5, w=64, h=64, dn="阀门3"),
        _node("g2", "氮气罐1_流量计", 2, 1454, 666.5, w=50, h=68.75, dn="流量计4"),
        _node("g2", "氮气罐1_压力传感器", 2, 1544, 666.5, w=50, h=90, dn="压力传感器3"),
    ]
    dd = _build_device_directory(ir, nodes)
    assert list(dd.keys()) == ["空气罐", "阀门", "流量计", "压力传感器", "氮气罐"]
    assert len(dd["空气罐"]) == 1
    assert dd["空气罐"][0] == ("g1", "空气罐1", 1)
    assert len(dd["阀门"]) == 3
    assert dd["阀门"][0] == ("g1", "空气罐1_阀门", 1)
    assert dd["阀门"][1] == ("g2", "氮气罐1_阀门", 1)
    assert dd["阀门"][2] == ("g2", "氮气罐1_阀门", 2)
    assert len(dd["氮气罐"]) == 2
    assert dd["氮气罐"][0] == ("g2", "氮气罐1", 1)
    assert dd["氮气罐"][1] == ("g2", "氮气罐1", 2)


def test_resolve_name_numbered():
    from model.get_connection import _resolve_name, _build_device_directory
    ir = _ir_data()
    nodes = [
        _node("g1", "空气罐1", 1, 386, 623.5),
        _node("g2", "氮气罐1", 1, 1357, 388.5),
        _node("g2", "氮气罐1", 2, 1357, 858.5),
        _node("g1", "空气罐1_阀门", 1, 386, 431.5, w=64, h=64),
        _node("g2", "氮气罐1_阀门", 1, 1357, 196.5, w=64, h=64),
        _node("g2", "氮气罐1_阀门", 2, 1357, 666.5, w=64, h=64),
    ]
    dd = _build_device_directory(ir, nodes)
    assert _resolve_name("氮气罐1", dd) == ("g2", "氮气罐1", 1)
    assert _resolve_name("氮气罐2", dd) == ("g2", "氮气罐1", 2)
    assert _resolve_name("阀门1", dd) == ("g1", "空气罐1_阀门", 1)
    assert _resolve_name("阀门2", dd) == ("g2", "氮气罐1_阀门", 1)
    assert _resolve_name("阀门3", dd) == ("g2", "氮气罐1_阀门", 2)


def test_resolve_name_unnumbered():
    from model.get_connection import _resolve_name, _build_device_directory, TopologyMismatchError
    ir = _ir_data()
    nodes = [
        _node("g1", "空气罐1", 1, 386, 623.5),
        _node("g2", "氮气罐1", 1, 1357, 388.5),
        _node("g2", "氮气罐1", 2, 1357, 858.5),
    ]
    dd = _build_device_directory(ir, nodes)
    assert _resolve_name("空气罐", dd) == ("g1", "空气罐1", 1)
    with pytest.raises(TopologyMismatchError, match="多个候选"):
        _resolve_name("氮气罐", dd)


def test_resolve_name_nonexistent():
    from model.get_connection import _resolve_name, _build_device_directory, TopologyMismatchError
    ir = _ir_data()
    nodes = [_node("g1", "空气罐1", 1, 0, 0)]
    dd = _build_device_directory(ir, nodes)
    with pytest.raises(TopologyMismatchError, match="设备类型不存在"):
        _resolve_name("不存在", dd)


def test_resolve_name_out_of_range():
    from model.get_connection import _resolve_name, _build_device_directory, TopologyMismatchError
    ir = _ir_data()
    nodes = [
        _node("g1", "空气罐1", 1, 0, 0),
    ]
    dd = _build_device_directory(ir, nodes)
    with pytest.raises(TopologyMismatchError, match="共有 1 个"):
        _resolve_name("空气罐2", dd)


def test_try_parse_chains_simple():
    from model.get_connection import _try_parse_chains, _build_device_directory
    ir = _ir_data()
    nodes = [
        _node("g1", "空气罐1", 1, 0, 0),
        _node("g1", "空气罐1_阀门", 1, 0, 0, w=64, h=64),
    ]
    dd = _build_device_directory(ir, nodes)
    chains = _try_parse_chains("空气罐→阀门", dd)
    assert chains is not None
    assert len(chains) == 1
    assert len(chains[0]) == 1
    assert chains[0][0] == ("g1", "空气罐1", 1, "g1", "空气罐1_阀门", 1)


def test_try_parse_chains_multiple():
    from model.get_connection import _try_parse_chains, _build_device_directory
    ir = _ir_data()
    nodes = [
        _node("g1", "空气罐1", 1, 0, 0),
        _node("g1", "空气罐1_阀门", 1, 0, 0, w=64, h=64),
        _node("g2", "氮气罐1", 1, 0, 0),
        _node("g2", "氮气罐1_阀门", 1, 0, 0, w=64, h=64),
    ]
    dd = _build_device_directory(ir, nodes)
    chains = _try_parse_chains("空气罐1→阀门1, 氮气罐1→阀门2", dd)
    assert chains is not None
    assert len(chains) == 2
    assert len(chains[0]) == 1
    assert len(chains[1]) == 1
    assert chains[0][0] == ("g1", "空气罐1", 1, "g1", "空气罐1_阀门", 1)
    assert chains[1][0] == ("g2", "氮气罐1", 1, "g2", "氮气罐1_阀门", 1)


def test_try_parse_chains_descriptive():
    from model.get_connection import _try_parse_chains, _build_device_directory
    ir = _ir_data()
    nodes = [_node("g1", "空气罐1", 1, 0, 0)]
    dd = _build_device_directory(ir, nodes)
    chains = _try_parse_chains("全部设备串联连接", dd)
    assert chains is None


def test_try_parse_chains_ambiguous_raises():
    from model.get_connection import _try_parse_chains, _build_device_directory, TopologyMismatchError
    ir = _ir_data()
    nodes = [
        _node("g1", "空气罐1_阀门", 1, 0, 0, w=64, h=64),
        _node("g2", "氮气罐1_阀门", 1, 0, 0, w=64, h=64),
    ]
    dd = _build_device_directory(ir, nodes)
    with pytest.raises(TopologyMismatchError, match="多个候选"):
        _try_parse_chains("阀门→阀门", dd)


def test_normalize_ports_horizontal():
    from model.get_connection import ConnectionSpec, ConnectionEnd, _normalize_ports
    nodes = [
        _node("g1", "n1", 1, 300, 100, w=160, h=100),
        _node("g1", "n2", 1, 500, 100, w=160, h=100),
    ]
    spec = ConnectionSpec(
        id="pipe-1",
        source=ConnectionEnd(group="g1", node="n1", instance=1, port="right"),
        target=ConnectionEnd(group="g1", node="n2", instance=1, port="left"),
    )
    result = _normalize_ports([spec], nodes)
    assert len(result) == 1
    assert result[0].source.port == "right"
    assert result[0].target.port == "left"


def test_normalize_ports_vertical_top_bottom():
    from model.get_connection import ConnectionSpec, ConnectionEnd, _normalize_ports
    nodes = [
        _node("g1", "tank", 1, 100, 500, w=160, h=240),
        _node("g1", "valve", 1, 100, 300, w=64, h=64),
    ]
    spec = ConnectionSpec(
        id="pipe-1",
        source=ConnectionEnd(group="g1", node="tank", instance=1, port="right"),
        target=ConnectionEnd(group="g1", node="valve", instance=1, port="left"),
    )
    result = _normalize_ports([spec], nodes)
    assert result[0].source.port == "top"
    assert result[0].target.port == "bottom"


def test_normalize_ports_center_coincidence():
    from model.get_connection import ConnectionSpec, ConnectionEnd, _normalize_ports, TopologyMismatchError
    nodes = [
        _node("g1", "n1", 1, 20, -20, w=160, h=240),
        _node("g1", "n2", 1, 68, 68, w=64, h=64),
    ]
    spec = ConnectionSpec(
        id="pipe-1",
        source=ConnectionEnd(group="g1", node="n1", instance=1, port="right"),
        target=ConnectionEnd(group="g1", node="n2", instance=1, port="left"),
    )
    with pytest.raises(TopologyMismatchError, match="中心重合"):
        _normalize_ports([spec], nodes)


def test_validate_exact_edges_pass():
    from model.get_connection import (
        ConnectionSpec, ConnectionEnd, _validate_exact_edges,
    )
    edges = [
        ConnectionSpec(id="", source=ConnectionEnd("g", "a", 1, ""), target=ConnectionEnd("g", "b", 1, "")),
        ConnectionSpec(id="", source=ConnectionEnd("g", "b", 1, ""), target=ConnectionEnd("g", "c", 1, "")),
    ]
    _validate_exact_edges(edges, edges)


def test_validate_exact_edges_missing():
    from model.get_connection import (
        ConnectionSpec, ConnectionEnd, _validate_exact_edges, TopologyMismatchError,
    )
    actual = [
        ConnectionSpec(id="", source=ConnectionEnd("g", "a", 1, ""), target=ConnectionEnd("g", "b", 1, "")),
    ]
    expected = [
        ConnectionSpec(id="", source=ConnectionEnd("g", "a", 1, ""), target=ConnectionEnd("g", "b", 1, "")),
        ConnectionSpec(id="", source=ConnectionEnd("g", "b", 1, ""), target=ConnectionEnd("g", "c", 1, "")),
    ]
    with pytest.raises(TopologyMismatchError, match="缺失边"):
        _validate_exact_edges(actual, expected)


def test_validate_exact_edges_extra():
    from model.get_connection import (
        ConnectionSpec, ConnectionEnd, _validate_exact_edges, TopologyMismatchError,
    )
    actual = [
        ConnectionSpec(id="", source=ConnectionEnd("g", "a", 1, ""), target=ConnectionEnd("g", "b", 1, "")),
        ConnectionSpec(id="", source=ConnectionEnd("g", "c", 1, ""), target=ConnectionEnd("g", "d", 1, "")),
    ]
    expected = [
        ConnectionSpec(id="", source=ConnectionEnd("g", "a", 1, ""), target=ConnectionEnd("g", "b", 1, "")),
    ]
    with pytest.raises(TopologyMismatchError, match="额外边"):
        _validate_exact_edges(actual, expected)


def test_validate_exact_edges_reversed():
    from model.get_connection import (
        ConnectionSpec, ConnectionEnd, _validate_exact_edges, TopologyMismatchError,
    )
    actual = [
        ConnectionSpec(id="", source=ConnectionEnd("g", "a", 1, ""), target=ConnectionEnd("g", "b", 1, "")),
    ]
    expected = [
        ConnectionSpec(id="", source=ConnectionEnd("g", "b", 1, ""), target=ConnectionEnd("g", "a", 1, "")),
    ]
    with pytest.raises(TopologyMismatchError, match="反向边"):
        _validate_exact_edges(actual, expected)


def test_all_selector_cartesian():
    from model.get_connection import (
        ConnectionTemplate, TemplateEnd, _expand_templates, _deduplicate_specs,
    )
    instances = {("g1", "n1"): {1, 2}, ("g2", "n2"): {1, 2}}
    tmpl = ConnectionTemplate(
        source=TemplateEnd(group="g1", node="n1", port="right", selector="all"),
        target=TemplateEnd(group="g2", node="n2", port="left", selector="all"),
    )
    expanded = _expand_templates([tmpl], instances)
    deduped = _deduplicate_specs(expanded)
    assert len(deduped) == 4


def test_comprehensive_10_edges_with_ports(tmp_path):
    nodes = [
        _node("g1", "空气罐1", 1, 386, 623.5, dn="空气罐"),
        _node("g1", "空气罐1_阀门", 1, 386, 431.5, w=64, h=64, dn="阀门"),
        _node("g1", "空气罐1_流量计1", 1, 483, 431.5, w=50, h=68.75, dn="流量计"),
        _node("g1", "空气罐1_压力传感器", 1, 573, 431.5, w=50, h=90, dn="压力传感器"),
        _node("g1", "空气罐1_流量计2", 1, 663, 431.5, w=50, h=68.75, dn="流量计2"),
        _node("g2", "氮气罐1", 1, 1357, 388.5, dn="氮气罐"),
        _node("g2", "氮气罐1_阀门", 1, 1357, 196.5, w=64, h=64, dn="阀门2"),
        _node("g2", "氮气罐1_流量计", 1, 1454, 196.5, w=50, h=68.75, dn="流量计3"),
        _node("g2", "氮气罐1_压力传感器", 1, 1544, 196.5, w=50, h=90, dn="压力传感器2"),
        _node("g2", "氮气罐1", 2, 1357, 858.5, dn="氮气罐2"),
        _node("g2", "氮气罐1_阀门", 2, 1357, 666.5, w=64, h=64, dn="阀门3"),
        _node("g2", "氮气罐1_流量计", 2, 1454, 666.5, w=50, h=68.75, dn="流量计4"),
        _node("g2", "氮气罐1_压力传感器", 2, 1544, 666.5, w=50, h=90, dn="压力传感器3"),
    ]

    from model.get_connection import (
        _validate_connections, _group_instances, _expand_templates,
        _deduplicate_specs, _normalize_ports,
    )

    raw = [
        {"source": {"group": "g1", "node": "空气罐1", "selector": [1], "port": "right"},
         "target": {"group": "g1", "node": "空气罐1_阀门", "selector": [1], "port": "left"}},
        {"source": {"group": "g1", "node": "空气罐1_阀门", "selector": [1], "port": "right"},
         "target": {"group": "g1", "node": "空气罐1_流量计1", "selector": [1], "port": "left"}},
        {"source": {"group": "g1", "node": "空气罐1_流量计1", "selector": [1], "port": "right"},
         "target": {"group": "g1", "node": "空气罐1_压力传感器", "selector": [1], "port": "left"}},
        {"source": {"group": "g1", "node": "空气罐1_压力传感器", "selector": [1], "port": "right"},
         "target": {"group": "g1", "node": "空气罐1_流量计2", "selector": [1], "port": "left"}},
        {"source": {"group": "g2", "node": "氮气罐1", "selector": [1], "port": "right"},
         "target": {"group": "g2", "node": "氮气罐1_阀门", "selector": [1], "port": "left"}},
        {"source": {"group": "g2", "node": "氮气罐1_阀门", "selector": [1], "port": "right"},
         "target": {"group": "g2", "node": "氮气罐1_流量计", "selector": [1], "port": "left"}},
        {"source": {"group": "g2", "node": "氮气罐1_流量计", "selector": [1], "port": "right"},
         "target": {"group": "g2", "node": "氮气罐1_压力传感器", "selector": [1], "port": "left"}},
        {"source": {"group": "g2", "node": "氮气罐1", "selector": [2], "port": "right"},
         "target": {"group": "g2", "node": "氮气罐1_阀门", "selector": [2], "port": "left"}},
        {"source": {"group": "g2", "node": "氮气罐1_阀门", "selector": [2], "port": "right"},
         "target": {"group": "g2", "node": "氮气罐1_流量计", "selector": [2], "port": "left"}},
        {"source": {"group": "g2", "node": "氮气罐1_流量计", "selector": [2], "port": "right"},
         "target": {"group": "g2", "node": "氮气罐1_压力传感器", "selector": [2], "port": "left"}},
    ]

    templates, errors = _validate_connections(raw, nodes)
    assert not errors, errors

    instances = _group_instances(nodes)
    expanded = _expand_templates(templates, instances)
    expanded = _deduplicate_specs(expanded)
    expanded = _normalize_ports(expanded, nodes)

    assert len(expanded) == 10

    air_edges = [s for s in expanded if s.source.group == "g1" and s.source.node.startswith("空气罐")]
    assert len(air_edges) == 4

    n2_1_edges = [s for s in expanded if s.source.group == "g2" and s.source.instance == 1]
    assert len(n2_1_edges) == 3

    n2_2_edges = [s for s in expanded if s.source.group == "g2" and s.source.instance == 2]
    assert len(n2_2_edges) == 3

    cross_edges = [s for s in expanded if s.source.instance != s.target.instance]
    assert len(cross_edges) == 0

    air_g2_edges = [s for s in expanded if s.source.group != s.target.group]
    assert len(air_g2_edges) == 0

    tank_to_valve = [s for s in expanded if s.source.node == "空气罐1" or s.source.node == "氮气罐1"]
    for s in tank_to_valve:
        assert s.source.port == "top"
        assert s.target.port == "bottom"

    horizontal_edges = [s for s in expanded if s not in tank_to_valve]
    for s in horizontal_edges:
        assert s.source.port == "right"
        assert s.target.port == "left"
