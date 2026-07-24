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

    def fake_write_text(self, text, encoding):
        writes[self.name] = text
        assert encoding == "utf-8"
        return len(text)

    monkeypatch.setattr("model.generate_gird.generate_intent", fake_generate_intent)
    monkeypatch.setattr("model.compute_position.convert_layout_file", fake_convert_layout_file)
    monkeypatch.setattr("model.layout_agent._schema_validate", fake_schema_validate)
    monkeypatch.setattr("model.layout_agent.Path.write_text", fake_write_text)
    monkeypatch.setattr(LayoutAgent, "create_canvas", fake_create_canvas)

    result = await LayoutAgent(db=DB(), client=object(), model="test-model").generate(
        "控件：1台水泵。\n流程：水泵。\n结构：水泵位于页面中部。\n管道：对齐。",
        1920,
        1080,
    )

    ir_writes = {path: content for path, content in writes.items() if path.endswith("it_ir.json")}
    pos_writes = {path: content for path, content in writes.items() if path.endswith("position.json")}
    assert len(ir_writes) == 1
    assert json.loads(list(ir_writes.values())[0]) == result.ir_data
    assert len(pos_writes) == 0
