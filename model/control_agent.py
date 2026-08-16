from __future__ import annotations
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional
from data.chroma.control_chunk import QUERY_PREFIX
from model.control_tools.catalog import ControlCatalogManager, CatalogCorruptError
from model.control_tools.extract import extract_control_words, normalize_term
from model.llm_client import default_client, default_model
logger = logging.getLogger(__name__)


@dataclass
class ControlCandidate:
    displayName: str
    image: str
    width: float
    height: float
    similarity: float
    source: str


@dataclass
class KeywordResult:
    keyword: str
    candidates: list[ControlCandidate] = field(default_factory=list)


@dataclass
class ControlAgentResult:
    keywords: list[KeywordResult] = field(default_factory=list)
    missed: list[str] = field(default_factory=list)


class ControlAgent:
    def __init__(
        self,
        manager: Optional[ControlCatalogManager] = None,
        client=None,
        model=None,
    ):
        self._manager = manager
        self._client = client if client is not None else default_client
        self._model = model if model is not None else default_model

    async def init(self) -> None:
        if self._manager is not None:
            await asyncio.to_thread(self._manager.load_initial)

    async def process_query(self, query: str) -> ControlAgentResult:
        snap = await self._manager.acquire()
        try:
            return await self._process(snap, query)
        finally:
            self._manager.release(snap)

    async def _process(self, snap, query: str) -> ControlAgentResult:
        names_str = "、".join(snap.names)
        keywords, cache_hit = await self._extract_control_names(query, names_str)
        cache_tag = " (缓存命中)" if cache_hit else ""
        logger.info("LLM提取: %s%s", ", ".join(keywords), cache_tag)

        keyword_results: list[KeywordResult] = []
        missed: list[str] = []
        missed_norms: set[str] = set()

        for word in keywords:
            norm = normalize_term(word)
            if norm in snap.controls_by_norm:
                target = snap.controls_by_norm[norm]
                candidates = await self._query_exact_top3(snap, word, target)
            elif norm in snap.mappings:
                whitelist = snap.mappings[norm]
                candidates = await self._query_whitelist(snap, word, whitelist, "mapping")
            else:
                keyword_results.append(KeywordResult(keyword=word, candidates=[]))
                if norm not in missed_norms:
                    missed.append(word)
                    missed_norms.add(norm)
                continue
            keyword_results.append(KeywordResult(keyword=word, candidates=candidates))

        if not keywords and query.strip():
            keyword_results.append(KeywordResult(keyword=query, candidates=[]))
            if query not in missed:
                missed.append(query)

        total = sum(len(kr.candidates) for kr in keyword_results)
        logger.info("返回 %d 个关键词, %d 个候选项", len(keyword_results), total)
        if missed:
            logger.info("未命中: %s", ", ".join(missed))

        return ControlAgentResult(
            keywords=keyword_results,
            missed=missed,
        )

    async def _query_exact_top3(self, snap, query_text: str, target: dict):
        prefixed = QUERY_PREFIX + query_text
        result = await asyncio.to_thread(
            snap.collection.query,
            query_texts=[prefixed],
            n_results=3,
        )
        metadatas = result["metadatas"][0] if result.get("metadatas") else []
        distances = result["distances"][0] if result.get("distances") else []
        by_name = {}
        for meta, distance in zip(metadatas, distances):
            by_name[meta["displayName"]] = distance
        exact_name = target["displayName"]
        exact_similarity = 1.0
        if exact_name in by_name:
            exact_similarity = round(1 - by_name[exact_name], 4)
        candidates = [ControlCandidate(
            displayName=exact_name,
            image=target.get("image", ""),
            width=target.get("width") or 0,
            height=target.get("height") or 0,
            similarity=exact_similarity,
            source="exact",
        )]
        for meta, distance in zip(metadatas, distances):
            name = meta["displayName"]
            if name == exact_name:
                continue
            candidates.append(ControlCandidate(
                displayName=name,
                image=meta.get("image", ""),
                width=meta.get("width") or 0,
                height=meta.get("height") or 0,
                similarity=round(1 - distance, 4),
                source="vector",
            ))
            if len(candidates) >= 3:
                break
        return candidates

    async def _query_whitelist(self, snap, query_text: str, whitelist: list[str], source: str):
        n = len(whitelist)
        prefixed = QUERY_PREFIX + query_text
        result = await asyncio.to_thread(
            snap.collection.query,
            query_texts=[prefixed],
            n_results=n,
            where={"displayName": {"$in": whitelist}},
        )
        ids = result["ids"][0] if result.get("ids") else []
        metadatas = result["metadatas"][0] if result.get("metadatas") else []
        distances = result["distances"][0] if result.get("distances") else []
        if len(ids) != n or len(metadatas) != n or len(distances) != n:
            raise CatalogCorruptError("白名单查询结果不完整")
        got_names = [meta["displayName"] for meta in metadatas]
        if set(got_names) != set(whitelist):
            raise CatalogCorruptError("白名单查询结果与授权目标不一致")
        by_name = {meta["displayName"]: (meta, distance) for meta, distance in zip(metadatas, distances)}
        candidates = []
        for name in whitelist:
            meta, distance = by_name[name]
            candidates.append(ControlCandidate(
                displayName=name,
                image=meta.get("image", ""),
                width=meta.get("width") or 0,
                height=meta.get("height") or 0,
                similarity=round(1 - distance, 4),
                source=source,
            ))
        return candidates

    async def _extract_control_names(self, query: str, names_str: str) -> tuple[list[str], bool]:
        return await extract_control_words(
            self._client, self._model, query, names_str
        )
