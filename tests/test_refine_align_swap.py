from __future__ import annotations

from typing import Any

import pytest

from model.refine_agent import RefineAgent, RefineModelError
from tests.conftest import FakeAsyncClient, make_fake_completion


def _control(
    node_i: int,
    name: str,
    x: float,
    y: float,
    w: float,
    h: float,
) -> dict:
    return {
        "c": "ht.Node",
        "i": node_i,
        "a": {
            "layout.node": True,
            "layout.sourceWidth": 100,
            "layout.sourceHeight": 50,
        },
        "p": {
            "displayName": name,
            "image": "symbols/x.png",
            "position": {"x": x, "y": y},
            "width": w,
            "height": h,
        },
    }


def _label(node_i: int, label_for: int, text: str = "泵") -> dict:
    return {
        "c": "ht.Text",
        "i": node_i,
        "a": {"layout.role": "control-label", "layout.labelFor": label_for},
        "p": {"position": {"x": 100, "y": 166}, "width": 56, "height": 32},
        "s": {"text": text},
    }


def _json(entries: list[dict]) -> dict:
    return {"a": {"width": 1920, "height": 1080}, "d": entries}


def _two_controls() -> list[dict]:
    return [
        _control(1, "阀A", 100, 200, 40, 20),
        _control(2, "阀B", 300, 400, 60, 30),
    ]


async def _refine(actions_json: str, json_data: dict):
    fake = FakeAsyncClient(
        [make_fake_completion('{"actions": ' + actions_json + ', "message": "ok"}')]
    )
    agent = RefineAgent(client=fake)
    return await agent.refine("调整", json_data)


def _values(patch: list[dict], path: str) -> list[Any]:
    return [op["value"] for op in patch if op.get("path") == path]


@pytest.mark.asyncio
async def test_align_left():
    result = await _refine(
        '[{"type":"align","target_ids":[1,2],"alignment":"left"}]',
        _json(_two_controls()),
    )
    assert _values(result.patch, "/d/0/p/position/x") == []
    assert _values(result.patch, "/d/1/p/position/x") == [110]


@pytest.mark.asyncio
async def test_align_right():
    result = await _refine(
        '[{"type":"align","target_ids":[1,2],"alignment":"right"}]',
        _json(_two_controls()),
    )
    assert _values(result.patch, "/d/0/p/position/x") == [310]
    assert _values(result.patch, "/d/1/p/position/x") == []


@pytest.mark.asyncio
async def test_align_top():
    result = await _refine(
        '[{"type":"align","target_ids":[1,2],"alignment":"top"}]',
        _json(_two_controls()),
    )
    assert _values(result.patch, "/d/0/p/position/y") == []
    assert _values(result.patch, "/d/1/p/position/y") == [205]


@pytest.mark.asyncio
async def test_align_bottom():
    result = await _refine(
        '[{"type":"align","target_ids":[1,2],"alignment":"bottom"}]',
        _json(_two_controls()),
    )
    assert _values(result.patch, "/d/0/p/position/y") == [405]
    assert _values(result.patch, "/d/1/p/position/y") == []


@pytest.mark.asyncio
async def test_align_center_x():
    result = await _refine(
        '[{"type":"align","target_ids":[1,2],"alignment":"center_x"}]',
        _json(_two_controls()),
    )
    assert _values(result.patch, "/d/0/p/position/x") == [205]
    assert _values(result.patch, "/d/1/p/position/x") == [205]


@pytest.mark.asyncio
async def test_align_center_y():
    result = await _refine(
        '[{"type":"align","target_ids":[1,2],"alignment":"center_y"}]',
        _json(_two_controls()),
    )
    assert _values(result.patch, "/d/0/p/position/y") == [302.5]
    assert _values(result.patch, "/d/1/p/position/y") == [302.5]


@pytest.mark.asyncio
async def test_align_three_controls():
    controls = _two_controls()
    controls.append(_control(3, "阀C", 500, 600, 80, 40))
    result = await _refine(
        '[{"type":"align","target_ids":[1,2,3],"alignment":"left"}]',
        _json(controls),
    )
    assert _values(result.patch, "/d/0/p/position/x") == []
    assert _values(result.patch, "/d/1/p/position/x") == [110]
    assert _values(result.patch, "/d/2/p/position/x") == [120]


@pytest.mark.asyncio
async def test_align_moves_label_with_control():
    entries = _two_controls()
    entries.append(_label(3, 1))
    result = await _refine(
        '[{"type":"align","target_ids":[1,2],"alignment":"center_x"}]',
        _json(entries),
    )
    assert _values(result.patch, "/d/0/p/position/x") == [205]
    assert _values(result.patch, "/d/2/p/position/x") == [205]


@pytest.mark.asyncio
async def test_align_invalid_alignment_is_model_error():
    with pytest.raises(RefineModelError):
        await _refine(
            '[{"type":"align","target_ids":[1,2],"alignment":"diagonal"}]',
            _json(_two_controls()),
        )


@pytest.mark.asyncio
async def test_align_single_target_is_model_error():
    with pytest.raises(RefineModelError):
        await _refine(
            '[{"type":"align","target_ids":[1],"alignment":"left"}]',
            _json(_two_controls()),
        )


@pytest.mark.asyncio
async def test_swap_exchanges_positions():
    result = await _refine(
        '[{"type":"swap","target_ids":[1,2]}]',
        _json(_two_controls()),
    )
    assert _values(result.patch, "/d/0/p/position/x") == [300]
    assert _values(result.patch, "/d/0/p/position/y") == [400]
    assert _values(result.patch, "/d/1/p/position/x") == [100]
    assert _values(result.patch, "/d/1/p/position/y") == [200]


@pytest.mark.asyncio
async def test_swap_keeps_sizes_unchanged():
    result = await _refine(
        '[{"type":"swap","target_ids":[1,2]}]',
        _json(_two_controls()),
    )
    assert _values(result.patch, "/d/0/p/width") == []
    assert _values(result.patch, "/d/0/p/height") == []
    assert _values(result.patch, "/d/1/p/width") == []
    assert _values(result.patch, "/d/1/p/height") == []


@pytest.mark.asyncio
async def test_swap_moves_labels_with_controls():
    entries = _two_controls()
    entries.append(_label(3, 1))
    entries.append(_label(4, 2))
    result = await _refine(
        '[{"type":"swap","target_ids":[1,2]}]',
        _json(entries),
    )
    assert _values(result.patch, "/d/2/p/position/x") == [300]
    assert _values(result.patch, "/d/3/p/position/x") == [100]


@pytest.mark.asyncio
async def test_swap_single_target_is_model_error():
    with pytest.raises(RefineModelError):
        await _refine(
            '[{"type":"swap","target_ids":[1]}]',
            _json(_two_controls()),
        )


@pytest.mark.asyncio
async def test_swap_three_targets_is_model_error():
    controls = _two_controls()
    controls.append(_control(3, "阀C", 500, 600, 80, 40))
    with pytest.raises(RefineModelError):
        await _refine(
            '[{"type":"swap","target_ids":[1,2,3]}]',
            _json(controls),
        )


@pytest.mark.asyncio
async def test_swap_extra_field_is_model_error():
    with pytest.raises(RefineModelError):
        await _refine(
            '[{"type":"swap","target_ids":[1,2],"dx":10}]',
            _json(_two_controls()),
        )


@pytest.mark.asyncio
async def test_swap_clamps_to_canvas():
    controls = [
        _control(1, "阀A", 100, 200, 40, 20),
        _control(2, "阀B", 1950, 1060, 60, 30),
    ]
    result = await _refine(
        '[{"type":"swap","target_ids":[1,2]}]',
        _json(controls),
    )
    assert _values(result.patch, "/d/0/p/position/x") == [1900]
    assert _values(result.patch, "/d/0/p/position/y") == [1060]
    assert _values(result.patch, "/d/1/p/position/x") == [100]
    assert _values(result.patch, "/d/1/p/position/y") == [200]


@pytest.mark.asyncio
async def test_swap_positions_via_two_absolute_moves():
    result = await _refine(
        '[{"type":"move","target_ids":[1],"x":300,"y":400},{"type":"move","target_ids":[2],"x":100,"y":200}]',
        _json(_two_controls()),
    )
    assert _values(result.patch, "/d/0/p/position/x") == [300]
    assert _values(result.patch, "/d/0/p/position/y") == [400]
    assert _values(result.patch, "/d/1/p/position/x") == [100]
    assert _values(result.patch, "/d/1/p/position/y") == [200]
