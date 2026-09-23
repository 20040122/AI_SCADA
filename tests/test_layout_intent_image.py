from __future__ import annotations

import base64

import pytest

from model.image_intent import IMAGE_TEMPERATURE, PROMPT, _encode
from model.layout_tools.get_intent import (
    IntentModelOutputError,
    IntentModelUnavailableError,
    StructuredPromptError,
    _INTENT_CACHE,
    _prompt_from_image_payload,
    generate_intent_from_image,
    image_to_structured_prompt,
    parse_structured_prompt,
)
from tests.conftest import make_fake_completion


def _materials() -> list[dict]:
    return [{"displayName": "泵"}, {"displayName": "水箱"}]


def _image_payload() -> str:
    return (
        '{"inventory":[{"deviceType":"泵","count":1},{"deviceType":"水箱","count":1}],'
        '"flow":"水箱-泵",'
        '"structure":"水箱与泵通过管道连接，两条支路彼此独立",'
        '"piping":"水箱-泵"}'
    )


def _valid_intent_json() -> str:
    return (
        '{"layoutIntent":{"groups":['
        '{"id":"g1","region":"center","count":1,"unit":{"root":{"id":"r1","deviceType":"泵"}}},'
        '{"id":"g2","region":"center","count":1,"topology":"single",'
        '"relativeTo":"g1","side":"right","unit":{"root":{"id":"r2","deviceType":"水箱"}}}'
        "]}}"
    )


class FakeImageCaller:
    def __init__(self, payload: str):
        self._payload = payload
        self.calls = 0
        self.prompts: list[str] = []
        self.images: list[object] = []

    async def __call__(self, image, prompt, client=None, model=None):
        self.calls += 1
        self.prompts.append(prompt)
        self.images.append(image)
        return self._payload


class FakeModelCaller:
    def __init__(self, payload: str = ""):
        self._payload = payload
        self.calls = 0

    async def __call__(self, client, model, messages, **kwargs):
        self.calls += 1
        return make_fake_completion(self._payload)


class RaisingImageCaller:
    def __init__(self, exc: Exception):
        self._exc = exc
        self.calls = 0

    async def __call__(self, image, prompt, client=None, model=None):
        self.calls += 1
        raise self._exc


def _clear_cache():
    _INTENT_CACHE.clear()


@pytest.mark.asyncio
async def test_generate_intent_from_image_end_to_end():
    _clear_cache()
    image_caller = FakeImageCaller(_image_payload())
    model_caller = FakeModelCaller(_valid_intent_json())
    result = await generate_intent_from_image(
        b"fake-bytes",
        _materials(),
        model_caller=model_caller,
        image_caller=image_caller,
    )
    assert image_caller.calls == 1
    assert model_caller.calls == 1
    assert [g.unit.root.deviceType for g in result.layoutIntent.groups] == ["泵", "水箱"]
    assert "泵、水箱" in image_caller.prompts[0]


@pytest.mark.asyncio
async def test_image_prompt_includes_vocab():
    _clear_cache()
    image_caller = FakeImageCaller(_image_payload())
    model_caller = FakeModelCaller(_valid_intent_json())
    await generate_intent_from_image(
        "image01.png",
        _materials(),
        model_caller=model_caller,
        image_caller=image_caller,
    )
    assert "泵、水箱" in image_caller.prompts[0]


@pytest.mark.asyncio
async def test_invalid_image_json_raises_with_category():
    _clear_cache()
    image_caller = FakeImageCaller("这不是 JSON")
    model_caller = FakeModelCaller(_valid_intent_json())
    with pytest.raises(IntentModelOutputError) as excinfo:
        await generate_intent_from_image(
            b"fake-bytes",
            _materials(),
            model_caller=model_caller,
            image_caller=image_caller,
        )
    assert excinfo.value.category == "image_json_parse"
    assert excinfo.value.raw_output == "这不是 JSON"
    assert model_caller.calls == 0


@pytest.mark.asyncio
async def test_missing_image_fields_raises_image_structure():
    _clear_cache()
    image_caller = FakeImageCaller('{"inventory":[],"structure":"x"}')
    model_caller = FakeModelCaller(_valid_intent_json())
    with pytest.raises(IntentModelOutputError) as excinfo:
        await generate_intent_from_image(
            b"fake-bytes",
            _materials(),
            model_caller=model_caller,
            image_caller=image_caller,
        )
    assert excinfo.value.category == "image_structure"
    assert "流程" in str(excinfo.value)
    assert model_caller.calls == 0


@pytest.mark.asyncio
async def test_image_device_not_in_vocab_raises_structured_prompt_error():
    _clear_cache()
    image_caller = FakeImageCaller(
        '{"inventory":[{"deviceType":"风机","count":1}],"flow":"风机","structure":"风机位于左侧"}'
    )
    model_caller = FakeModelCaller(_valid_intent_json())
    with pytest.raises(StructuredPromptError):
        await generate_intent_from_image(
            b"fake-bytes",
            _materials(),
            model_caller=model_caller,
            image_caller=image_caller,
        )
    assert model_caller.calls == 0


@pytest.mark.asyncio
async def test_image_to_structured_prompt_includes_piping_section():
    image_caller = FakeImageCaller(_image_payload())
    prompt = await image_to_structured_prompt(
        b"fake-bytes", _materials(), image_caller=image_caller
    )
    assert prompt == (
        "控件：1台泵、1台水箱\n"
        "流程：水箱-泵\n"
        "结构：水箱与泵通过管道连接，两条支路彼此独立\n"
        "管道：水箱-泵"
    )


@pytest.mark.asyncio
async def test_image_to_structured_prompt_omits_empty_piping():
    image_caller = FakeImageCaller(
        '{"inventory":[{"deviceType":"泵","count":1}],"flow":"泵",'
        '"structure":"泵位于左侧","piping":""}'
    )
    prompt = await image_to_structured_prompt(
        b"fake-bytes", _materials(), image_caller=image_caller
    )
    assert "管道" not in prompt


@pytest.mark.asyncio
async def test_image_model_failure_raises_unavailable():
    _clear_cache()
    image_caller = RaisingImageCaller(RuntimeError("boom"))
    model_caller = FakeModelCaller(_valid_intent_json())
    with pytest.raises(IntentModelUnavailableError):
        await generate_intent_from_image(
            b"fake-bytes",
            _materials(),
            model_caller=model_caller,
            image_caller=image_caller,
        )
    assert image_caller.calls == 1
    assert model_caller.calls == 0


def test_prompt_from_image_payload_rejects_non_dict():
    with pytest.raises(IntentModelOutputError) as excinfo:
        _prompt_from_image_payload([])
    assert excinfo.value.category == "image_structure"


@pytest.mark.asyncio
async def test_image_intent_sets_zero_temperature(monkeypatch):
    captured: dict = {}

    async def fake_call_llm(client, model, messages, **kwargs):
        captured["messages"] = messages
        captured["kwargs"] = kwargs
        return make_fake_completion(_image_payload())

    import model.image_intent as image_intent_module

    monkeypatch.setattr(image_intent_module, "call_llm", fake_call_llm)
    result = await image_intent_module.image_intent(b"fake-bytes")
    assert result == _image_payload()
    assert IMAGE_TEMPERATURE == 0.0
    assert captured["kwargs"].get("temperature") == IMAGE_TEMPERATURE
    assert "禁止矩阵补全" in captured["messages"][0]["content"]


def test_image_prompt_guards_isolated_instances():
    assert "孤立设备" in PROMPT
    assert "禁止矩阵补全" in PROMPT
    assert "示例设备B3" in PROMPT
    assert "示例设备A-示例设备B3" not in PROMPT
    assert '"isolated"' in PROMPT
    assert "五个字段" in PROMPT


def test_prompt_from_image_payload_strips_isolated_chains():
    payload = {
        "inventory": [{"deviceType": "冷冻泵", "count": 4}],
        "flow": "冷冻泵",
        "structure": "冷冻泵4无连接线，为孤立设备。",
        "piping": "冷水机1-冷冻泵1；冷水机1-冷冻泵4；冷水机2-冷冻泵2",
        "isolated": ["冷冻泵4"],
    }
    prompt = _prompt_from_image_payload(payload)
    piping_line = prompt.split("管道：", 1)[1]
    assert "冷冻泵4" not in piping_line
    assert "冷水机1-冷冻泵1" in piping_line
    assert "冷水机2-冷冻泵2" in piping_line


def test_prompt_from_image_payload_tolerates_missing_isolated():
    payload = {
        "inventory": [{"deviceType": "泵", "count": 1}],
        "flow": "泵",
        "structure": "泵",
        "piping": "泵-泵",
    }
    prompt = _prompt_from_image_payload(payload)
    assert "管道：泵-泵" in prompt


def test_parse_structured_prompt_structure_count_conflict_toggle():
    prompt = "控件：2台水箱\n流程：水箱\n结构：两条支路各1台水箱，水箱位于右侧"
    with pytest.raises(StructuredPromptError) as excinfo:
        parse_structured_prompt(prompt)
    assert excinfo.value.errors[0].path == "结构.水箱.count"
    checked = parse_structured_prompt(prompt, check_structure_counts=False)
    assert checked.inventory[0].count == 2


@pytest.mark.asyncio
async def test_image_path_skips_structure_count_conflict():
    _clear_cache()
    image_caller = FakeImageCaller(
        '{"inventory":[{"deviceType":"水箱","count":2}],'
        '"flow":"水箱",'
        '"structure":"两条支路各1台水箱，水箱位于右侧纵向排列",'
        '"piping":""}'
    )
    model_caller = FakeModelCaller(
        '{"layoutIntent":{"groups":['
        '{"id":"g1","region":"center","count":2,"arrangement":"vertical",'
        '"unit":{"root":{"id":"r1","deviceType":"水箱"}}}'
        "]}}"
    )
    result = await generate_intent_from_image(
        b"fake-bytes",
        [{"displayName": "水箱"}],
        model_caller=model_caller,
        image_caller=image_caller,
    )
    assert image_caller.calls == 1
    assert result.layoutIntent.groups[0].count == 2


def test_encode_supports_bytes_data_url_and_path(tmp_path):
    raw = b"png-bytes"
    assert _encode(raw) == "data:image/png;base64," + base64.b64encode(raw).decode()
    assert _encode(bytearray(raw)).endswith(base64.b64encode(raw).decode())
    data_url = "data:image/jpeg;base64,QUJD"
    assert _encode(data_url) == data_url
    assert _encode("QUJD") == "data:image/png;base64,QUJD"
    image_path = tmp_path / "sample.png"
    image_path.write_bytes(raw)
    assert _encode(str(image_path)) == "data:image/png;base64," + base64.b64encode(raw).decode()
