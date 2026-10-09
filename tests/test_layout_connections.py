from __future__ import annotations

import pytest

from model.layout_tools import get_connection
from model.layout_tools.get_connection import generate_connections


def _ir_data() -> dict:
    return {
        "layoutIntent": {
            "groups": [
                {"id": "g1", "unit": {"root": {"id": "c", "deviceType": "冷水机"}}},
                {"id": "g2", "unit": {"root": {"id": "p", "deviceType": "冷冻泵"}}},
            ]
        }
    }


def _node(group: str, node: str, instance: int, x: float, y: float) -> dict:
    return {
        "a": {
            "layout.group": group,
            "layout.node": node,
            "layout.instance": instance,
        },
        "p": {
            "position": {"x": x, "y": y},
            "width": 120,
            "height": 80,
        },
    }


def _nodes() -> list[dict]:
    nodes = []
    for i in range(3):
        nodes.append(_node("g1", "c", i + 1, 400, 100 + i * 200))
    for i in range(4):
        nodes.append(_node("g2", "p", i + 1, 1200, 100 + i * 150))
    return nodes


_PIPING = (
    "冷水机1-冷冻泵1；冷水机1-冷冻泵2；冷水机1-冷冻泵3；"
    "冷水机2-冷冻泵1；冷水机2-冷冻泵2；冷水机2-冷冻泵3；"
    "冷水机3-冷冻泵1；冷水机3-冷冻泵2；冷水机3-冷冻泵3"
)


@pytest.mark.asyncio
async def test_explicit_piping_skips_connection_model(monkeypatch):
    async def _boom(*args, **kwargs):
        raise AssertionError("显式管道不应调用连接模型")

    monkeypatch.setattr(get_connection, "_call_connection_model", _boom)

    query = "控件：3台冷水机、4台冷冻泵\n管道：" + _PIPING
    result = await generate_connections(
        query, _nodes(), client=None, ir_data=_ir_data()
    )

    assert result is not None
    assert len(result["connections"]) == 9
    targets = {c["target"]["instance"] for c in result["connections"]}
    assert targets == {1, 2, 3}
    assert all(c["target"]["instance"] != 4 for c in result["connections"])


@pytest.mark.asyncio
async def test_explicit_piping_assigns_geometric_ports():
    query = "管道：" + _PIPING
    result = await generate_connections(
        query, _nodes(), client=None, ir_data=_ir_data()
    )
    assert result is not None
    assert all(c["source"]["port"] == "right" for c in result["connections"])
    assert all(c["target"]["port"] == "left" for c in result["connections"])
    assert [c["id"] for c in result["connections"]][:3] == [
        "pipe-1",
        "pipe-2",
        "pipe-3",
    ]
