from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import sys
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data" / "reference.png"
DEFAULT_OUTPUT_DIR = ROOT / "output"
DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/api/v1"
DEFAULT_MODEL = "qwen-image-3.0"
PROMPT_TEMPLATE = (
    "参考图仅用于提取配色、材质、边框、以及工业 SCADA / HMI 视觉语言。"
    "完全删除并替换参考图中的原主体，不得保留、复制、变形复用原主体的轮廓、部件、布局或结构。"
    "不要生成任何 UI 外壳，仅生成一个全新的“{control_name}”控件主题图标。"
    "控件外观和结构必须准确表达“{control_name}”的功能与含义。"
    "专业、简洁、可靠，正视角、主体居中、轮廓清晰，小尺寸下保持高识别度。"
    "避免卡通化、游戏化和复杂装饰、背景简洁、不包含文字、Logo 或水印，"
    "仅输出独立高精度 SCADA UI 控件。"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--name")
    parser.add_argument("--size", default="1024*1024")
    parser.add_argument("--seed", type=int, default=123456)
    parser.add_argument("--model")
    parser.add_argument("--timeout", type=float, default=300.0)
    return parser.parse_args()


def build_prompt(control_name: str) -> str:
    name = control_name.strip()
    if not name:
        raise ValueError("控件名称不能为空")
    return PROMPT_TEMPLATE.replace("{control_name}", name)


def encode_image(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"参考图片不存在: {path}")
    mime_type, _ = mimetypes.guess_type(path.name)
    if mime_type is None or not mime_type.startswith("image/"):
        raise ValueError(f"无法识别图片格式: {path}")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def build_payload(image: str, prompt: str, model: str, size: str, seed: int) -> dict:
    return {
        "model": model,
        "input": {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"image": image},
                        {"text": prompt},
                    ],
                }
            ]
        },
        "parameters": {
            "size": size,
            "n": 1,
            "prompt_extend": False,
            "watermark": False,
            "seed": seed,
        },
    }


def call_api(endpoint: str, api_key: str, payload: dict, timeout: float) -> dict:
    request = Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"API 请求失败: HTTP {exc.code} {body}") from exc
    except URLError as exc:
        raise RuntimeError(f"API 连接失败: {exc.reason}") from exc


def extract_image_url(response: dict) -> str:
    choices = response.get("output", {}).get("choices", [])
    for choice in choices:
        content = choice.get("message", {}).get("content", [])
        for item in content:
            image = item.get("image") if isinstance(item, dict) else None
            if isinstance(image, str) and image:
                return image
    code = response.get("code", "UnknownError")
    message = response.get("message", "响应中没有生成图片")
    raise RuntimeError(f"图片生成失败: {code} {message}")


def save_image(image: str, output: Path, timeout: float) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if image.startswith("data:"):
        _, encoded = image.split(",", 1)
        output.write_bytes(base64.b64decode(encoded))
        return
    try:
        with urlopen(image, timeout=timeout) as response:
            output.write_bytes(response.read())
    except HTTPError as exc:
        raise RuntimeError(f"下载生成图片失败: HTTP {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"下载生成图片失败: {exc.reason}") from exc


def default_output_path() -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return DEFAULT_OUTPUT_DIR / f"qwen_{timestamp}.png"


def main() -> int:
    load_dotenv(ROOT / ".env.local")
    args = parse_args()
    api_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        print("缺少 DASHSCOPE_API_KEY，请在项目根目录 .env.local 中配置", file=sys.stderr)
        return 1
    base_url = os.environ.get("DASHSCOPE_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    model = args.model or os.environ.get("QWEN_IMAGE_MODEL", DEFAULT_MODEL)
    endpoint = f"{base_url}/services/aigc/multimodal-generation/generation"
    output = args.output or default_output_path()
    try:
        control_name = args.name if args.name is not None else input("请输入控件名称: ")
        prompt = build_prompt(control_name)
        image = encode_image(args.input)
        payload = build_payload(image, prompt, model, args.size, args.seed)
        response = call_api(endpoint, api_key, payload, args.timeout)
        image_url = extract_image_url(response)
        save_image(image_url, output, args.timeout)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
