import warnings
warnings.simplefilter("ignore")
import json
import os
from dataclasses import dataclass, field
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(".env.local")
INTENT_PROMPT = """\
提取控件关键词
需求: {query}
输出(JSON):
{{
  "queries": ["关键词1", "关键词2", ...],
  "controls": [
    {{"name": "控件名", "count": 1}}
  ]
}}
"""

_client = OpenAI(
    api_key=os.environ.get("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com",
)
_MODEL = os.environ.get("DEEPSEEK_MODEL")


@dataclass
class ControlIntent:
    name: str
    count: int


@dataclass
class IntentResult:
    queries: list[str] = field(default_factory=list)
    controls: list[ControlIntent] = field(default_factory=list)


def analyze_intent(query: str) -> IntentResult:
    response = _client.chat.completions.create(
        model=_MODEL,
        messages=[
            {"role": "system", "content": INTENT_PROMPT},
            {"role": "user", "content": query},
        ],
        stream=False,
        reasoning_effort="low",
        response_format={"type": "json_object"},
        extra_body={"thinking": {"type": "enabled"}},
    )
    data = json.loads(response.choices[0].message.content)
    return IntentResult(
        queries=data.get("queries", []),
        controls=[ControlIntent(**c) for c in data.get("controls", [])],
    )


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from model.search_service import search_controls

    query = input("请输入需求: ")
    intent = analyze_intent(query)

    print(f"\nqueries: {intent.queries}")
    for ctrl in intent.controls:
        print(f"control: {ctrl.name} x{ctrl.count}")

    if intent.queries:
        results = search_controls(intent.queries)
        print("\n检索结果:")
        for keyword, r in results.items():
            meta = r["metadata"]
            print(f"『{keyword}』→ {meta['displayName']}  (距离: {r['distance']:.4f})")
            print(f"   资源: {meta['image']} | 尺寸: {meta['width']}x{meta['height']}")