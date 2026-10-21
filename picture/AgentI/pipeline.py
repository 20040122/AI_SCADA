from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, Optional

import cv2

ROOT = Path(__file__).resolve().parent
PROJECT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if __package__:
    from .name import DEFAULT_CONCURRENCY, DEFAULT_CONTEXT, fill_control_names, refine_label_values
    from .ocr import fill_text_values, infer_text_style, write_atomic
    from .opencv import run_detection
    from .semantic import review_detection
else:
    from name import DEFAULT_CONCURRENCY, DEFAULT_CONTEXT, fill_control_names, refine_label_values
    from ocr import fill_text_values, infer_text_style, write_atomic
    from opencv import run_detection
    from semantic import review_detection


def run_pipeline(
    image_path: Path,
    output_dir: Path,
    output_path: Path,
    db_path: Path,
    ocr_lang: str = "chi_sim+eng",
    psm: int = 7,
    target_height: int = 48,
    min_confidence: float = 60.0,
    timeout: float = 30.0,
    model: Optional[str] = None,
    concurrency: int = DEFAULT_CONCURRENCY,
    context: float = DEFAULT_CONTEXT,
    dump_crops: Optional[Path] = None,
    ocr_workers: int = 6,
    remove_grid: bool = True,
    refine_labels: bool = True,
    semantic_mode: str = "auto",
) -> Dict[str, Any]:
    if output_path.resolve() == image_path.resolve():
        raise ValueError("输出路径不能覆盖输入图片。")
    timing: Dict[str, Any] = {}
    started = time.perf_counter()
    stage = time.perf_counter()
    image, items, detection = run_detection(image_path, output_dir, remove_grid=remove_grid)
    timing["detection_seconds"] = round(time.perf_counter() - stage, 3)

    def timed(label: str, func):
        stage = time.perf_counter()
        try:
            return func()
        finally:
            timing[label] = round(time.perf_counter() - stage, 3)

    items, detection, semantic_summary = timed(
        "layout_review_seconds",
        lambda: review_detection(image, items, detection, output_dir, db_path, model, ocr_lang, semantic_mode),
    )

    def run_ocr():
        return fill_text_values(image, items, ocr_lang, psm, target_height, min_confidence, timeout, ocr_workers, True)

    def run_naming():
        return fill_control_names(image, items, db_path, model, concurrency, context, dump_crops)

    stage = time.perf_counter()
    with ThreadPoolExecutor(max_workers=2) as pool:
        ocr_future = pool.submit(timed, "ocr_seconds", run_ocr)
        naming_future = pool.submit(timed, "naming_seconds", run_naming)
        ocr_summary = ocr_future.result()
        naming_summary = naming_future.result()
    timing["parallel_seconds"] = round(time.perf_counter() - stage, 3)
    label_summary = timed("label_refinement_seconds", lambda: refine_label_values(image, items, model, concurrency)) if refine_labels else {"enabled": False}
    for item in items:
        if item.get("type") == "text":
            item["text_style"] = infer_text_style(image, item)
    detection["semantic"] = semantic_summary
    stage = time.perf_counter()
    write_atomic(output_path, items)
    (output_dir / "detection_details.json").write_text(json.dumps(detection, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    timing["write_seconds"] = round(time.perf_counter() - stage, 3)
    timing["total_seconds"] = round(time.perf_counter() - started, 3)
    return {
        "output": str(output_path.resolve()),
        "image": str(image_path.resolve()),
        "detection": {"counts": detection["counts"], "semantic": semantic_summary},
        "ocr": ocr_summary,
        "naming": naming_summary,
        "label_refinement": label_summary,
        "timing": timing,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="SCADA 全流程：OpenCV 检测 → Tesseract 文字识别 → DeepSeek 控件命名，仅写出最终 detections.json")
    parser.add_argument("--image", type=Path, default=ROOT / "data" / "output_clean.png")
    parser.add_argument("--remove-grid", action="store_true", help="输入图片自带网格时启用网格检测和去除")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "opencv_output")
    parser.add_argument("--output", type=Path, default=ROOT / "opencv_output" / "detections.json")
    parser.add_argument("--db", type=Path, default=PROJECT / "data" / "sqlite" / "material.db")
    parser.add_argument("--ocr-lang", default="chi_sim+eng")
    parser.add_argument("--psm", type=int, choices=(6, 7, 8, 11, 13), default=7)
    parser.add_argument("--target-height", type=int, default=48)
    parser.add_argument("--min-confidence", type=float, default=60.0)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--model", default=None, help="默认取 DEEPSEEK_MODEL")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY, help="控件命名并发请求数")
    parser.add_argument("--context", type=float, default=DEFAULT_CONTEXT, help="控件裁剪图向四周外扩的比例")
    parser.add_argument("--dump-crops", type=Path, default=None, help="导出全部控件裁剪图到该目录，用于人工核对")
    parser.add_argument("--ocr-workers", type=int, default=6, help="Tesseract 文本识别的并行工作线程数")
    parser.add_argument("--no-refine-labels", action="store_true", help="关闭设备标签的视觉转写复核")
    parser.add_argument("--semantic-mode", choices=("auto", "off", "always"), default="auto", help="设备语义定位模式，auto在检测异常时补检，off使用原有路径")
    args = parser.parse_args()
    try:
        result = run_pipeline(
            args.image, args.output_dir, args.output, args.db, args.ocr_lang,
            args.psm, args.target_height, args.min_confidence, args.timeout,
            args.model, args.concurrency, args.context, args.dump_crops, args.ocr_workers,
            remove_grid=args.remove_grid,
            refine_labels=not args.no_refine_labels,
            semantic_mode=args.semantic_mode,
        )
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError, sqlite3.Error, cv2.error, subprocess.TimeoutExpired) as error:
        parser.exit(1, "流程失败: {}\n".format(error))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
