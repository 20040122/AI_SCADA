import sys
import warnings
warnings.simplefilter("ignore")
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
import logging
import os
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
)
_MODEL = os.environ.get("DEEPSEEK_MODEL")


@dataclass
class ControlIntent:
    name: str
    count: int


@dataclass
class ControlAgentResult:
    controls: list[dict] = field(default_factory=list)
    missed: list[str] = field(default_factory=list)


class ControlAgent:
    def __init__(self):
        self._db = MaterialDB()
        self._db.init_db()
        self._control_names = ControlChunk().get_raw_controls()
        self._control_names_str = "、".join(c["displayName"] for c in self._control_names)

    def process_query(self, query: str) -> ControlAgentResult:
        self._db.clear_query_results()
        logger.info("🔍 ControlAgent 流程")
        logger.info("━" * 40)
        logger.info("📝 用户输入: %s", query)

        control_intents = self._extract_controls(query)
        intent_str = ", ".join(f"{c.name}x{c.count}" for c in control_intents)
        logger.info("🤖 LLM提取: %s", intent_str)

        keywords = [c.name for c in control_intents]
        count_map = {c.name: c.count for c in control_intents}
        search_results = search_controls_with_threshold(keywords)
        matched_controls: list[dict] = []
        matched_names: set[str] = set()
        missed: list[str] = []

        logger.info("━" * 40)
        for keyword, result in search_results.items():
            name = result["metadata"]["displayName"]
            sim = result["similarity"]
            if result["matched"]:
                count = count_map.get(keyword, 1)
                if result["metadata"]["displayName"] not in matched_names:
                    logger.info("🔎 向量检索 \"%s\": ✅ %s  (sim=%.4f, ≥0.55)", keyword, name, sim)
                    meta = result["metadata"]
                    for _ in range(count):
                        matched_controls.append(meta)
                    matched_names.add(meta["displayName"])
                else:
                    logger.info("🔎 向量检索 \"%s\": ⏭️ %s  (已匹配, 跳过)", keyword, name)
            else:
                logger.info("🔎 向量检索 \"%s\": ❌ %s  (sim=%.4f, <0.55)", keyword, name, sim)
                db_results = self._db.search_by_name(keyword)
                if db_results:
                    count = count_map.get(keyword, 1)
                    matched_in_db = []
                    for item in db_results:
                        if item["displayName"] not in matched_names:
                            matched_in_db.append(item["displayName"])
                            for _ in range(count):
                                matched_controls.append(item)
                            matched_names.add(item["displayName"])
                    if matched_in_db:
                        logger.info("💾 SQLite兜底 \"%s\": ✅ %s", keyword, ", ".join(matched_in_db))
                    else:
                        logger.info("💾 SQLite兜底 \"%s\": ⏭️ (已匹配, 跳过)", keyword)
                else:
                    logger.info("💾 SQLite兜底 \"%s\": ❌ 无结果", keyword)
                    if keyword not in missed:
                        missed.append(keyword)

        logger.info("━" * 40)
        control_summary = ", ".join(
            f"{name}x{matched_controls.count(next(c for c in matched_controls if c['displayName'] == name))}"
            for name in matched_names
        )
        logger.info("✅ 匹配 %d 个控件: %s", len(matched_controls), ", ".join(
            f"{n}x{sum(1 for c in matched_controls if c['displayName'] == n)}"
            for n in matched_names
        ))
        if missed:
            logger.info("❌ 未命中: %s", ", ".join(missed))

        result = ControlAgentResult(
            controls=matched_controls,
            missed=missed,
        )
        self._db.save_query_result(query, matched_controls)
        return result

    def _extract_controls(self, query: str) -> list[ControlIntent]:
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
        return [ControlIntent(**c) for c in data.get("controls", [])]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    agent = ControlAgent()
    query = input("AI检索: ")
    result = agent.process_query(query)

    print(f"\n匹配到的控件 ({len(result.controls)}):")
    for ctrl in result.controls:
        print(f"  {ctrl['displayName']} | {ctrl.get('image', '')} | "
              f"{ctrl.get('width', 0)}x{ctrl.get('height', 0)}")
    if result.missed:
        print(f"\n未命中的检索词: {result.missed}")