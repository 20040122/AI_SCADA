import sqlite3

import pytest

from app.schemas import CanvasLayoutRequest
import data.sqlite.material_db as material_db_module
from data.sqlite.material_db import MaterialDB
from model.compute_position import MissingMaterialError, convert_layout_file
from model.generate_gird import _load_vocab
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
