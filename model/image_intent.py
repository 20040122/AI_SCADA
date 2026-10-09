from __future__ import annotations
import base64
import mimetypes
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from model.llm_client import call_llm, default_client, default_model

PROMPT = """\
你是工业 SCADA 图纸结构识别器。分析输入图片中的设备、设备数量、流程方向、空间布局和连接关系，并只输出一个合法 JSON 对象。识别连接关系时必须逐条追踪可见连线，不得按行列规律推断或补全。

  deviceType 必须优先从可用设备类型中选择，并与名称完全一致。图片文字存在换行时，应合并成一个完整名称，例如“压力传\\n感器”识别为“压力传感器”。不得把箭头、连接线、边框、背景和说明文字识别
  为设备。

  输出必须严格包含以下五个字段，不得增加或遗漏字段：

  {{
    "inventory": [
      {{
        "deviceType": "设备类型",
        "count": 1
      }}
    ],
    "flow": "设备类型-设备类型",
    "structure": "设备的空间位置、排列方式以及附属设备关系",
    "piping": "设备1-设备2；设备3-设备4",
    "isolated": ["设备4"]
  }}

  识别规则：

  1. inventory
  - 统计图片中实际可见的所有设备。
  - 相同 deviceType 合并为一项，count 为图片中的总数量。
  - count 必须是大于等于 1 的整数。
  - inventory 中每种 deviceType 只能出现一次。
  - 按主设备从左到右排列；横坐标接近时从上到下排列。附属仪表排在主设备之后。
  - 不得根据常识补充图片中没有出现的设备。
  - 无任何连线的孤立设备仍需计入 inventory，但其编号不得出现在 piping 中。

  2. flow
  - 根据箭头方向生成流程链，使用半角连字符“-”连接设备类型。
  - flow 使用 deviceType，不使用实例编号。
  - 多条不同结构的流程使用中文分号“；”分隔。
  - 多个完全相同的重复支路只保留一个流程模板。
  - 同一流程中相同设备出现多次时必须重复写出。
  - 不得添加图片中没有画出的跨支路连接。

  3. structure
  - 描述主设备位于左侧、中部或右侧。
  - 描述重复主设备采用纵向、横向或网格排列。
  - 描述附属设备位于主设备的上方、右侧、下方或左侧。
  - 按箭头顺序描述同一支路上的附属设备。
  - 明确指出哪些支路彼此独立。
  - 使用确定、简短的中文陈述，不描述颜色、线宽、背景和装饰。

  4. piping
  - 展开图片中每一条实际可见的连接链，使用中文分号“；”分隔。
  - 严格按照箭头方向书写。
  - 某种 deviceType 在 inventory 中只有一个实例时，直接使用 deviceType。
  - 某种 deviceType 有多个实例时，必须使用从 1 开始的连续编号，例如“阀门1”“阀门2”。
  - 实例编号按照所属主设备从左到右、同列从上到下的支路顺序分配；同一支路内按照箭头方向分配。
  - piping 中的每个设备都必须存在于 inventory，实例编号不得超过对应 count。
  - 图片没有明确连接时，piping 输出空字符串。
  - 不得把位置接近但没有连接线的设备推断为相连。
  - 逐个实例核验：只有画面上存在实际连接线的实例才写入 piping；某实例没有连线时必须忽略，不得因同类型其他实例有连线而按规律补全。
  - 禁止矩阵补全：两组设备部分相连时，必须逐条写出真实存在的边，不得输出完整交叉矩阵。

  5. isolated
  - 必须在写出 piping 之前，逐个实例检查是否存在实际连接线。
  - 列出图片中没有任何连接线的实例名称数组，例如 ["冷冻泵4"]；没有孤立实例时输出空数组 []。
  - piping 中严禁出现 isolated 中列出的任何实例。

  6. 输出约束
  - 只输出 JSON，不要输出 Markdown、代码块、解释、前缀或后缀。
  - 所有五个字段必须存在。
  - inventory、isolated 必须是数组；flow、structure、piping 必须是字符串。
  - 不得输出 null。
  - 输出前自行核对 inventory 数量、流程链和实例编号是否一致。
  - 输出前逐一核对 piping 中每个编号：该实例附近必须存在实际连接线，否则删除。

  下面只是格式示例，不得复制其中的设备和数量：

  {{
    "inventory": [
      {{"deviceType": "示例设备A", "count": 1}},
      {{"deviceType": "示例设备B", "count": 3}}
    ],
    "flow": "示例设备A-示例设备B",
    "structure": "示例设备A位于左侧，3台示例设备B位于右侧纵向排列；示例设备B3无连接线，为孤立设备。",
    "piping": "示例设备A-示例设备B1；示例设备A-示例设备B2",
    "isolated": ["示例设备B3"]
  }}
"""

def _encode(image) -> str:
    if isinstance(image, (bytes, bytearray, memoryview)):
        return f"data:image/png;base64,{base64.b64encode(bytes(image)).decode()}"
    if isinstance(image, str) and image.startswith("data:"):
        return image
    text = image if isinstance(image, str) else str(image)
    if "\n" not in text and len(text) < 4096:
        try:
            path = Path(text)
            if path.exists() and path.is_file():
                mime = mimetypes.guess_type(path.name)[0] or "image/png"
                return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"
        except OSError:
            pass
    return f"data:image/png;base64,{text}"

IMAGE_TEMPERATURE = 0.0


async def image_intent(image, prompt: str = PROMPT, client=None, model=None) -> str:
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": [{"type": "image_url", "image_url": {"url": _encode(image)}}]},
    ]
    response = await call_llm(
        client or default_client,
        model or default_model,
        messages,
        temperature=IMAGE_TEMPERATURE,
    )
    return response.choices[0].message.content or ""

if __name__ == "__main__":
    import asyncio
    print(asyncio.run(image_intent(sys.argv[1])))