from __future__ import annotations
import base64
import mimetypes
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from model.llm_client import call_llm, default_client, default_model

PROMPT = """\
你是工业 SCADA 界面意图识别专家。根据图片生成布局意图中间表示IR的JSON文件。
"""

def _encode(image) -> str:
    path = Path(image)
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"

async def image_intent(image, prompt: str = PROMPT, client=None, model=None) -> str:
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": [{"type": "image_url", "image_url": {"url": _encode(image)}}]},
    ]
    response = await call_llm(client or default_client, model or default_model, messages)
    return response.choices[0].message.content or ""

if __name__ == "__main__":
    import asyncio
    print(asyncio.run(image_intent(sys.argv[1])))