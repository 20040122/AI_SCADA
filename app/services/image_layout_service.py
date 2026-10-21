from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Optional

from PIL import UnidentifiedImageError

from app.services.validation_service import ValidationService
from model.layout_agent import LayoutOutputError
from model.layout_tools.geometry import content_rect_of_nodes


AGENT_DIR = Path(__file__).resolve().parents[2] / "picture" / "AgentI"


@dataclass
class ImageLayoutResult:
    json_data: dict
    content_rect: dict
    missing_controls: list = field(default_factory=list)
    quality_issues: list = field(default_factory=list)
    pipe_data: Optional[dict] = None


def generate_image_layout(image: bytes, materials: list, width: int, height: int, title: str) -> ImageLayoutResult:
    from picture.AgentI.assemble.compile import compile_canvas
    from picture.AgentI.assemble.compute import convert_detections
    from picture.AgentI.pipeline import run_pipeline
    from picture.AgentI.resize_image import resize_image

    if not image:
        raise ValueError("上传图片不能为空")
    if not materials:
        raise ValueError("query_results 表为空")
    if width <= 0 or height <= 0:
        raise ValueError("画布宽高必须为正整数")

    with TemporaryDirectory(prefix="scada-image-layout-") as directory:
        work = Path(directory)
        source = work / "input"
        source.write_bytes(image)
        clean = work / "clean.png"
        try:
            resize_image(source, work / "grid.png", clean_output_path=clean)
        except UnidentifiedImageError as exc:
            raise ValueError("无法解码上传图片") from exc
        db_path = work / "materials.db"
        with closing(sqlite3.connect(str(db_path))) as connection:
            connection.execute("CREATE TABLE query_results (displayName TEXT, image TEXT, width REAL, height REAL)")
            connection.executemany(
                "INSERT INTO query_results VALUES (?, ?, ?, ?)",
                [(item.get("displayName"), item.get("image", ""), item.get("width", 0), item.get("height", 0)) for item in materials],
            )
            connection.commit()
        detections_path = work / "detections.json"
        summary = run_pipeline(clean, work / "detection", detections_path, db_path, remove_grid=False)
        detections = convert_detections(json.loads(detections_path.read_text(encoding="utf-8")))
        for detection in detections:
            if detection.get("type") == "text" and not isinstance(detection.get("value"), str):
                detection["value"] = ""
        templates = [json.loads((AGENT_DIR / "data" / filename).read_text(encoding="utf-8")) for filename in ("canva_template.json", "text_template.json", "control_template.json")]
        canvas, unmatched = compile_canvas(detections, *templates, materials)

    scale = min(width / 1920, height / 1080)
    offset_x = (width - 1920 * scale) / 2
    offset_y = (height - 1080 * scale) / 2
    canvas["a"].update(width=width, height=height, title=title, **{"layout.materials": materials})
    for node in canvas["d"]:
        props = node["p"]
        props["position"] = {"x": props["position"]["x"] * scale + offset_x, "y": props["position"]["y"] * scale + offset_y}
        props["width"] *= scale
        props["height"] *= scale
        if node["c"] == "ht.Node":
            node.setdefault("a", {}).update({"layout.group": "image", "layout.node": str(node["i"]), "layout.instance": 1})
        elif node["c"] == "ht.Text":
            font = node["s"].get("text.font", "16px arial, sans-serif")
            node["s"]["text.font"] = re.sub(r"([\d.]+)px", lambda match: "{:g}px".format(float(match.group(1)) * scale), font)
    rect = content_rect_of_nodes([dict(node["p"]["position"], width=node["p"]["width"], height=node["p"]["height"]) for node in canvas["d"]])
    canvas["contentRect"] = rect
    errors, _ = ValidationService.instance().validate("canvas", canvas)
    if errors:
        raise LayoutOutputError("; ".join("{} {}".format(error.path, error.message) for error in errors))
    issues = []
    semantic = summary.get("detection", {}).get("semantic", {})
    if semantic.get("status") == "failed" or semantic.get("text_detection_error") or semantic.get("refinement_failed") or summary.get("naming", {}).get("failed") or summary.get("label_refinement", {}).get("failed"):
        issues.append({"severity": "warning", "issue_type": "image_recognition", "message": "部分图片识别失败，已保留检测结果，请核验设备和文字", "controls": []})
    return ImageLayoutResult(canvas, rect, [str(name or "未命名控件") for name in unmatched], issues)
