from __future__ import annotations

import logging
from typing import Optional

import pytest
from fastapi.testclient import TestClient

import app.deps as deps_module
from app.main import app
from model.layout_tools.get_intent import (
    IntentModelOutputError,
    IntentModelTimeoutError,
    IntentModelUnavailableError,
    _INTENT_CACHE,
    generate_intent,
)
from tests.conftest import make_fake_completion


def _prompt() -> str:
    return "控件：2台泵\n流程：泵\n结构：泵"


def _rule_prompt() -> str:
    return "控件：2台泵\n流程：泵\n结构：泵左侧"


def _materials() -> list[dict]:
    return [{"displayName": "泵"}]


def _valid_intent_json() -> str:
    return '{"layoutIntent":{"groups":[{"id":"g1","region":"center","count":2,"unit":{"root":{"id":"r","deviceType":"泵"}}}]}}'


def _invalid_json() -> str:
    return "这不是 JSON"


def _structure_invalid_json() -> str:
    return '{"layoutIntent":{}}'


def _semantic_invalid_json() -> str:
    return '{"layoutIntent":{"groups":[{"id":"g1","region":"center","count":1,"unit":{"root":{"id":"r","deviceType":"泵"}}}]}}'


class FakeCaller:
    def __init__(self, responses: list[str], raises: Optional[list[Exception]] = None):
        self._responses = list(responses)
        self._raises = list(raises or [])
        self.calls = 0
        self.messages_history: list[list[dict]] = []

    async def __call__(self, client, model, messages, **kwargs):
        self.calls += 1
        self.messages_history.append([dict(m) for m in messages])
        if self._raises:
            raise self._raises.pop(0)
        if self._responses:
            return make_fake_completion(self._responses.pop(0))
        return make_fake_completion()


def _clear_cache():
    _INTENT_CACHE.clear()


@pytest.mark.asyncio
async def test_first_valid_intent_calls_model_once():
    _clear_cache()
    fake = FakeCaller([_valid_intent_json()])
    result = await generate_intent(_prompt(), _materials(), model_caller=fake)
    assert fake.calls == 1
    assert result.layoutIntent.groups[0].count == 2


@pytest.mark.asyncio
async def test_fifth_attempt_valid_returns_and_caches():
    _clear_cache()
    fake = FakeCaller([_invalid_json()] * 4 + [_valid_intent_json()])
    result = await generate_intent(_prompt(), _materials(), model_caller=fake)
    assert fake.calls == 5
    assert result.layoutIntent.groups[0].count == 2
    cached_fake = FakeCaller([])
    await generate_intent(_prompt(), _materials(), model_caller=cached_fake)
    assert cached_fake.calls == 0


@pytest.mark.asyncio
async def test_all_five_fail_raises_with_count_and_last_error():
    _clear_cache()
    fake = FakeCaller([_invalid_json()] * 5)
    with pytest.raises(IntentModelOutputError) as excinfo:
        await generate_intent(_prompt(), _materials(), model_caller=fake)
    assert fake.calls == 5
    assert "连续 5 次" in str(excinfo.value)
    assert excinfo.value.category == "json_parse"
    assert excinfo.value.raw_output == _invalid_json()


@pytest.mark.parametrize(
    "payload,expected_category",
    [
        (_invalid_json(), "json_parse"),
        (_structure_invalid_json(), "structure"),
        (_semantic_invalid_json(), "semantic"),
    ],
)
@pytest.mark.asyncio
async def test_each_failure_category_retries(payload, expected_category):
    _clear_cache()
    fake = FakeCaller([payload, payload, _valid_intent_json()])
    await generate_intent(_prompt(), _materials(), model_caller=fake)
    assert fake.calls == 3
    assert f"（{expected_category}）" in fake.messages_history[1][2]["content"]


@pytest.mark.asyncio
async def test_warning_only_output_passes_first_try():
    _clear_cache()
    fake = FakeCaller([_valid_intent_json()])
    result = await generate_intent(_prompt(), _materials(), model_caller=fake)
    assert fake.calls == 1
    assert result.layoutIntent.groups[0].count == 2


@pytest.mark.asyncio
async def test_correction_contains_only_latest_error_without_raw_output():
    _clear_cache()
    fake = FakeCaller([_invalid_json(), _structure_invalid_json(), _valid_intent_json()])
    await generate_intent(_prompt(), _materials(), model_caller=fake)
    assert len(fake.messages_history) == 3
    correction = fake.messages_history[2][2]["content"]
    assert "structure" in correction
    assert "json_parse" not in correction
    assert "这不是 JSON" not in correction
    assert len(fake.messages_history[1]) == 3
    assert fake.messages_history[1][2]["content"].startswith("上一次布局意图输出未通过校验")


@pytest.mark.asyncio
async def test_timeout_calls_once_and_propagates():
    _clear_cache()
    fake = FakeCaller([], raises=[IntentModelTimeoutError("布局模型请求超时")])
    with pytest.raises(IntentModelTimeoutError):
        await generate_intent(_prompt(), _materials(), model_caller=fake)
    assert fake.calls == 1


@pytest.mark.asyncio
async def test_unavailable_calls_once_and_propagates():
    _clear_cache()
    fake = FakeCaller([], raises=[RuntimeError("boom")])
    with pytest.raises(IntentModelUnavailableError):
        await generate_intent(_prompt(), _materials(), model_caller=fake)
    assert fake.calls == 1


@pytest.mark.asyncio
async def test_logs_contain_attempt_and_category_not_raw_output(caplog):
    _clear_cache()
    with caplog.at_level(logging.INFO, logger="model.layout_tools.get_intent"):
        fake = FakeCaller([_invalid_json(), _invalid_json(), _valid_intent_json()])
        await generate_intent(_prompt(), _materials(), model_caller=fake)
    records = [r.message for r in caplog.records]
    assert any("第 1/5 次尝试未通过校验" in r and "json_parse" in r for r in records)
    assert any("第 2/5 次尝试未通过校验" in r and "json_parse" in r for r in records)
    assert any("第 3/5 次尝试成功" in r for r in records)
    assert not any("这不是 JSON" in r for r in records)


@pytest.mark.asyncio
async def test_cache_hit_and_valid_rule_layout_do_not_call_model():
    _clear_cache()
    fake = FakeCaller([_valid_intent_json()])
    await generate_intent(_prompt(), _materials(), model_caller=fake)
    cached_fake = FakeCaller([])
    await generate_intent(_prompt(), _materials(), model_caller=cached_fake)
    assert cached_fake.calls == 0
    rule_fake = FakeCaller([])
    await generate_intent(_rule_prompt(), _materials(), model_caller=rule_fake)
    assert rule_fake.calls == 0


class TestLayoutRouteMapping:
    def test_final_intent_error_maps_to_502_detail(self):
        original = deps_module._layout_agent
        try:
            class StubAgent:
                async def generate(self, **kwargs):
                    raise IntentModelOutputError(
                        "布局模型输出连续 5 次未通过校验：LLM 输出无法解析为 JSON"
                    )

            deps_module._layout_agent = StubAgent()
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/api/canvas/layout",
                json={
                    "query": "test",
                    "title": "test",
                    "canvas_width": 1920,
                    "canvas_height": 1080,
                },
            )
            assert resp.status_code == 502
            assert (
                resp.json()["detail"]
                == "布局模型输出连续 5 次未通过校验：LLM 输出无法解析为 JSON"
            )
        finally:
            deps_module._layout_agent = original
