from __future__ import annotations

import pytest

from model.refine_agent import RefineAgent
from model.validate_agent import ValidateAgent

from tests.conftest import FakeAsyncClient, make_fake_completion


@pytest.mark.asyncio
async def test_refine_agent_importable():
    from model.refine_agent import RefineAgent
    assert RefineAgent is not None


@pytest.mark.asyncio
async def test_validate_agent_importable():
    from model.validate_agent import ValidateAgent
    assert ValidateAgent is not None


@pytest.mark.asyncio
async def test_validate_agent_returns_expected_structure():
    fake = FakeAsyncClient([make_fake_completion(
        '{"valid": true, "summary": "ok", "errors": [], "warnings": []}'
    )])
    agent = ValidateAgent(client=fake)
    result = await agent.validate("canvas", {"test": True})
    assert "valid" in result
    assert "summary" in result
    assert "errors" in result
    assert "warnings" in result
    assert result["valid"] is True


@pytest.mark.asyncio
async def test_validate_agent_returns_expected_structure_with_errors():
    fake = FakeAsyncClient([make_fake_completion(
        '{"valid": false, "summary": "has issues", "errors": [{"path": "x", "message": "bad"}], "warnings": []}'
    )])
    agent = ValidateAgent(client=fake)
    result = await agent.validate("canvas", {"test": True})
    assert result["valid"] is False
    assert len(result["errors"]) == 1


@pytest.mark.asyncio
async def test_refine_agent_returns_patch():
    json_data = {
        "a": {"width": 1920, "height": 1080},
        "d": [
            {
                "i": 1,
                "a": {"layout.node": True},
                "p": {"displayName": "阀", "position": {"x": 100, "y": 200}, "width": 60, "height": 40},
            }
        ],
    }
    fake = FakeAsyncClient([make_fake_completion(
        '{"actions": [{"type": "move", "target_ids": [1], "dx": 10, "dy": 0}], "message": "moved"}'
    )])
    agent = RefineAgent(client=fake)
    result = await agent.refine("move left", json_data)
    assert hasattr(result, "patch")
    assert hasattr(result, "message")
    assert len(result.patch) > 0


@pytest.mark.asyncio
async def test_refine_agent_input_error():
    with pytest.raises(Exception):
        agent = RefineAgent(client=FakeAsyncClient())
        await agent.refine("", {})


@pytest.mark.asyncio
async def test_validate_agent_unknown_category():
    fake = FakeAsyncClient([make_fake_completion(
        '{"valid": false, "summary": "unknown", "errors": [], "warnings": []}'
    )])
    agent = ValidateAgent(client=fake)
    result = await agent.validate("unknown_cat", {})
    assert "valid" in result
    assert "summary" in result
    assert "errors" in result
    assert "warnings" in result
