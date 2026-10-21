from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from resize_image import resize_image
from pipeline import run_pipeline
from assemble.compute import convert_detections
from assemble.compile import compile_canvas
from assemble.control import load_query_results


def run_all(
    input_image: Path,
    grid_image: Path,
    opencv_dir: Path,
    detections_path: Path,
    db_path: Path,
    canvas_output: Path,
    background: str = "white",
    grid_step: int = 20,
    model: Optional[str] = None,
    clean_image: Optional[Path] = None,
    refine_labels: bool = True,
    semantic_mode: str = "auto",
) -> Tuple[Dict[str, Any], List[str]]:
    clean_image = clean_image or grid_image.with_name("{}_clean.png".format(grid_image.stem))
    resize_image(input_image, grid_image, background, grid_step=grid_step, clean_output_path=clean_image)
    print("[1/4] 识别图已生成：{}，坐标参考图：{}".format(clean_image, grid_image))
    summary = run_pipeline(clean_image, opencv_dir, detections_path, db_path, model=model, remove_grid=False, refine_labels=refine_labels, semantic_mode=semantic_mode)
    semantic = summary.get("detection", {}).get("semantic", {})
    if semantic.get("status") == "failed":
        print("设备语义补检失败，已保留原有检测结果，需要核验：{}".format(semantic.get("error", "")))
    print("[2/4] 检测、文字识别与控件命名完成：{}".format(detections_path))
    detections = convert_detections(json.loads(detections_path.read_text(encoding="utf-8")))
    print("[3/4] 已转换 {} 条检测结果".format(len(detections)))
    canvas_template = json.loads((ROOT / "data" / "canva_template.json").read_text(encoding="utf-8"))
    text_template = json.loads((ROOT / "data" / "text_template.json").read_text(encoding="utf-8"))
    control_template = json.loads((ROOT / "data" / "control_template.json").read_text(encoding="utf-8"))
    materials = load_query_results(db_path)
    canvas, unmatched = compile_canvas(detections, canvas_template, text_template, control_template, materials)
    canvas_output.parent.mkdir(parents=True, exist_ok=True)
    canvas_output.write_text(json.dumps(canvas, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    controls = sum(1 for node in canvas["d"] if node.get("c") == "ht.Node")
    texts = sum(1 for node in canvas["d"] if node.get("c") == "ht.Text")
    print("[4/4] 已生成画布 {}，控件节点 {} 个，文字节点 {} 个".format(canvas_output, controls, texts))
    if unmatched:
        print("未匹配 {} 个控件: {}".format(len(unmatched), "、".join(str(value) for value in unmatched)))
    return canvas, unmatched


def main() -> None:
    parser = argparse.ArgumentParser(description="SCADA 一键流程：缩放补边 → 无网格图检测识别命名 → 拼装画布 JSON")
    parser.add_argument("--input", type=Path, default=ROOT / "data" / "input.png", help="输入图片路径")
    parser.add_argument("--grid-image", type=Path, default=ROOT / "data" / "output.png", help="1920×1080 网格图输出路径")
    parser.add_argument("--clean-image", type=Path, default=None, help="无网格识别图路径，默认在网格图文件名后添加 _clean")
    parser.add_argument("--opencv-dir", type=Path, default=ROOT / "opencv_output", help="OpenCV 中间结果目录")
    parser.add_argument("--detections", type=Path, default=ROOT / "opencv_output" / "detections.json", help="检测结果 JSON 路径")
    parser.add_argument("--db", type=Path, default=PROJECT / "data" / "sqlite" / "material.db", help="物料数据库路径")
    parser.add_argument("--canvas-output", type=Path, default=None, help="最终画布 JSON 输出路径，默认按时间戳写入 output 目录")
    parser.add_argument("--background", default="white", help="网格图补边颜色，默认 white")
    parser.add_argument("--grid-step", type=int, default=20, help="网格图小网格间距（像素，默认 20）")
    parser.add_argument("--model", default=None, help="DeepSeek 模型，默认取 DEEPSEEK_MODEL")
    parser.add_argument("--no-refine-labels", action="store_true", help="关闭标签与不确定文字的视觉转写复核")
    parser.add_argument("--semantic-mode", choices=("auto", "off", "always"), default="auto", help="设备语义定位模式")
    args = parser.parse_args()
    canvas_output = args.canvas_output or PROJECT / "output" / "canvas_{}.json".format(
        datetime.now().strftime("%Y%m%d_%H%M%S")
    )
    try:
        run_all(
            args.input, args.grid_image, args.opencv_dir, args.detections,
            args.db, canvas_output, args.background, args.grid_step, args.model, args.clean_image,
            not args.no_refine_labels,
            args.semantic_mode,
        )
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError, sqlite3.Error, cv2.error, subprocess.TimeoutExpired) as error:
        parser.exit(1, "流程失败：{}\n".format(error))


if __name__ == "__main__":
    main()
