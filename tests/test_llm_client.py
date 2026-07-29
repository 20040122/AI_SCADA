from __future__ import annotations

import pytest
from openai import APIConnectionError, APITimeoutError, RateLimitError

from model.llm_client import call_llm

from tests.conftest import FakeAsyncClient, make_fake_completion


def _rate_limit_error():
    try:
        raise RateLimitError(
            "rate limited",
            response=type("R", (), {"status_code": 429, "headers": {}, "text": "", "request": type("RQ", (), {})()})(),
            body='{"error": {"message": "rate limited"}}',
        )
    except RateLimitError as e:
        return e


def _connection_error():
    try:
        raise APIConnectionError(
            message="connection failed",
            request=type("RQ", (), {})(),
        )
    except APIConnectionError as e:
        return e


@pytest.mark.asyncio
async def test_call_llm_success():
    client = FakeAsyncClient([make_fake_completion('{"ok": true}')])
    resp = await call_llm(client, "test-model", [{"role": "user", "content": "hi"}])
    assert resp.choices[0].message.content == '{"ok": true}'


@pytest.mark.asyncio
async def test_call_llm_retry_then_succeed():
    client = FakeAsyncClient([make_fake_completion("ok")])
    client.fail_times(2, APITimeoutError("timeout"))
    resp = await call_llm(client, "test-model", [{"role": "user", "content": "hi"}])
    assert resp.choices[0].message.content == "ok"
    assert client._call_count == 3


@pytest.mark.asyncio
async def test_call_llm_all_retries_exhausted():
    client = FakeAsyncClient()
    client.fail_times(3, APITimeoutError("timeout"))
    with pytest.raises(APITimeoutError):
        await call_llm(client, "test-model", [{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_non_retryable_exception_not_retried():
    client = FakeAsyncClient()
    client.fail_times(1, ValueError("not retryable"))
    with pytest.raises(ValueError):
        await call_llm(client, "test-model", [{"role": "user", "content": "hi"}])
    assert client._call_count == 1


@pytest.mark.asyncio
async def test_retry_on_rate_limit():
    client = FakeAsyncClient([make_fake_completion("ok")])
    client.fail_times(1, _rate_limit_error())
    resp = await call_llm(client, "test-model", [{"role": "user", "content": "hi"}])
    assert resp.choices[0].message.content == "ok"
    assert client._call_count == 2


@pytest.mark.asyncio
async def test_retry_on_connection_error():
    client = FakeAsyncClient([make_fake_completion("ok")])
    client.fail_times(1, _connection_error())
    resp = await call_llm(client, "test-model", [{"role": "user", "content": "hi"}])
    assert resp.choices[0].message.content == "ok"
    assert client._call_count == 2
