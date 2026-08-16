from __future__ import annotations

import json

import pytest

from data.chroma.control_chunk import QUERY_PREFIX
from model.control_agent import ControlAgent
from model.control_tools.catalog import ControlCatalogManager, CatalogCorruptError
from tests.conftest import FakeAsyncClient, FakeEmbedding, make_fake_completion

DEFAULT_CONTROLS = [
    {"displayName": "水泵", "image": "symbols/a/水泵.json", "width": 100, "height": 80},
    {"displayName": "仪表盘", "image": "symbols/a/仪表盘.json", "width": 200, "height": 200},
    {"displayName": "参数值", "image": "symbols/a/参数值.json", "width": 60, "height": 20},
    {"displayName": "风机", "image": "symbols/a/风机.json", "width": 138, "height": 115},
    {"displayName": "风机2", "image": "symbols/a/风机2.json", "width": 48, "height": 50},
    {"displayName": "鼓风机", "image": "symbols/a/鼓风机.json", "width": 100, "height": 100},
    {"displayName": "风扇", "image": "symbols/a/风扇.json", "width": 79, "height": 106},
]

DEFAULT_MAPPINGS = {
    "version": "1",
    "mappings": [
        {"term": "温度", "targets": ["仪表盘", "参数值"]},
        {"term": "压力", "targets": ["仪表盘", "参数值"]},
    ],
}


class CountingEmbedding(FakeEmbedding):
    def __init__(self):
        super().__init__()
        self.calls = 0

    def embed_query(self, input):
        self.calls += 1
        return super().embed_query(input)

    def embed_documents(self, input):
        self.calls += 1
        return super().embed_documents(input)

    def __call__(self, input):
        self.calls += 1
        return super().__call__(input)


async def _build_agent(tmp_path, fake_client, controls=None, mappings_data=None):
    controls = controls if controls is not None else DEFAULT_CONTROLS
    mappings_data = mappings_data if mappings_data is not None else DEFAULT_MAPPINGS
    jsonl = tmp_path / "control.jsonl"
    jsonl.write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in controls),
        encoding="utf-8",
    )
    mappings = tmp_path / "control_mappings.json"
    mappings.write_text(
        json.dumps(mappings_data, ensure_ascii=False),
        encoding="utf-8",
    )
    embedding = CountingEmbedding()
    manager = ControlCatalogManager(
        chroma_dir=str(tmp_path / "chroma"),
        control_jsonl_path=str(jsonl),
        mappings_path=str(mappings),
        embedding_function=embedding,
    )
    agent = ControlAgent(manager=manager, client=fake_client, model="test-model")
    await agent.init()
    return agent, manager, embedding


@pytest.mark.asyncio
async def test_plane_returns_empty_candidates_and_missed_without_vector_query(tmp_path):
    fake = FakeAsyncClient([make_fake_completion('{"controls": ["飞机"]}')])
    agent, manager, embedding = await _build_agent(tmp_path, fake)
    try:
        baseline = embedding.calls
        result = await agent.process_query("飞机")
        assert result.missed == ["飞机"]
        assert len(result.keywords) == 1
        kr = result.keywords[0]
        assert kr.keyword == "飞机"
        assert kr.candidates == []
        assert embedding.calls == baseline
    finally:
        manager.close()


@pytest.mark.asyncio
async def test_submarine_like_unconfigured_words_never_query_vector(tmp_path):
    fake = FakeAsyncClient([make_fake_completion('{"controls": ["潜水艇"]}')])
    agent, manager, embedding = await _build_agent(tmp_path, fake)
    try:
        baseline = embedding.calls
        result = await agent.process_query("潜水艇")
        assert result.missed == ["潜水艇"]
        assert result.keywords[0].candidates == []
        assert embedding.calls == baseline
    finally:
        manager.close()


@pytest.mark.asyncio
async def test_plane_and_pump_mixed(tmp_path):
    fake = FakeAsyncClient([make_fake_completion('{"controls": ["飞机", "水泵"]}')])
    agent, manager, _ = await _build_agent(tmp_path, fake)
    try:
        result = await agent.process_query("飞机和水泵")
        assert result.missed == ["飞机"]
        assert [kr.keyword for kr in result.keywords] == ["飞机", "水泵"]
        plane = result.keywords[0]
        assert plane.candidates == []
        pump = result.keywords[1]
        assert len(pump.candidates) == 3
        exact = pump.candidates[0]
        assert exact.displayName == "水泵"
        assert exact.image == "symbols/a/水泵.json"
        assert exact.source == "exact"
        assert -1.0 <= exact.similarity <= 1.0
        assert all(c.source == "vector" for c in pump.candidates[1:])
        assert all(-1.0 <= c.similarity <= 1.0 for c in pump.candidates)
    finally:
        manager.close()


@pytest.mark.asyncio
async def test_temperature_and_pressure_mapping_order_and_source(tmp_path):
    fake = FakeAsyncClient([make_fake_completion('{"controls": ["温度", "压力"]}')])
    agent, manager, embedding = await _build_agent(tmp_path, fake)
    try:
        result = await agent.process_query("显示温度和压力")
        assert result.missed == []
        assert [kr.keyword for kr in result.keywords] == ["温度", "压力"]
        for kr in result.keywords:
            assert [c.displayName for c in kr.candidates] == ["仪表盘", "参数值"]
            assert all(c.source == "mapping" for c in kr.candidates)
            for c in kr.candidates:
                distance = _query_distance(manager, kr.keyword, c.displayName)
                assert c.similarity == round(1 - distance, 4)
        assert embedding.calls > 0
    finally:
        manager.close()


@pytest.mark.asyncio
async def test_low_similarity_mapping_targets_still_returned(tmp_path):
    fake = FakeAsyncClient([make_fake_completion('{"controls": ["温度"]}')])
    agent, manager, _ = await _build_agent(tmp_path, fake)
    try:
        result = await agent.process_query("显示温度")
        kr = result.keywords[0]
        assert len(kr.candidates) == 2
        assert all(c.similarity < 0.55 for c in kr.candidates)
    finally:
        manager.close()


@pytest.mark.asyncio
async def test_fan_exact_returns_top3_with_exact_first(tmp_path):
    fake = FakeAsyncClient([make_fake_completion('{"controls": ["风机"]}')])
    agent, manager, _ = await _build_agent(tmp_path, fake)
    try:
        result = await agent.process_query("风机")
        kr = result.keywords[0]
        assert len(kr.candidates) == 3
        assert kr.candidates[0].displayName == "风机"
        assert kr.candidates[0].source == "exact"
        assert all(c.source == "vector" for c in kr.candidates[1:])
        assert all(c.displayName != "风机" for c in kr.candidates[1:])
        assert len({c.displayName for c in kr.candidates}) == 3
        assert kr.candidates[1].similarity >= kr.candidates[2].similarity
    finally:
        manager.close()


@pytest.mark.asyncio
async def test_exact_target_not_in_top3_still_first(tmp_path):
    fake = FakeAsyncClient([make_fake_completion('{"controls": ["水泵"]}')])
    agent, manager, _ = await _build_agent(tmp_path, fake)
    try:
        result = await agent.process_query("水泵")
        kr = result.keywords[0]
        assert kr.candidates[0].displayName == "水泵"
        assert kr.candidates[0].source == "exact"
        assert len(kr.candidates) <= 3
        assert all(c.displayName != "水泵" for c in kr.candidates[1:])
        assert len({c.displayName for c in kr.candidates}) == len(kr.candidates)
    finally:
        manager.close()


@pytest.mark.asyncio
async def test_duplicate_words_deduped_by_normalized_value(tmp_path):
    fake = FakeAsyncClient([make_fake_completion('{"controls": ["水泵", "水泵"]}')])
    agent, manager, _ = await _build_agent(tmp_path, fake)
    try:
        result = await agent.process_query("水泵 和 水泵")
        assert len(result.keywords) == 1
        assert result.keywords[0].keyword == "水泵"
        assert len(result.keywords[0].candidates) == 3
        assert result.keywords[0].candidates[0].displayName == "水泵"
        assert result.missed == []
    finally:
        manager.close()


@pytest.mark.asyncio
async def test_case_insensitive_exact_match(tmp_path):
    controls = list(DEFAULT_CONTROLS)
    controls.append({"displayName": "Light", "image": "symbols/a/Light.json", "width": 30, "height": 30})
    fake = FakeAsyncClient([make_fake_completion('{"controls": ["light", "水泵"]}')])
    agent, manager, _ = await _build_agent(tmp_path, fake, controls=controls)
    try:
        result = await agent.process_query("light 和 水泵")
        assert result.missed == []
        assert [kr.keyword for kr in result.keywords] == ["light", "水泵"]
        assert result.keywords[0].candidates[0].displayName == "Light"
        assert result.keywords[0].candidates[0].source == "exact"
        assert len(result.keywords[0].candidates) == 3
        assert result.keywords[1].candidates[0].displayName == "水泵"
    finally:
        manager.close()


@pytest.mark.asyncio
async def test_same_normalized_missed_word_appears_once(tmp_path):
    fake = FakeAsyncClient([make_fake_completion('{"controls": ["潜水艇", "潜水艇"]}')])
    agent, manager, _ = await _build_agent(tmp_path, fake)
    try:
        result = await agent.process_query("潜水艇 和 潜水艇")
        assert result.missed == ["潜水艇"]
        assert len(result.keywords) == 1
        assert result.keywords[0].candidates == []
    finally:
        manager.close()


@pytest.mark.asyncio
async def test_empty_extract_twice_uses_full_query_as_empty_keyword(tmp_path):
    fake = FakeAsyncClient([
        make_fake_completion('{"controls": []}'),
        make_fake_completion('{"controls": []}'),
    ])
    agent, manager, _ = await _build_agent(tmp_path, fake)
    try:
        result = await agent.process_query("给我一个画面")
        assert len(result.keywords) == 1
        assert result.keywords[0].keyword == "给我一个画面"
        assert result.keywords[0].candidates == []
        assert result.missed == ["给我一个画面"]
    finally:
        manager.close()


@pytest.mark.asyncio
async def test_catalog_corrupt_whitelist_query_raises(tmp_path):
    fake = FakeAsyncClient([make_fake_completion('{"controls": ["温度"]}')])
    agent, manager, _ = await _build_agent(tmp_path, fake)
    try:
        snap = await manager.acquire()
        snap.collection.delete(ids=["control_仪表盘"])
        manager.release(snap)
        with pytest.raises(CatalogCorruptError):
            await agent.process_query("显示温度")
    finally:
        manager.close()


def _query_distance(manager, query_text, name):
    snap = manager._current
    res = snap.collection.query(
        query_texts=[QUERY_PREFIX + query_text],
        n_results=5,
        where={"displayName": {"$in": [name]}},
    )
    return res["distances"][0][0]
