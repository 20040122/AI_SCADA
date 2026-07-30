from __future__ import annotations
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Optional
from dotenv import load_dotenv
from openai import AsyncOpenAI
from data.sqlite.material_db import MaterialDB
from model.control_tools.search_service import search_controls_with_threshold
logger = logging.getLogger(__name__)
load_dotenv(".env.local")

EXTRACT_PROMPT = """\
你是工业SCADA控件检索专家。从用户的自然语言描述中提取所需的控件名称。
控件库中可用的控件名称列表：
{control_names}
提取要求：
1. 控件名称必须优先从上方列表中选取
2. 若用户描述的控件不在列表中，提取最接近的名称用于模糊检索
3. 忽略用户描述中的数量，同一个控件名称只输出一次
示例：
用户: 2个指示灯和1个水泵
输出: {{"controls": ["指示灯", "水泵"]}}
用户: 组态画面需要显示温度和压力
输出: {{"controls": ["仪表盘", "参数值"]}}
输出JSON:
{{"controls": ["控件名"]}}
"""
_client = AsyncOpenAI(
    api_key=os.environ.get("DEEPSEEK_API_KEY"),
    base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    timeout=20.0,
)
_MODEL = os.environ.get("DEEPSEEK_MODEL")


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
    def __init__(self, db: Optional[MaterialDB] = None):
        self._db = db or MaterialDB()

    async def init(self) -> None:
        await self._db.init_db()
        from data.chroma import ControlChunk
        chunk = ControlChunk()
        self._control_names = chunk.get_raw_controls()
        self._control_names_str = "、".join(c["displayName"] for c in self._control_names)

    async def process_query(self, query: str) -> ControlAgentResult:
        keywords, cache_hit = await self._extract_control_names(query)
        cache_tag = " (缓存命中)" if cache_hit else ""
        logger.info("LLM提取: %s%s", ", ".join(keywords), cache_tag)

        search_results = await search_controls_with_threshold(keywords)
        keyword_results: list[KeywordResult] = []
        missed: list[str] = []

        for keyword, candidates in search_results.items():
            all_candidates: list[ControlCandidate] = []

            vector_hit = False
            for c in candidates:
                meta = c["metadata"]
                sim = c["similarity"]
                if c["matched"]:
                    vector_hit = True
                all_candidates.append(ControlCandidate(
                    displayName=meta.get("displayName", ""),
                    image=meta.get("image", ""),
                    width=meta.get("width") or 0,
                    height=meta.get("height") or 0,
                    similarity=sim,
                    source=c["source"],
                ))

            if not vector_hit:
                logger.debug("向量检索 \"%s\": 无命中 (sim < 0.55)", keyword)
                await self._db.sync_if_needed()
                db_results = await self._db.search_by_name(keyword)
                if db_results:
                    for item in db_results:
                        logger.debug("SQLite兜底 \"%s\": %s", keyword, item["displayName"])
                        all_candidates.append(ControlCandidate(
                            displayName=item.get("displayName", ""),
                            image=item.get("image", ""),
                            width=item.get("width") or 0,
                            height=item.get("height") or 0,
                            similarity=0.0,
                            source="sqlite",
                        ))
                    sqlite_names = [d.get("displayName", "") for d in db_results]
                    logger.info("检索 \"%s\": 向量未命中, SQLite兜底 %s", keyword, ", ".join(sqlite_names))
                else:
                    logger.info("检索 \"%s\": 无结果", keyword)
                    if keyword not in missed:
                        missed.append(keyword)
            else:
                matched_names = [c.displayName for c in all_candidates if c.similarity >= 0.55]
                logger.info("检索 \"%s\": %s", keyword, ", ".join(matched_names))

            seen = set()
            unique_candidates = []
            for c in all_candidates:
                if c.displayName not in seen:
                    unique_candidates.append(c)
                    seen.add(c.displayName)

            keyword_results.append(KeywordResult(
                keyword=keyword,
                candidates=unique_candidates[:5],
            ))

        total = sum(len(kr.candidates) for kr in keyword_results)
        logger.info("返回 %d 个关键词, %d 个候选项", len(keyword_results), total)
        if missed:
            logger.info("未命中: %s", ", ".join(missed))

        return ControlAgentResult(
            keywords=keyword_results,
            missed=missed,
        )

    async def _extract_control_names(self, query: str) -> tuple[list[str], bool]:
        cached = _extract_control_names_cached(query, self._control_names_str)
        if cached is not None:
            return cached, True
        prompt = EXTRACT_PROMPT.format(control_names=self._control_names_str)
        response = await _client.chat.completions.create(
            model=_MODEL,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": query},
            ],
            stream=False,
            reasoning_effort="low",
            response_format={"type": "json_object"},
            extra_body={"thinking": {"type": "enabled"}},
        )
        data = json.loads(response.choices[0].message.content)
        control_names = []
        seen = set()
        for value in data.get("controls", []):
            if not isinstance(value, str):
                continue
            name = value.strip()
            if name and name not in seen:
                control_names.append(name)
                seen.add(name)
        _extract_cache[(query, self._control_names_str)] = control_names.copy()
        return control_names, False

_extract_cache: dict = {}

def _extract_control_names_cached(query: str, control_names_str: str) -> Optional[list[str]]:
    key = (query, control_names_str)
    if key in _extract_cache:
        return _extract_cache[key]
    return None
