from __future__ import annotations

import httpx
import pytest
from openai import APIConnectionError, APITimeoutError

from model.control_tools.extract import (
    EXTRACT_PROMPT,
    ControlModelOutputError,
    ControlModelTimeoutError,
    ControlModelUnavailableError,
    clear_extract_cache,
    extract_control_words,
    normalize_term,
    validate_extracted_words,
)
from tests.conftest import FakeAsyncClient, make_fake_completion


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_extract_cache()
    yield
    clear_extract_cache()


def test_validate_keeps_original_substrings_in_first_occurrence_order():
    words, errors = validate_extracted_words("显示温度和压力", ["压力", "温度"])
    assert errors == []
    assert words == ["温度", "压力"]


def test_validate_rejects_rewritten_library_word():
    words, errors = validate_extracted_words("飞机", ["风机"])
    assert words is None
    assert "词不在原文中" in errors[0]


def test_validate_rejects_substring_missing_word():
    words, errors = validate_extracted_words("飞机和水泵", ["飞机", "潜水艇"])
    assert words is None
    assert any("潜水艇" in error for error in errors)


def test_validate_dedupes_repeated_words():
    words, errors = validate_extracted_words("水泵和冷却泵", ["水泵", "水泵"])
    assert errors == []
    assert words == ["水泵"]


def test_validate_fullwidth_case_and_whitespace_normalization():
    words, errors = validate_extracted_words("Ｐｕｍｐ　和　水泵", ["pump", "水泵"])
    assert errors == []
    assert words == ["pump", "水泵"]


def test_validate_non_string_element_is_error():
    words, errors = validate_extracted_words("水泵", [123])
    assert words is None
    assert "非字符串" in errors[0]


def test_validate_non_list_structure_is_error():
    words, errors = validate_extracted_words("水泵", 5)
    assert words is None
    assert "数组" in errors[0]


def test_normalize_term_folds_whitespace_case_and_width():
    assert normalize_term("  Ｐｕｍｐ\t ") == "pump"
    assert normalize_term("温度　压力") == "温度 压力"


@pytest.mark.asyncio
async def test_extract_returns_validated_words():
    fake = FakeAsyncClient([make_fake_completion('{"controls": ["温度", "压力"]}')])
    words, hit = await extract_control_words(fake, "m", "显示温度和压力", "仪表盘、参数值")
    assert words == ["温度", "压力"]
    assert hit is False


@pytest.mark.asyncio
async def test_extract_retries_once_then_success():
    fake = FakeAsyncClient([
        make_fake_completion('{"controls": ["风机"]}'),
        make_fake_completion('{"controls": ["飞机"]}'),
    ])
    words, _ = await extract_control_words(fake, "m", "飞机", "风机、水泵")
    assert words == ["飞机"]


@pytest.mark.asyncio
async def test_extract_rewrite_twice_raises_model_output_error():
    fake = FakeAsyncClient([
        make_fake_completion('{"controls": ["风机"]}'),
        make_fake_completion('{"controls": ["风机"]}'),
    ])
    with pytest.raises(ControlModelOutputError):
        await extract_control_words(fake, "m", "飞机", "风机、水泵")


@pytest.mark.asyncio
async def test_extract_invalid_json_twice_raises_model_output_error():
    fake = FakeAsyncClient([
        make_fake_completion("not json"),
        make_fake_completion("not json"),
    ])
    with pytest.raises(ControlModelOutputError):
        await extract_control_words(fake, "m", "飞机", "风机、水泵")


@pytest.mark.asyncio
async def test_extract_invalid_structure_then_success():
    fake = FakeAsyncClient([
        make_fake_completion('{"controls": 5}'),
        make_fake_completion('{"controls": ["水泵"]}'),
    ])
    words, _ = await extract_control_words(fake, "m", "水泵", "风机、水泵")
    assert words == ["水泵"]


@pytest.mark.asyncio
async def test_extract_empty_twice_returns_empty():
    fake = FakeAsyncClient([
        make_fake_completion('{"controls": []}'),
        make_fake_completion('{"controls": []}'),
    ])
    words, _ = await extract_control_words(fake, "m", "给我一个画面", "风机、水泵")
    assert words == []


@pytest.mark.asyncio
async def test_extract_first_invalid_second_empty_returns_empty():
    fake = FakeAsyncClient([
        make_fake_completion('{"controls": ["风机"]}'),
        make_fake_completion('{"controls": []}'),
    ])
    words, _ = await extract_control_words(fake, "m", "飞机", "风机、水泵")
    assert words == []


@pytest.mark.asyncio
async def test_extract_cache_hit_skips_llm_call():
    fake = FakeAsyncClient([make_fake_completion('{"controls": ["水泵"]}')])
    words, hit = await extract_control_words(fake, "m", "水泵", "风机、水泵")
    assert words == ["水泵"]
    assert hit is False
    words2, hit2 = await extract_control_words(fake, "m", "水泵", "风机、水泵")
    assert words2 == ["水泵"]
    assert hit2 is True
    assert fake._call_count == 1


@pytest.mark.asyncio
async def test_extract_cache_key_includes_model_and_prompt_version():
    fake = FakeAsyncClient([
        make_fake_completion('{"controls": ["水泵"]}'),
        make_fake_completion('{"controls": ["水泵"]}'),
    ])
    words, _ = await extract_control_words(fake, "m1", "水泵", "风机、水泵")
    assert words == ["水泵"]
    words2, hit2 = await extract_control_words(fake, "m2", "水泵", "风机、水泵")
    assert words2 == ["水泵"]
    assert hit2 is False
    assert fake._call_count == 2


@pytest.mark.asyncio
async def test_extract_timeout_maps_to_timeout_error():
    fake = FakeAsyncClient()
    fake.set_failure(0, APITimeoutError("timeout"))
    with pytest.raises(ControlModelTimeoutError):
        await extract_control_words(fake, "m", "水泵", "风机、水泵")


@pytest.mark.asyncio
async def test_extract_connection_error_maps_to_unavailable_error():
    fake = FakeAsyncClient()
    fake.set_failure(0, APIConnectionError(request=httpx.Request("POST", "http://x")))
    with pytest.raises(ControlModelUnavailableError):
        await extract_control_words(fake, "m", "水泵", "风机、水泵")


@pytest.mark.asyncio
async def test_extract_other_error_maps_to_model_output_error():
    fake = FakeAsyncClient()
    fake.set_failure(0, ValueError("boom"))
    with pytest.raises(ControlModelOutputError):
        await extract_control_words(fake, "m", "水泵", "风机、水泵")


def test_prompt_forbids_rewriting():
    assert "禁止改写成控件库中的名称" in EXTRACT_PROMPT
    assert "温度" in EXTRACT_PROMPT
