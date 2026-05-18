import warnings
warnings.simplefilter("ignore")
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI
load_dotenv(".env.local")
GENERATE_PROMPT = """\
你是画布JSON生成器。
## 画布模板
{canva_json}
## 可用控件
{controls_jsonl}
## 用户需求
{user_query}
## 生成规则
1. 输出必须是合法 JSON，不要输出任何解释、Markdown 或代码块
2. JSON 顶层结构必须包含 v、p、a、d 四个字段
3. v 固定为 "8.0.5"
4. p 从画布模板复制，保持 layers、autoAdjustIndex、hierarchicalRendering 等字段
5. a 从画布模板复制，但不要包含 width、height、contentRect
6. 所有控件必须放入 d 数组
7. d 数组中的每个控件对象格式如下：
   {{
     "c": "ht.Node",
     "i": 数字ID,
     "p": {{
       "displayName": "...",
       "image": "...",
       "position": {{
         "x": 数字,
         "y": 数字
       }}
     }}
   }}
8. 每个控件的 c 必须是 "ht.Node"
9. displayName 和 image 必须严格来自"可用控件"，不要编造名称或 image 路径
10. 每个节点需要唯一的 i 值，从 17092 开始自增
11. 主设备放在左中位置，参考坐标约为：
    {{
      "x": 252,
      "y": 402
    }}
12. 控制类控件放在右侧，纵向排列，x 约为 588，y 间距约 60
13. position 的 x/y 表示控件中心点坐标
14. 如果控件模板中提供 width、height，可以复制到该节点的 p 中；否则不要编造
15. 不要输出 contentRect，程序会自动计算
## 输出格式
只输出如下结构的合法 JSON：
{{
  "v": "8.0.5",
  "p": {{
    "layers": [
      {{
        "name": "0",
        "visible": true,
        "selectable": true,
        "movable": true,
        "editable": true
      }}
    ],
    "autoAdjustIndex": true,
    "hierarchicalRendering": true
  }},
  "a": {{
    "fitContent": true,
    "zoomable": false,
    "pannable": false
  }},
  "d": [
    ...
  ]
}}
"""

_client = OpenAI(
    api_key=os.environ.get("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com",
)

_MODEL = os.environ.get("DEEPSEEK_MODEL")

_CANVAS_JSON = Path(__file__).resolve().parent.parent / "data" / "canvas.json"


@dataclass
class GenerateResult:
    v: str
    p: dict
    a: dict = field(default_factory=dict)
    d: list[dict] = field(default_factory=list)


def generate_canvas(query: str, controls: list[dict]) -> GenerateResult:
    canvas_template = _CANVAS_JSON.read_text(encoding="utf-8")
    controls_jsonl = "\n".join(json.dumps(c, ensure_ascii=False) for c in controls)
    prompt = GENERATE_PROMPT.format(
        canva_json=canvas_template,
        controls_jsonl=controls_jsonl,
        user_query=query,
    )
    response = _client.chat.completions.create(
        model=_MODEL,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": query},
        ],
        stream=False,
        reasoning_effort="high",
        response_format={"type": "json_object"},
        extra_body={"thinking": {"type": "enabled"}},
    )
    data = json.loads(response.choices[0].message.content)
    return GenerateResult(
        v=data["v"],
        p=data["p"],
        a=data.get("a", {}),
        d=data.get("d", []),
    )

if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from model.intent_agent import analyze_intent
    from model.search_service import search_controls
    query = input("输入您的需求: ")
    intent = analyze_intent(query)
    all_controls = []
    for ctrl in intent.controls:
        results = search_controls([ctrl.name])
        if ctrl.name in results:
            meta = results[ctrl.name]["metadata"]
            for _ in range(ctrl.count):
                all_controls.append(meta)
    for kw in intent.queries:
        if kw not in {c["displayName"] for c in all_controls}:
            results = search_controls([kw])
            if kw in results:
                all_controls.append(results[kw]["metadata"])
    result = generate_canvas(query, all_controls)
    print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))