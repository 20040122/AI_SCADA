import sys
import warnings
warnings.simplefilter("ignore")
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
import logging
import os
from typing import List, Optional, Tuple
from dataclasses import dataclass, field
from dotenv import load_dotenv
from openai import OpenAI

from data.material_db import MaterialDB
from data.chroma import ControlChunk
from model.search_service import search_controls_with_threshold

logger = logging.getLogger(__name__)

load_dotenv(".env.local")

EXTRACT_PROMPT = """\
你是工业SCADA控件检索专家。从用户的自然语言描述中提取所需的控件关键词及数量。

控件库中可用的控件名称列表：
{control_names}

提取要求：
1. 从用户描述中提取控件关键词，关键词必须优先从上方列表中选取
2. 若用户描述的控件不在列表中，提取最接近的关键词用于模糊检索
3. 若用户未指定数量则默认为1

示例：
用户: 2个指示灯和1个水泵
输出: {{"controls": [{{"name": "指示灯", "count": 2}}, {{"name": "水泵", "count": 1}}]}}

用户: 组态画面需要显示温度和压力
输出: {{"controls": [{{"name": "仪表盘", "count": 1}}, {{"name": "参数值", "count": 2}}]}}

输出JSON:
{{"controls": [{{"name": "关键词", "count": 数量}}]}}
"""

_client = OpenAI(
    api_key=os.environ.get("DEEPSEEK_API_KEY"),
    base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    timeout=50.0,
)
_MODEL = os.environ.get("DEEPSEEK_MODEL")


@dataclass
class ControlIntent:
    name: str
    count: int


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
    count: int
    candidates: list[ControlCandidate] = field(default_factory=list)


@dataclass
class ControlAgentResult:
    keywords: list[KeywordResult] = field(default_factory=list)
    missed: list[str] = field(default_factory=list)


class ControlAgent:
    def __init__(self, db: Optional[MaterialDB] = None):
        self._db = db or MaterialDB()
        self._db.init_db()
        self._control_names = ControlChunk().get_raw_controls()
        self._control_names_str = "、".join(c["displayName"] for c in self._control_names)

    def process_query(self, query: str) -> ControlAgentResult:
        logger.info("向量检索流程")
        logger.info("━" * 40)

        control_intents, cache_hit = self._extract_controls(query)
        if cache_hit:
            logger.info("🤖 LLM提取: %s (缓存命中)", ", ".join(f"{c.name}x{c.count}" for c in control_intents))
        else:
            logger.info("🤖 LLM提取: %s", ", ".join(f"{c.name}x{c.count}" for c in control_intents))

        keywords = [c.name for c in control_intents]
        count_map = {c.name: c.count for c in control_intents}
        search_results = search_controls_with_threshold(keywords)
        keyword_results: list[KeywordResult] = []
        missed: list[str] = []

        logger.info("━" * 40)
        for keyword, candidates in search_results.items():
            count = count_map.get(keyword, 1)
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
                logger.info("🔎 向量检索 \"%s\": ❌ 无命中 (sim < 0.55)", keyword)
                db_results = self._db.search_by_name(keyword)
                if db_results:
                    for item in db_results:
                        logger.info("💾 SQLite兜底 \"%s\": ✅ %s", keyword, item["displayName"])
                        all_candidates.append(ControlCandidate(
                            displayName=item.get("displayName", ""),
                            image=item.get("image", ""),
                            width=item.get("width") or 0,
                            height=item.get("height") or 0,
                            similarity=0.0,
                            source="sqlite",
                        ))
                else:
                    logger.info("💾 SQLite兜底 \"%s\": ❌ 无结果", keyword)
                    if keyword not in missed:
                        missed.append(keyword)
            else:
                matched_names = [c.displayName for c in all_candidates if c.similarity >= 0.55]
                logger.info("🔎 向量检索 \"%s\": ✅ %s", keyword, ", ".join(matched_names))

            seen = set()
            unique_candidates = []
            for c in all_candidates:
                if c.displayName not in seen:
                    unique_candidates.append(c)
                    seen.add(c.displayName)

            keyword_results.append(KeywordResult(
                keyword=keyword,
                count=count,
                candidates=unique_candidates[:5],
            ))

        logger.info("━" * 40)
        total = sum(len(kr.candidates) for kr in keyword_results)
        logger.info("✅ 返回 %d 个关键词, %d 个候选项", len(keyword_results), total)
        if missed:
            logger.info("❌ 未命中: %s", ", ".join(missed))

        return ControlAgentResult(
            keywords=keyword_results,
            missed=missed,
        )

    def _extract_controls(self, query: str) -> Tuple[List[ControlIntent], bool]:
        cached = _extract_controls_cached(query, self._control_names_str)
        if cached is not None:
            return [ControlIntent(name=c[0], count=c[1]) for c in cached], True
        prompt = EXTRACT_PROMPT.format(control_names=self._control_names_str)
        response = _client.chat.completions.create(
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
        intents = [ControlIntent(**c) for c in data.get("controls", [])]
        _extract_cache[(query, self._control_names_str)] = [
            (c.name, c.count) for c in intents
        ]
        return intents, False


_extract_cache: dict = {}


def _extract_controls_cached(query: str, control_names_str: str) -> Optional[List[Tuple[str, int]]]:
    key = (query, control_names_str)
    if key in _extract_cache:
        return _extract_cache[key]
    return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    agent = ControlAgent()
    while True:
        try:
            query = input("\nAI检索 (q退出): ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not query or query.lower() == "q":
            break
        result = agent.process_query(query)

        for kr in result.keywords:
            print(f"\n  [{kr.keyword}] x{kr.count} ({len(kr.candidates)} 候选)")
            for c in kr.candidates:
                print(f"    {c.displayName} | sim={c.similarity:.4f} | src={c.source}")
        if result.missed:
            print(f"\n未命中的检索词: {result.missed}")