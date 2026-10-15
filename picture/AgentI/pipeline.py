from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import cv2

ROOT = Path(__file__).resolve().parent
PROJECT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from name import DEFAULT_CONCURRENCY, DEFAULT_CONTEXT, fill_control_names
from ocr import fill_text_values, write_atomic
from opencv import run_detection


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
) -> Dict[str, Any]:
    if output_path.resolve() == image_path.resolve():
        raise ValueError("输出路径不能覆盖输入图片。")
    image, items, detection = run_detection(image_path, output_dir)
    ocr_summary = fill_text_values(image, items, ocr_lang, psm, target_height, min_confidence, timeout)
    naming_summary = fill_control_names(image, items, db_path, model, concurrency, context, dump_crops)
    write_atomic(output_path, items)
    return {
        "output": str(output_path.resolve()),
        "image": str(image_path.resolve()),
        "detection": {"counts": detection["counts"]},
        "ocr": ocr_summary,
        "naming": naming_summary,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="SCADA 全流程：OpenCV 检测 → Tesseract 文字识别 → DeepSeek 控件命名，仅写出最终 detections.json")
    parser.add_argument("--image", type=Path, default=ROOT / "data" / "output.png")
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
    args = parser.parse_args()
    try:
        result = run_pipeline(
            args.image, args.output_dir, args.output, args.db, args.ocr_lang,
            args.psm, args.target_height, args.min_confidence, args.timeout,
            args.model, args.concurrency, args.context, args.dump_crops,
        )
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError, sqlite3.Error, cv2.error, subprocess.TimeoutExpired) as error:
        parser.exit(1, "流程失败: {}\n".format(error))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
