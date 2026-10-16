import argparse
import csv
import io
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, List, Tuple

import cv2
import numpy as np


CJK = "\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"


@dataclass(frozen=True)
class Recognition:
    value: str
    confidence: float
    passes: int = 1


def normalize_text(value: str) -> str:
    value = " ".join(value.split())
    value = re.sub(r"(?<=[" + CJK + r"])\s+(?=[" + CJK + r"])", "", value)
    return re.sub(r"\s+([,.;:!?，。；：！？])", r"\1", value)


def parse_tsv(value: str) -> Recognition:
    lines = {}
    scores = []
    for row in csv.DictReader(io.StringIO(value), delimiter="\t"):
        word = (row.get("text") or "").strip()
        if row.get("level") != "5" or not word:
            continue
        score = float(row["conf"])
        if not math.isfinite(score) or score < 0:
            continue
        key = tuple(row[name] for name in ("page_num", "block_num", "par_num", "line_num"))
        lines.setdefault(key, []).append(row)
        scores.append(score)
    values = []
    for words in lines.values():
        words.sort(key=lambda row: int(row["left"]))
        parts = []
        previous = None
        for word in words:
            text = word["text"].strip()
            if previous is not None:
                gap = int(word["left"]) - int(previous["left"]) - int(previous["width"])
                height = min(int(word["height"]), int(previous["height"]))
                compact = re.search("[" + CJK + "]", previous["text"] + text) and gap <= height * 0.25
                if not compact:
                    parts.append(" ")
            parts.append(text)
            previous = word
        values.append(normalize_text("".join(parts)))
    return Recognition("\n".join(values), sum(scores) / len(scores) if scores else 0.0)


def read_inputs(image_path: Path, detections_path: Path) -> Tuple[np.ndarray, List[Dict[str, Any]]]:
    image = cv2.imdecode(np.frombuffer(image_path.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("无法解码图片: {}".format(image_path))
    items = json.loads(detections_path.read_text(encoding="utf-8"))
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise ValueError("检测 JSON 必须是元素对象数组。")
    height, width = image.shape[:2]
    text_ids = set()
    for item in items:
        if item.get("type") != "text":
            continue
        identifier = item.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in text_ids:
            raise ValueError("文字元素必须具有非空且唯一的 id。")
        text_ids.add(identifier)
        box = item.get("bbox")
        if not isinstance(box, list) or len(box) != 4 or any(type(number) is not int for number in box):
            raise ValueError("{} 的 bbox 必须是四个整数 [x, y, width, height]。".format(identifier))
        x, y, w, h = box
        if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > width or y + h > height:
            raise ValueError("{} 的 bbox 超出图片范围或尺寸无效。".format(identifier))
    return image, items


def check_engine(language: str, timeout: float) -> str:
    executable = shutil.which("tesseract")
    if executable is None:
        raise RuntimeError("需要安装 Tesseract 和所需语言包；macOS 可执行 brew install tesseract tesseract-lang。")
    languages = language.split("+")
    if any(not name or name.strip() != name for name in languages):
        raise ValueError("OCR 语言格式无效，示例: chi_sim+eng。")
    process = subprocess.run([executable, "--list-langs"], capture_output=True, timeout=timeout)
    if process.returncode:
        raise RuntimeError("无法查询 Tesseract 语言包: {}".format(process.stderr.decode("utf-8", errors="replace").strip()))
    installed = set(process.stdout.decode("utf-8", errors="replace").splitlines())
    missing = sorted(set(languages) - installed)
    if missing:
        raise RuntimeError("缺少 Tesseract 语言包: {}".format(", ".join(missing)))
    return executable


def border_median(image: np.ndarray) -> float:
    return float(np.median(np.concatenate((image[0], image[-1], image[:, 0], image[:, -1]))))


def prepare_crop(crop: np.ndarray, target_height: int, binary: bool = False, conservative: bool = False) -> np.ndarray:
    scale = min(4.0, max(1.0, target_height / crop.shape[0]))
    if conservative:
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        if border_median(gray) < 128:
            gray = cv2.bitwise_not(gray)
        threshold, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        _, image = cv2.threshold(gray, threshold * 0.9, 255, cv2.THRESH_BINARY)
        image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        return cv2.copyMakeBorder(image, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=255)
    image = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if binary:
        _, image = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        background = border_median(image)
    else:
        background = border_median(gray)
    if background < 128:
        image = cv2.bitwise_not(image)
    return cv2.copyMakeBorder(image, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=(255, 255, 255))


def recognize(image: np.ndarray, executable: str, language: str, psm: int, timeout: float) -> Recognition:
    success, encoded = cv2.imencode(".png", image)
    if not success:
        raise ValueError("无法编码 OCR 裁剪图。")
    environment = dict(os.environ, OMP_THREAD_LIMIT="1")
    process = subprocess.run(
        [executable, "stdin", "stdout", "-l", language, "--psm", str(psm), "tsv"],
        input=encoded.tobytes(), capture_output=True, timeout=timeout, env=environment,
    )
    if process.returncode:
        raise RuntimeError("Tesseract 识别失败: {}".format(process.stderr.decode("utf-8", errors="replace").strip()))
    return parse_tsv(process.stdout.decode("utf-8"))


def recognize_crop(
    crop: np.ndarray, executable: str, language: str, psm: int,
    target_height: int, min_confidence: float, timeout: float,
) -> Recognition:
    color = prepare_crop(crop, target_height)
    results = [recognize(color, executable, language, psm, timeout)]
    candidate_mode = 13 if psm == 7 else psm
    if psm == 7:
        results.append(recognize(color, executable, language, candidate_mode, timeout))
    if psm in (7, 13) or not results[0].value or results[0].confidence < min_confidence:
        binary = prepare_crop(crop, target_height, binary=True)
        results.append(recognize(binary, executable, language, candidate_mode, timeout))
    best = max(results, key=lambda result: result.confidence if result.value else -1)
    if not best.value or best.confidence < min_confidence:
        conservative = prepare_crop(crop, target_height, conservative=True)
        results.append(recognize(conservative, executable, language, candidate_mode, timeout))
        best = max(results, key=lambda result: result.confidence if result.value else -1)
    return replace(best, passes=len(results))


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


def fill_text_values(
    image: np.ndarray, items: List[Dict[str, Any]],
    language: str = "chi_sim+eng", psm: int = 7, target_height: int = 48,
    min_confidence: float = 60.0, timeout: float = 30.0, workers: int = 6,
) -> Dict[str, Any]:
    if type(target_height) is not int or target_height <= 0:
        raise ValueError("目标文字高度必须是正整数。")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("超时必须是正数。")
    if not math.isfinite(min_confidence) or not 0 <= min_confidence <= 100:
        raise ValueError("置信度阈值必须在 0 到 100 之间。")
    if psm not in (6, 7, 8, 11, 13):
        raise ValueError("分割模式必须是 6、7、8、11 或 13。")
    if type(workers) is not int or workers <= 0:
        raise ValueError("并行工作线程数必须是正整数。")
    texts = [item for item in items if item.get("type") == "text"]
    executable = check_engine(language, timeout) if texts else ""

    def process(item: Dict[str, Any]) -> Recognition:
        x, y, w, h = item["bbox"]
        crop = image[y:y + h, x:x + w]
        try:
            return recognize_crop(crop, executable, language, psm, target_height, min_confidence, timeout)
        except subprocess.TimeoutExpired as error:
            raise RuntimeError("{} 识别超时（{} 秒）。".format(item["id"], timeout)) from error
        except (RuntimeError, ValueError, csv.Error) as error:
            raise RuntimeError("{}: {}".format(item["id"], error)) from error

    if workers == 1 or len(texts) <= 1:
        results = [process(item) for item in texts]
    else:
        with ThreadPoolExecutor(max_workers=min(workers, len(texts))) as pool:
            futures = [pool.submit(process, item) for item in texts]
            results = [future.result() for future in futures]
    unrecognized = []
    low_confidence = []
    calls = 0
    for item, result in zip(texts, results):
        item["value"] = result.value or None
        calls += result.passes
        if not result.value:
            unrecognized.append(item["id"])
        elif result.confidence < min_confidence:
            low_confidence.append({"id": item["id"], "confidence": round(result.confidence, 2)})
    return {
        "element_count": len(items), "text_count": len(texts),
        "recognized": len(texts) - len(unrecognized), "unrecognized": unrecognized,
        "low_confidence": low_confidence, "tesseract_calls": calls,
    }


def extract_text(
    image_path: Path, detections_path: Path, output_path: Path,
    language: str = "chi_sim+eng", psm: int = 7, target_height: int = 48,
    min_confidence: float = 60.0, timeout: float = 30.0,
) -> Dict[str, Any]:
    if output_path.resolve() in (image_path.resolve(), detections_path.resolve()):
        raise ValueError("输出路径不能覆盖输入图片或检测 JSON。")
    image, items = read_inputs(image_path, detections_path)
    summary = fill_text_values(image, items, language, psm, target_height, min_confidence, timeout)
    write_atomic(output_path, items)
    return {"output": str(output_path.resolve()), **summary}


def main() -> None:
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="使用 Tesseract 识别检测 JSON 中的 text 元素并回填 value")
    parser.add_argument("--image", type=Path, default=root / "output.png")
    parser.add_argument("--detections", type=Path, default=root / "opencv_output" / "detections_01.json")
    parser.add_argument("--output", type=Path, default=root / "opencv_output" / "detections_02.json")
    parser.add_argument("--ocr-lang", default="chi_sim+eng")
    parser.add_argument("--psm", type=int, choices=(6, 7, 8, 11, 13), default=7)
    parser.add_argument("--target-height", type=int, default=48)
    parser.add_argument("--min-confidence", type=float, default=60.0)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    try:
        result = extract_text(
            args.image, args.detections, args.output, args.ocr_lang, args.psm,
            args.target_height, args.min_confidence, args.timeout,
        )
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired, cv2.error) as error:
        parser.exit(1, "OCR 失败: {}\n".format(error))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
