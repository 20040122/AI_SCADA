from __future__ import annotations

import argparse
import asyncio
import base64
import json
import math
import os
import sqlite3
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env.local")

from model.llm_client import call_llm, default_client, default_model


UNKNOWN_SUFFIX = "unknow"
DEFAULT_CONCURRENCY = 32
DEFAULT_CONTEXT = 0.5
TEMPERATURE = 0.0

PROMPT_TEMPLATE = """\
你是工业 SCADA 图纸控件识别器。输入是一张从图纸上裁剪出来的控件图，请判断它属于白名单中的哪一类控件，并且只输出一个合法 JSON 对象。

白名单（必须优先从中选择，名称必须与白名单逐字一致）：
{whitelist}

输出必须严格包含以下字段，不得增加或遗漏字段：

{{
  "name": "控件名"
}}

识别规则：

1. 白名单优先
- 只要裁剪图与白名单中任意一类相符，name 必须是该类名称的白名单原文。
- 禁止改写为近义词、简称、繁体、英文或带实例编号的说法。“冷却塔1”“冷却塔#1”“CoolingTower”都必须写成“冷却塔”。
- 只有与白名单所有类别都不相符时，才允许给出你自己的名称。

2. 最高优先级：读取名称文字
- SCADA 图纸会在设备正下方标注名称，例如“冷却泵#1”“冷冻泵#3”“冷水机组#1”“调节阀#4”“电动阀#2”“旁通阀#1”“流量计#1”。
- 裁剪图内或裁剪图正下方紧邻处出现这类文字时，必须先按文字判定：取名称去掉“#编号”后的类别（“冷却泵#1”判为“冷却泵”，“冷水机组#1”判为“冷水机”，“调节阀#4”判为“调节阀”），不得忽略文字另作外观推断。
- 名称文字与外观冲突时，一律以名称为准。

3. 外观特征
- 冷却泵：整体呈蓝色的立式离心泵（约 99x100 像素）。
- 冷冻泵：整体呈青绿色（蓝绿色）的立式离心泵，形状与冷却泵相同但颜色明显偏绿，不要判为冷却泵。
- 冷却塔：带圆形风扇叶片的方形塔体，尺寸较大（约 70x87 像素）。
- 冷水机：带冷凝管路的卧式机组，浅黄米色（约 174x140 像素）。
- 绿色状态：绿底白字的窄胶囊（约 65x18 像素），文字是状态词，如“运行”“开到位”“关到位”；只要是这个形状的绿色胶囊，无论文字是哪个状态词都判为绿色状态。
- 状态显示：比绿色状态更宽的开关状态条（约 70x31 像素），出现在“上电”“近控”“远控”“运行”等标签右侧。
- 按钮：成排出现的彩色圆角矩形，内部是完整操作动词短语，如“一键启动”“一键断电”“运行中加机”“运行中减机”“故障复位”“系统急停”“远/近控”“手动/自动”“一键上电”。只要内部是这类短语，一律判为按钮，不得判为状态显示。
- 数值显示：浅灰或浅蓝底矩形，内部只有短横线或数字（约 44x21 或 66x20 像素），单位（℃、Mpa、A、%、Hz、m³/h、m）通常在框外；框内不会出现阀体、泵体、风扇等设备轮廓。框内只有“---”时即使看不到单位也判为数值显示。
- 调节阀：浅灰色袖珍阀体加顶部手轮（约 20x30 像素），其上方或附近是百分号（%）数值框。
- 电动阀：浅灰色袖珍阀体，尺寸与调节阀几乎相同，其上方通常是绿色“开到位”“关到位”胶囊。
- 调节阀与电动阀外观几乎一致，只能靠名称文字或上方标识区分；两者都看不到时，选“电动阀”。
- 旁通阀：蓝色的袖珍阀体加顶部手轮（约 37x36 像素），比冷却塔小得多，附近常有百分号数值框；不得因为颜色偏蓝而判为泵，也不得因为模糊而判为冷却塔。
- 流量计：蓝色的圆形表盘加蓝色阀体，与阀门不同，名称文字为“流量计#N”。
- 室外环境图标：户外的温度、湿度、露点图标。
- 补水泵：颜色与冷冻泵接近，但泵体带补水罐，且周围没有频率、电流数值框，不要判为冷冻泵。
- 补水箱：蓝色矩形水箱，标注“总高度”“液位”。
- 以上四类若未出现在白名单中，就按“补水泵”“补水箱”“流量计”这样的常规名称输出。

4. 排除项
- 不得把背景、管线、连接线、边框、装饰条纹、纯色块当作控件。
- 裁剪图特征不明显时仍需给出最接近的白名单类别；不得使用“未知”“未识别”“其他”“无”之类的占位词。确实不属于白名单时，给出具体控件名称。

5. 输出约束
- 只输出 JSON，不要输出 Markdown、代码块、解释、前缀或后缀。
- name 必须是非空字符串。
"""


def load_whitelist(db_path: Path) -> List[str]:
    if not db_path.is_file():
        raise ValueError("白名单数据库不存在: {}".format(db_path))
    connection = None
    try:
        connection = sqlite3.connect("{}?mode=ro".format(db_path.resolve().as_uri()), uri=True)
        rows = connection.execute(
            "SELECT DISTINCT displayName FROM query_results ORDER BY displayName"
        ).fetchall()
    except sqlite3.Error as error:
        raise ValueError("无法读取 query_results 表: {}".format(error)) from error
    finally:
        if connection is not None:
            connection.close()
    names = []
    for row in rows:
        name = row[0]
        if isinstance(name, str) and name.strip():
            names.append(name.strip())
    if not names:
        raise ValueError("query_results 表为空，控件白名单不可用。")
    return names


def build_prompt(whitelist: List[str]) -> str:
    return PROMPT_TEMPLATE.format(whitelist="、".join(whitelist))


def read_inputs(image_path: Path, detections_path: Path) -> Tuple[np.ndarray, List[Dict[str, Any]]]:
    image = cv2.imdecode(np.frombuffer(image_path.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("无法解码图片: {}".format(image_path))
    items = json.loads(detections_path.read_text(encoding="utf-8"))
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise ValueError("检测 JSON 必须是元素对象数组。")
    height, width = image.shape[:2]
    identifiers = set()
    for item in items:
        identifier = item.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in identifiers:
            raise ValueError("元素必须具有非空且唯一的 id。")
        identifiers.add(identifier)
        if item.get("type") != "controls":
            continue
        box = item.get("bbox")
        if not isinstance(box, list) or len(box) != 4 or any(type(number) is not int for number in box):
            raise ValueError("{} 的 bbox 必须是四个整数 [x, y, width, height]。".format(identifier))
        x, y, w, h = box
        if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > width or y + h > height:
            raise ValueError("{} 的 bbox 超出图片范围或尺寸无效。".format(identifier))
    return image, items


def expand_bbox(image: np.ndarray, bbox: List[int], context: float) -> List[int]:
    height, width = image.shape[:2]
    x, y, w, h = bbox
    pad_x = int(round(w * context))
    pad_y = int(round(h * context))
    left = max(0, x - pad_x)
    top = max(0, y - pad_y)
    right = min(width, x + w + pad_x)
    bottom = min(height, y + h + pad_y)
    return [left, top, right - left, bottom - top]


def crop_control(image: np.ndarray, bbox: List[int], context: float = 0.0) -> np.ndarray:
    x, y, w, h = expand_bbox(image, bbox, context)
    return image[y:y + h, x:x + w]


def crop_named_control(image: np.ndarray, item: Dict[str, Any], context: float) -> np.ndarray:
    x, y, w, h = expand_bbox(image, item["bbox"], context)
    right, bottom = x + w, y + h
    for lx, ly, lw, lh in item.get("label_bboxes", []):
        x, y = min(x, max(0, lx - 3)), min(y, max(0, ly - 3))
        right, bottom = max(right, lx + lw + 3), max(bottom, ly + lh + 3)
    return image[y:min(image.shape[0], bottom), x:min(image.shape[1], right)]


def encode_image(image: np.ndarray) -> bytes:
    success, encoded = cv2.imencode(".png", image)
    if not success:
        raise ValueError("无法编码控件裁剪图。")
    return encoded.tobytes()


def encode_crop(image: np.ndarray, bbox: List[int], context: float = 0.0) -> str:
    image_bytes = encode_image(crop_control(image, bbox, context))
    return "data:image/png;base64,{}".format(base64.b64encode(image_bytes).decode("ascii"))


def write_crops(image: np.ndarray, items: List[Dict[str, Any]], directory: Path, context: float = 0.0) -> int:
    directory.mkdir(parents=True, exist_ok=True)
    written = 0
    for item in items:
        if item.get("type") != "controls":
            continue
        (directory / "{}.png".format(item["id"])).write_bytes(encode_image(crop_named_control(image, item, context)))
        written += 1
    return written


def parse_name(content: str) -> str:
    text = content.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("模型响应中没有 JSON 对象。")
    data = json.loads(text[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError("模型响应的 JSON 不是对象。")
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("模型响应的 name 字段无效。")
    return " ".join(name.split())


def normalize(name: str, whitelist: List[str]) -> str:
    if not name:
        raise ValueError("模型返回的控件名称为空。")
    if name in whitelist:
        return name
    contained = [entry for entry in whitelist if entry in name]
    if contained:
        prefixed = [entry for entry in contained if name.startswith(entry)]
        return max(prefixed or contained, key=len)
    return "{}({})".format(name, UNKNOWN_SUFFIX)


async def recognize_control(
    client: Any,
    model: str,
    semaphore: asyncio.Semaphore,
    item: Dict[str, Any],
    image: np.ndarray,
    whitelist: List[str],
    prompt: str,
    context: float,
    durations: Optional[List[float]] = None,
) -> Tuple[str, bool]:
    box = item["bbox"]
    image_bytes = encode_image(crop_named_control(image, item, context))
    url = "data:image/png;base64,{}".format(base64.b64encode(image_bytes).decode("ascii"))
    if context > 0:
        size_hint = "这是一张带上下文边距的裁剪图，其中控件本体约 {}x{} 像素。只输出 JSON。".format(box[2], box[3])
    else:
        size_hint = "该控件裁剪图尺寸：{}x{} 像素。只输出 JSON。".format(box[2], box[3])
    messages = [
        {"role": "system", "content": prompt},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": size_hint},
                {"type": "image_url", "image_url": {"url": url}},
            ],
        },
    ]
    async with semaphore:
        started = time.perf_counter()
        try:
            response = await call_llm(client, model, messages, temperature=TEMPERATURE)
        finally:
            if durations is not None:
                durations.append(round(time.perf_counter() - started, 3))
    content = response.choices[0].message.content or ""
    value = normalize(parse_name(content), whitelist)
    return value, value in whitelist


async def recognize_all(
    image: np.ndarray,
    items: List[Dict[str, Any]],
    whitelist: List[str],
    prompt: str,
    client: Any,
    model: str,
    concurrency: int,
    context: float,
) -> Dict[str, Any]:
    semaphore = asyncio.Semaphore(concurrency)
    targets = [item for item in items if item.get("type") == "controls"]
    durations: List[float] = []

    async def classify(item):
        category = item.get("semantic_name")
        if category in whitelist:
            return category, True
        category = {"value_field": "数值显示", "button": "按钮", "status": "绿色状态", "indicator": "状态显示"}.get(item.get("control_kind"))
        if category in whitelist:
            return category, True
        return await recognize_control(client, model, semaphore, item, image, whitelist, prompt, context, durations)

    results = await asyncio.gather(*[
        classify(item) for item in targets
    ], return_exceptions=True)
    groups = []
    for index, item in enumerate(targets):
        if not item.get("semantic_name") or not item.get("semantic_labels"):
            continue
        x, y, w, h = item["bbox"]
        crop = cv2.resize(image[y:y + h, x:x + w], (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32)
        key = (item["semantic_name"], tuple(item["semantic_labels"]))
        for group in groups:
            if group["key"] == key and abs(w / h - group["ratio"]) < 0.15 and np.mean(np.abs(crop - group["crop"])) < 15:
                group["indices"].append(index)
                break
        else:
            groups.append({"key": key, "ratio": w / h, "crop": crop, "indices": [index]})
    for group in groups:
        votes = Counter(results[index][0] for index in group["indices"] if not isinstance(results[index], BaseException) and results[index][1])
        if votes:
            category, count = votes.most_common(1)[0]
            if count >= 2 and count > len(group["indices"]) / 2:
                for index in group["indices"]:
                    if not isinstance(results[index], BaseException):
                        results[index] = category, True
    matched = []
    unknown = []
    failed = []
    for item, result in zip(targets, results):
        if isinstance(result, BaseException):
            failed.append(item["id"])
            continue
        value, known = result
        item["value"] = value
        if known:
            matched.append(item["id"])
        else:
            unknown.append(item["id"])
    summary = {"controls": len(targets), "matched": matched, "unknown": unknown, "failed": failed}
    if durations:
        ordered = sorted(durations)
        summary["llm_seconds"] = {
            "min": ordered[0],
            "avg": round(sum(ordered) / len(ordered), 3),
            "p95": ordered[min(len(ordered) - 1, math.ceil(len(ordered) * 0.95) - 1)],
            "max": ordered[-1],
        }
    return summary


def write_atomic(output_path: Path, items: List[Dict[str, Any]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=output_path.parent, suffix=".json", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(items, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(str(temporary), str(output_path))
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def fill_control_names(
    image: np.ndarray,
    items: List[Dict[str, Any]],
    db_path: Path,
    model: Optional[str] = None,
    concurrency: int = DEFAULT_CONCURRENCY,
    context: float = DEFAULT_CONTEXT,
    dump_crops: Optional[Path] = None,
) -> Dict[str, Any]:
    if type(concurrency) is not int or concurrency <= 0:
        raise ValueError("并发数必须是正整数。")
    if not 0.0 <= context <= 2.0:
        raise ValueError("上下文边距必须在 0 到 2.0 之间。")
    if not os.environ.get("DEEPSEEK_API_KEY", "").strip():
        raise ValueError("缺少 DEEPSEEK_API_KEY，请在项目根目录 .env.local 中配置。")
    resolved_model = model or default_model
    if not resolved_model:
        raise ValueError("缺少 DEEPSEEK_MODEL，请在项目根目录 .env.local 中配置。")
    whitelist = load_whitelist(db_path)
    prompt = build_prompt(whitelist)
    dumped = write_crops(image, items, dump_crops, context) if dump_crops is not None else 0
    summary = asyncio.run(recognize_all(image, items, whitelist, prompt, default_client, resolved_model, concurrency, context))
    return {
        "model": resolved_model,
        "whitelist": whitelist,
        "element_count": len(items),
        "context": context,
        "dump_crops": dumped,
        **summary,
    }


def refine_label_values(
    image: np.ndarray,
    items: List[Dict[str, Any]],
    model: Optional[str] = None,
    concurrency: int = DEFAULT_CONCURRENCY,
) -> Dict[str, Any]:
    label_boxes = {tuple(box) for item in items if item.get("type") == "controls" for box in item.get("label_bboxes", [])}
    controls = {item["id"]: item for item in items if item.get("type") == "controls"}
    targets = [item for item in items if item.get("type") == "text" and not item.get("vision_value") and (tuple(item["bbox"]) in label_boxes or item.get("recognition_status") == "needs_review")]
    if not targets:
        return {"labels": 0, "refined": [], "failed": []}

    async def run_all():
        semaphore = asyncio.Semaphore(concurrency)

        async def transcribe(item):
            x, y, w, h = item["bbox"]
            crop = image[max(0, y - 2):min(image.shape[0], y + h + 2), max(0, x - 2):min(image.shape[1], x + w + 2)]
            factor = max(1.0, min(4.0, 64 / crop.shape[0]))
            crop = cv2.resize(crop, None, fx=factor, fy=factor, interpolation=cv2.INTER_CUBIC)
            url = "data:image/png;base64,{}".format(base64.b64encode(encode_image(crop)).decode("ascii"))
            category = controls.get(item.get("parent_id"), {}).get("value")
            hint = "关联设备类别为 {}，仅用于辨别形近字，标签原文以图片为准。".format(category) if category else "逐字读取图片。"
            messages = [
                {"role": "system", "content": '逐字转写图片中的文字，保留原始中文、符号、# 和实例编号，不添加图中没有的标点或文字。类别参考仅用于辨别形近字，不得根据常识补写内容。只输出 JSON：{"text":"图片原文"}；不能确定时输出 {"text":null}。'},
                {"role": "user", "content": [{"type": "text", "text": hint}, {"type": "image_url", "image_url": {"url": url}}]},
            ]
            async with semaphore:
                response = await call_llm(default_client, model or default_model, messages, temperature=TEMPERATURE)
            content = response.choices[0].message.content or ""
            start, end = content.find("{"), content.rfind("}")
            if start < 0 or end <= start:
                raise ValueError("标签复核没有返回 JSON")
            value = json.loads(content[start:end + 1]).get("text")
            if not isinstance(value, str) or not value.strip():
                raise ValueError("标签复核未能确定文字")
            return value.strip()

        return await asyncio.gather(*(transcribe(item) for item in targets), return_exceptions=True)

    results = asyncio.run(run_all())
    refined, failed = [], []
    for item, result in zip(targets, results):
        if isinstance(result, BaseException):
            item["recognition_status"] = "needs_review"
            failed.append(item["id"])
        else:
            item["ocr_value"] = item.get("value")
            item["value"] = result
            item["recognition_status"] = "vision_transcribed"
            refined.append(item["id"])
    return {"labels": len(targets), "refined": refined, "failed": failed}


def run(
    image_path: Path,
    detections_path: Path,
    output_path: Path,
    db_path: Path,
    model: Optional[str] = None,
    concurrency: int = DEFAULT_CONCURRENCY,
    context: float = DEFAULT_CONTEXT,
    dump_crops: Optional[Path] = None,
) -> Dict[str, Any]:
    if output_path.resolve() in (image_path.resolve(), detections_path.resolve()):
        raise ValueError("输出路径不能覆盖输入图片或检测 JSON。")
    image, items = read_inputs(image_path, detections_path)
    result = fill_control_names(image, items, db_path, model, concurrency, context, dump_crops)
    write_atomic(output_path, items)
    return {"output": str(output_path.resolve()), **result}


def main() -> None:
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="使用 DeepSeek 视觉模型识别控件名称并回填 value")
    parser.add_argument("--image", type=Path, default=root / "data" / "output.png")
    parser.add_argument("--detections", type=Path, default=root / "opencv_output" / "detections_02.json")
    parser.add_argument("--output", type=Path, default=root / "opencv_output" / "detections_03.json")
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "sqlite" / "material.db")
    parser.add_argument("--model", default=None, help="默认取 DEEPSEEK_MODEL")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY, help="并发请求数；实测 8 约需 140 秒，32 约需 7 秒且结果一致")
    parser.add_argument("--context", type=float, default=DEFAULT_CONTEXT, help="裁剪图向四周外扩的比例，0 为紧贴 bbox；默认 0.5 以纳入设备名称文字")
    parser.add_argument("--dump-crops", type=Path, default=None, help="导出全部控件裁剪图到该目录，用于人工核对")
    args = parser.parse_args()
    try:
        result = run(
            args.image, args.detections, args.output, args.db, args.model,
            args.concurrency, args.context, args.dump_crops,
        )
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError, sqlite3.Error, cv2.error) as error:
        parser.exit(1, "控件识别失败: {}\n".format(error))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
