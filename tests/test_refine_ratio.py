from __future__ import annotations

import pytest

from model.refine_agent import RefineAgent
from tests.conftest import FakeAsyncClient, make_fake_completion

ASPECT = 2.0


def _json_data(with_metadata=True, with_label=False):
    attrs: dict[str, object] = {"layout.node": True}
    if with_metadata:
        attrs["layout.sourceWidth"] = 200
        attrs["layout.sourceHeight"] = 100
    entries = [
        {
            "c": "ht.Node",
            "i": 1,
            "a": attrs,
            "p": {
                "displayName": "泵",
                "image": "symbols/pump.json",
                "position": {"x": 300, "y": 300},
                "width": 100,
                "height": 50,
            },
        }
    ]
    if with_label:
        entries.append(
            {
                "c": "ht.Text",
                "i": 2,
                "a": {"layout.role": "control-label", "layout.labelFor": 1},
                "p": {"position": {"x": 100, "y": 40}, "width": 120, "height": 32},
                "s": {"text": "泵"},
            }
        )
    return {"a": {"width": 1920, "height": 1080}, "d": entries}


def _patch_values(patch, path):
    return [op["value"] for op in patch if op.get("path") == path]


async def _refine(actions_json):
    fake = FakeAsyncClient(
        [make_fake_completion('{"actions": ' + actions_json + ', "message": "ok"}')]
    )
    agent = RefineAgent(client=fake)
    return await agent.refine("resize", _json_data())


@pytest.mark.asyncio
async def test_scale_scales_both_dims():
    result = await _refine('[{"type":"resize","target_ids":[1],"scale":1.5}]')
    assert _patch_values(result.patch, "/d/0/p/width") == [150]
    assert _patch_values(result.patch, "/d/0/p/height") == [75]


@pytest.mark.asyncio
async def test_width_only_derives_height():
    result = await _refine('[{"type":"resize","target_ids":[1],"width":200}]')
    assert _patch_values(result.patch, "/d/0/p/width") == [200]
    assert _patch_values(result.patch, "/d/0/p/height") == [100]


@pytest.mark.asyncio
async def test_height_only_derives_width():
    result = await _refine('[{"type":"resize","target_ids":[1],"height":40}]')
    assert _patch_values(result.patch, "/d/0/p/width") == [80]
    assert _patch_values(result.patch, "/d/0/p/height") == [40]


@pytest.mark.asyncio
async def test_mismatched_box_inscribes():
    result = await _refine('[{"type":"resize","target_ids":[1],"width":200,"height":150}]')
    assert _patch_values(result.patch, "/d/0/p/width") == [200]
    assert _patch_values(result.patch, "/d/0/p/height") == [100]


@pytest.mark.asyncio
async def test_mismatched_box_height_limited():
    result = await _refine('[{"type":"resize","target_ids":[1],"width":500,"height":100}]')
    assert _patch_values(result.patch, "/d/0/p/width") == [200]
    assert _patch_values(result.patch, "/d/0/p/height") == [100]


@pytest.mark.asyncio
async def test_canvas_boundary_clips_uniformly():
    result = await _refine('[{"type":"resize","target_ids":[1],"width":5000}]')
    width = _patch_values(result.patch, "/d/0/p/width")[0]
    height = _patch_values(result.patch, "/d/0/p/height")[0]
    assert width <= 1920
    assert height <= 1080
    assert abs(width / height - ASPECT) <= 1e-9


@pytest.mark.asyncio
async def test_missing_metadata_returns_empty_patch():
    fake = FakeAsyncClient(
        [make_fake_completion(
            '{"actions": [{"type":"resize","target_ids":[1],"width":200}], "message": "ok"}'
        )]
    )
    agent = RefineAgent(client=fake)
    result = await agent.refine("resize", _json_data(with_metadata=False))
    assert result.patch == []
    assert "no material size metadata" in result.message


@pytest.mark.asyncio
async def test_resized_control_emits_both_width_and_height():
    result = await _refine('[{"type":"resize","target_ids":[1],"width":200}]')
    paths = {op["path"] for op in result.patch}
    assert "/d/0/p/width" in paths
    assert "/d/0/p/height" in paths


@pytest.mark.asyncio
async def test_label_repositioned_after_resize():
    fake = FakeAsyncClient(
        [make_fake_completion(
            '{"actions": [{"type":"resize","target_ids":[1],"width":200}], "message": "ok"}'
        )]
    )
    agent = RefineAgent(client=fake)
    result = await agent.refine("resize", _json_data(with_label=True))
    label_y = _patch_values(result.patch, "/d/1/p/position/y")[0]
    label_width = _patch_values(result.patch, "/d/1/p/width")[0]
    assert label_y == 226
    assert label_width == 200


@pytest.mark.asyncio
async def test_move_without_ratio_metadata_still_works():
    fake = FakeAsyncClient(
        [make_fake_completion(
            '{"actions": [{"type":"move","target_ids":[1],"dx":10,"dy":0}], "message": "ok"}'
        )]
    )
    agent = RefineAgent(client=fake)
    result = await agent.refine("move", _json_data(with_metadata=False))
    assert _patch_values(result.patch, "/d/0/p/position/x") == [310]
