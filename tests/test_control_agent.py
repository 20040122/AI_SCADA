from types import SimpleNamespace

import pytest

import model.control_agent as control_agent_module
from app.schemas import KeywordResult as ApiKeywordResult
from model.control_agent import ControlAgent, KeywordResult


class FakeCompletions:
    async def create(self, **kwargs):
        message = SimpleNamespace(
            content='{"controls": [" 水泵 ", "水泵", "指示灯", "", 1]}'
        )
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeClient:
    def __init__(self):
        self.chat = SimpleNamespace(completions=FakeCompletions())


@pytest.mark.asyncio
async def test_extract_control_names_cleans_deduplicates_and_caches(monkeypatch):
    control_agent_module._extract_cache.clear()
    monkeypatch.setattr(control_agent_module, "_client", FakeClient())
    agent = ControlAgent(db=object())
    agent._control_names_str = "水泵、指示灯"

    first, first_cache_hit = await agent._extract_control_names("两个水泵和一个指示灯")
    second, second_cache_hit = await agent._extract_control_names("两个水泵和一个指示灯")

    assert first == ["水泵", "指示灯"]
    assert first_cache_hit is False
    assert second == first
    assert second_cache_hit is True


def test_keyword_result_has_no_count():
    domain_result = KeywordResult(keyword="水泵")
    api_result = ApiKeywordResult(keyword="水泵")

    assert not hasattr(domain_result, "count")
    assert "count" not in api_result.model_dump()
