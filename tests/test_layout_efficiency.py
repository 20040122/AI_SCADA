from __future__ import annotations

import logging
from typing import Optional

import pytest

from model.layout_tools import compute_position as cp
from model.layout_tools.get_intent import (
    DeviceNode,
    IntentModelOutputError,
    IntentModelUnavailableError,
    LayoutUnit,
    Region,
    Side,
    _IMAGE_CACHE,
    image_to_structured_prompt,
)
import model.layout_tools.get_intent as intent_module
from tests.conftest import make_fake_completion


PAYLOAD = (
    '{"inventory":[{"deviceType":"泵","count":1}],"flow":"泵",'
    '"structure":"泵位于左侧","piping":""}'
)


class FakeImageCaller:
    def __init__(self, payload=None, exc=None):
        self.payload = payload
        self.exc = exc
        self.calls = 0

    async def __call__(self, image, prompt, client=None, model=None):
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        return self.payload


class FakeModelCaller:
    def __init__(self, payload=""):
        self.payload = payload
        self.calls = 0

    async def __call__(self, client, model, messages, **kwargs):
        self.calls += 1
        return make_fake_completion(self.payload)


def _materials():
    return [{"displayName": "泵"}]


@pytest.fixture(autouse=True)
def _reset_image_cache():
    _IMAGE_CACHE.clear()
    yield
    _IMAGE_CACHE.clear()


@pytest.mark.asyncio
async def test_image_cache_hit_skips_recognition(caplog):
    caller = FakeImageCaller(PAYLOAD)
    with caplog.at_level(logging.INFO):
        first = await image_to_structured_prompt(b"same-image", _materials(), image_caller=caller)
        second = await image_to_structured_prompt(b"same-image", _materials(), image_caller=caller)
    assert first == second
    assert caller.calls == 1
    assert "cache_hit=true" in caplog.text
    assert "cache_hit=false" in caplog.text
    assert "model_calls=0" in caplog.text


@pytest.mark.asyncio
async def test_image_cache_invalidated_by_image_bytes():
    caller = FakeImageCaller(PAYLOAD)
    await image_to_structured_prompt(b"image-a", _materials(), image_caller=caller)
    await image_to_structured_prompt(b"image-b", _materials(), image_caller=caller)
    assert caller.calls == 2


@pytest.mark.asyncio
async def test_image_cache_invalidated_by_vocab():
    caller = FakeImageCaller(PAYLOAD)
    await image_to_structured_prompt(b"same-image", [{"displayName": "泵"}], image_caller=caller)
    await image_to_structured_prompt(
        b"same-image", [{"displayName": "泵"}, {"displayName": "水箱"}], image_caller=caller
    )
    assert caller.calls == 2


@pytest.mark.asyncio
async def test_image_cache_invalidated_by_model():
    caller = FakeImageCaller(PAYLOAD)
    await image_to_structured_prompt(
        b"same-image", _materials(), image_model="model-a", image_caller=caller
    )
    await image_to_structured_prompt(
        b"same-image", _materials(), image_model="model-b", image_caller=caller
    )
    assert caller.calls == 2


@pytest.mark.asyncio
async def test_image_cache_invalidated_by_prompt_version(monkeypatch):
    caller = FakeImageCaller(PAYLOAD)
    await image_to_structured_prompt(b"same-image", _materials(), image_caller=caller)
    monkeypatch.setattr(intent_module, "_IMAGE_CACHE_VERSION", intent_module._IMAGE_CACHE_VERSION + 1)
    await image_to_structured_prompt(b"same-image", _materials(), image_caller=caller)
    assert caller.calls == 2


@pytest.mark.asyncio
async def test_image_cache_failure_not_cached():
    failing = FakeImageCaller(exc=RuntimeError("boom"))
    with pytest.raises(IntentModelUnavailableError):
        await image_to_structured_prompt(b"same-image", _materials(), image_caller=failing)
    assert _IMAGE_CACHE == {}
    ok = FakeImageCaller(PAYLOAD)
    prompt = await image_to_structured_prompt(b"same-image", _materials(), image_caller=ok)
    assert ok.calls == 1
    assert prompt.startswith("控件：1台泵")


@pytest.mark.asyncio
async def test_image_cache_invalid_output_not_cached():
    invalid = FakeImageCaller("not-json")
    with pytest.raises(IntentModelOutputError):
        await image_to_structured_prompt(b"same-image", _materials(), image_caller=invalid)
    assert _IMAGE_CACHE == {}
    ok = FakeImageCaller(PAYLOAD)
    await image_to_structured_prompt(b"same-image", _materials(), image_caller=ok)
    assert ok.calls == 1


@pytest.mark.asyncio
async def test_image_cache_respects_capacity(monkeypatch):
    monkeypatch.setattr(intent_module, "_IMAGE_CACHE_MAX", 3)
    caller = FakeImageCaller(PAYLOAD)
    for index in range(5):
        await image_to_structured_prompt(
            ("image-%d" % index).encode(), _materials(), image_caller=caller
        )
    assert len(_IMAGE_CACHE) == 3


def _make_group(gid, region: Region = "center", relative_to=None, side: Optional[Side] = None):
    return cp.LayoutGroup(
        id=gid,
        region=region,
        count=1,
        relativeTo=relative_to,
        side=side,
        unit=LayoutUnit(root=DeviceNode(id="root-%s" % gid, deviceType="泵")),
    )


def test_related_group_columns_share_cache(monkeypatch):
    groups = [
        _make_group("g4", "right", "g3", "right"),
        _make_group("g3", "right", "g2", "right"),
        _make_group("g2", "right", "g1", "right"),
        _make_group("g1", "center"),
    ]
    relations = cp._group_relations(groups)
    content_rect = {"x": 0, "y": 0, "width": 1200, "height": 600}
    by_id = {group.id: group for group in groups}
    original = cp._group_column

    calls = {"n": 0}

    def counting(*args, **kwargs):
        calls["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(cp, "_group_column", counting)

    unshared_columns = {}
    for group in groups:
        unshared_columns[group.id] = cp._group_column(group, by_id, relations, {})
    unshared_total = calls["n"]

    calls["n"] = 0
    cp._compute_related_group_slots(groups, content_rect, relations)
    fixed_total = calls["n"]

    shared_cache = {}
    shared_columns = {
        group.id: original(group, by_id, relations, shared_cache) for group in groups
    }

    assert shared_columns == unshared_columns
    assert fixed_total < unshared_total
