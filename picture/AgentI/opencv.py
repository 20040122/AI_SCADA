import argparse
import csv
import io
import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

import cv2
import numpy as np


def read_image(path: Path) -> np.ndarray:
    if not path.is_file():
        raise FileNotFoundError("图像不存在: {}".format(path))
    image = cv2.imdecode(np.frombuffer(path.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("无法解码图像: {}".format(path))
    return image


def write_image(path: Path, image: np.ndarray) -> None:
    success, encoded = cv2.imencode(".png", image)
    if not success:
        raise RuntimeError("图像编码失败: {}".format(path))
    path.write_bytes(encoded.tobytes())


def boxes(mask: np.ndarray) -> List[Tuple[int, int, int, int, int]]:
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    return [tuple(int(v) for v in stats[i]) for i in range(1, count)]


def node(layer: str, index: int, kind: str, box: Tuple[int, ...], score: float) -> Dict[str, Any]:
    return {
        "id": "{}_{}".format(layer, index),
        "layer": layer,
        "type": kind,
        "bbox": list(box[:4]),
        "parent_id": None,
        "confidence": round(score, 3),
        "confidence_source": "heuristic",
        "text": None,
    }


def line_groups(values: np.ndarray) -> List[Tuple[int, int]]:
    indices = np.flatnonzero(values)
    if not indices.size:
        return []
    groups = np.split(indices, np.where(np.diff(indices) > 1)[0] + 1)
    return [(int(g[0]), int(g[-1] - g[0] + 1)) for g in groups]


def grid_detection(image: np.ndarray, enabled: bool = True) -> Tuple[Dict[str, Any], np.ndarray, np.ndarray]:
    height, width = image.shape[:2]
    xs = []
    ys = []
    mask = np.zeros((height, width), np.uint8)
    if enabled:
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        cyan = cv2.inRange(hsv, (82, 15, 115), (103, 255, 255))
        horizontal = cv2.morphologyEx(cyan, cv2.MORPH_OPEN, np.ones((1, max(20, width // 4)), np.uint8))
        vertical = cv2.morphologyEx(cyan, cv2.MORPH_OPEN, np.ones((max(20, height // 4), 1), np.uint8))
        xs = line_groups((np.count_nonzero(vertical, axis=0) > height * 0.4) | (np.count_nonzero(cyan, axis=0) > height * 0.55))
        ys = line_groups((np.count_nonzero(horizontal, axis=1) > width * 0.4) | (np.count_nonzero(cyan, axis=1) > width * 0.55))
        geometry = np.zeros((height, width), np.uint8)
        for x, thickness in xs:
            geometry[:, x:x + thickness] = 255
        for y, thickness in ys:
            geometry[y:y + thickness, :] = 255
        mask = cv2.bitwise_and(geometry, cyan)
    cleaned = cv2.inpaint(image, mask, 2, cv2.INPAINT_TELEA) if np.any(mask) else image.copy()
    info = {
        "id": "grid_1",
        "layer": "grid",
        "type": "coordinate_grid",
        "bbox": [0, 0, width, height],
        "parent_id": None,
        "vertical_lines": [{"position": x, "thickness": t} for x, t in xs],
        "horizontal_lines": [{"position": y, "thickness": t} for y, t in ys],
        "step_x": float(np.median(np.diff([x for x, _ in xs]))) if len(xs) > 1 else None,
        "step_y": float(np.median(np.diff([y for y, _ in ys]))) if len(ys) > 1 else None,
        "detected": bool(xs or ys),
    }
    return info, mask, cleaned


def controls_detection(image: np.ndarray, scale: float) -> Tuple[List[Dict[str, Any]], np.ndarray]:
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    height, width = image.shape[:2]
    green = cv2.inRange(hsv, (35, 200, 140), (75, 255, 255))
    blue = cv2.inRange(hsv, (88, 75, 130), (112, 255, 255))
    red = cv2.bitwise_or(cv2.inRange(hsv, (0, 100, 100), (25, 255, 255)), cv2.inRange(hsv, (170, 100, 100), (179, 255, 255)))
    gray_indicator = cv2.inRange(hsv, (0, 0, 110), (179, 30, 225))
    b, g, r = cv2.split(image)
    pale = np.where((b.astype(np.int16) - r.astype(np.int16) > 3) & (b.astype(np.int16) - g.astype(np.int16) > 2) & (r > 170) & (hsv[:, :, 1] < 65), 255, 0).astype(np.uint8)
    results = []
    occupied = np.zeros((height, width), np.uint8)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(3, round(5 * scale)), max(2, round(3 * scale))))
    for kind, raw in [("status", green), ("button", cv2.bitwise_or(blue, red)), ("value_field", pale), ("indicator", gray_indicator)]:
        mask = cv2.morphologyEx(raw, cv2.MORPH_CLOSE, kernel)
        for x, y, w, h, area in boxes(mask):
            ratio = w / max(h, 1)
            if kind == "value_field":
                valid = 25 * scale <= w <= 100 * scale and 10 * scale <= h <= 34 * scale and ratio >= 1.4
            elif kind in ("status", "indicator"):
                valid = 35 * scale <= w <= 110 * scale and 10 * scale <= h <= 38 * scale and ratio >= 1.5
                if kind == "indicator":
                    valid = valid and w >= 55 * scale and h >= 23 * scale
            else:
                valid = 65 * scale <= w <= 240 * scale and 23 * scale <= h <= 55 * scale and ratio >= 1.6
            if not valid or area / (w * h) < 0.38:
                continue
            if kind == "value_field" and np.count_nonzero(raw[y:y + h, x:x + w]) / (w * h) < 0.6:
                continue
            if kind == "indicator" and area / (w * h) < 0.65:
                continue
            actual_kind = "indicator" if kind == "status" and h > 24 * scale else kind
            item = node("controls", len(results) + 1, actual_kind, (x, y, w, h), min(0.95, 0.55 + area / (w * h) * 0.4))
            results.append(item)
    results = [item for item in results if not any(other is not item and other["type"] != "value_field" and item["type"] == "value_field" and contains(other["bbox"], item["bbox"]) for other in results)]
    for item in results:
        x, y, w, h = item["bbox"]
        occupied[y:y + h, x:x + w] = 255
    results.sort(key=lambda item: (item["bbox"][1], item["bbox"][0]))
    for i, item in enumerate(results, 1):
        item["id"] = "controls_{}".format(i)
    return results, occupied


def components_detection(image: np.ndarray, occupied: np.ndarray, scale: float) -> Tuple[List[Dict[str, Any]], np.ndarray]:
    border = np.concatenate((image[0], image[-1], image[:, 0], image[:, -1]))
    background = np.median(border, axis=0)
    difference = np.max(np.abs(image.astype(np.float32) - background), axis=2)
    foreground = np.where(difference > 28, 255, 0).astype(np.uint8)
    expanded_controls = cv2.dilate(occupied, np.ones((3, 3), np.uint8))
    foreground[expanded_controls > 0] = 0
    seeds = np.zeros_like(foreground)
    separated = cv2.morphologyEx(foreground, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    candidates = []
    raw_boxes = boxes(foreground)
    substantial = [box for box in raw_boxes if box[2] >= 10 * scale and box[3] >= 23 * scale and box[4] / (box[2] * box[3]) >= 0.3]
    for x, y, w, h, area in raw_boxes:
        if w < 10 * scale or h < 23 * scale or area < 100 * scale * scale:
            continue
        if area / (w * h) < 0.18 and not any(contains([x, y, w, h], list(box[:4])) for box in substantial):
            continue
        if h <= 60 * scale:
            body = foreground[y:y + h, x:x + w]
            upper_height = max(1, round(h * 0.6))
            upper_width = np.count_nonzero(np.any(body[:upper_height], axis=0))
            row_widths = np.array([np.ptp(np.flatnonzero(row)) + 1 if np.any(row) else 0 for row in body])
            widened = np.flatnonzero((np.arange(h) >= upper_height) & (row_widths > upper_width * 1.6))
            if upper_width < w * 0.65 and widened.size:
                bx, by, bw, bh = tight_box(body[:int(widened[0])])
                x, y, w, h = x + bx, y + by, bw, bh
            parts = [part for part in boxes(separated[y:y + h, x:x + w]) if part[3] >= 23 * scale and part[4] >= 100 * scale * scale]
            if len(parts) == 1 and parts[0][3] < h - 5 * scale and parts[0][2] <= w * 0.75:
                px, py, pw, ph, area = parts[0]
                x, y, w, h = x + max(0, px - 1), y + max(0, py - 1), pw, ph
        candidates.append((x, y, w, h, area))
    for x, y, w, h, area in candidates:
        aligned = [other for other in candidates if abs(other[1] - y) <= 3 * scale and abs(other[3] - h) <= 3 * scale and abs(other[0] - x) <= 3 * max(w, other[2]) and other[3] <= 30 * scale]
        if h <= 30 * scale and len(aligned) >= 3:
            continue
        seeds[y:y + h, x:x + w] |= foreground[y:y + h, x:x + w]
    kernel_size = max(2, round(3 * scale))
    merged = cv2.morphologyEx(seeds, cv2.MORPH_CLOSE, np.ones((kernel_size, kernel_size), np.uint8))
    results = []
    mask = np.zeros(image.shape[:2], np.uint8)
    for x, y, w, h, area in boxes(merged):
        if w < 10 * scale or h < 23 * scale or area < 100 * scale * scale:
            continue
        if w * h > image.shape[0] * image.shape[1] * 0.5:
            continue
        if w / h > 5 or h / w > 8:
            continue
        item = node("controls", len(results) + 1, "equipment_candidate", (x, y, w, h), min(0.85, 0.4 + area / (w * h) * 0.4))
        item["parent_id"] = "grid_1"
        results.append(item)
        mask[y:y + h, x:x + w] |= foreground[y:y + h, x:x + w]
    for item in list(results):
        x, y, w, h = item["bbox"]
        if w / h >= 0.5:
            continue
        nearby = []
        for other in results:
            if other is item:
                continue
            ox, oy, ow, oh = other["bbox"]
            overlap = max(0, min(y + h, oy + oh) - max(y, oy)) / h
            gap = max(ox - x - w, x - ox - ow, 0)
            if ow >= 2 * w and oh >= h and overlap >= 0.7 and gap <= max(3 * scale, ow * 0.2):
                nearby.append((gap, other))
        if nearby:
            other = min(nearby, key=lambda pair: pair[0])[1]
            ox, oy, ow, oh = other["bbox"]
            left, top = min(x, ox), min(y, oy)
            other["bbox"] = [left, top, max(x + w, ox + ow) - left, max(y + h, oy + oh) - top]
            results.remove(item)
    return results, mask


def glyph_mask(mask: np.ndarray, scale: float, short: bool = False) -> np.ndarray:
    filtered = np.zeros_like(mask)
    for x, y, w, h, area in boxes(mask):
        minimum_height = 1 if short else max(1, round(2 * scale))
        if minimum_height <= h <= 26 * scale and w <= 32 * scale and area >= max(2, round(2 * scale * scale)):
            filtered[y:y + h, x:x + w] |= mask[y:y + h, x:x + w]
    return filtered


def tight_box(mask: np.ndarray, offset: Tuple[int, int] = (0, 0)) -> Tuple[int, int, int, int]:
    ys, xs = np.nonzero(mask)
    return int(xs.min()) + offset[0], int(ys.min()) + offset[1], int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)


def text_detection(image: np.ndarray, component_mask: np.ndarray, controls: List[Dict[str, Any]], scale: float) -> List[Dict[str, Any]]:
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    dark = np.where((gray < 150) & ((hsv[:, :, 1] < 90) | (gray < 105)), 255, 0).astype(np.uint8)
    bright = np.where((gray > 225) & (hsv[:, :, 1] < 45), 255, 0).astype(np.uint8)
    candidates = np.zeros_like(gray)
    for source, light in [(dark, False), (bright, True)]:
        glyphs = boxes(glyph_mask(source, scale))
        if not light:
            separated = cv2.morphologyEx(source, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
            glyphs.extend((max(0, x - 1), max(0, y - 1), w, h, area) for x, y, w, h, area in boxes(glyph_mask(separated, scale)))
        for x, y, w, h, area in glyphs:
            margin = max(2, round(3 * scale))
            left, top = max(0, x - margin), max(0, y - margin)
            right, bottom = min(image.shape[1], x + w + margin), min(image.shape[0], y + h + margin)
            patch = gray[top:bottom, left:right]
            ring = np.ones(patch.shape, bool)
            ring[y - top:y - top + h, x - left:x - left + w] = False
            surrounding = patch[ring]
            if not surrounding.size:
                continue
            if light:
                valid = np.median(surrounding) < 215 and np.any(component_mask[y:y + h, x:x + w])
            else:
                valid = np.median(surrounding) > 215
            if valid:
                candidates[y:y + h, x:x + w] |= source[y:y + h, x:x + w]
    for control in controls:
        x, y, w, h = control["bbox"]
        if control["type"] == "equipment_candidate":
            if h < 80 * scale and w < h * 2.5:
                candidates[y:y + h, x:x + w] = 0
            continue
        candidates[max(0, y - 2):y + h + 2, max(0, x - 2):x + w + 2] = 0
    results = []
    merged = cv2.dilate(candidates, np.ones((max(1, round(2 * scale)), max(3, round(9 * scale))), np.uint8))
    for x, y, w, h, area in boxes(merged):
        selected = candidates[y:y + h, x:x + w]
        if not np.any(selected):
            continue
        box = tight_box(selected, (x, y))
        if not (4 * scale <= box[2] <= 260 * scale and 5 * scale <= box[3] <= 28 * scale):
            continue
        interior = any(contains(control["bbox"], list(box)) for control in controls if control["type"] == "equipment_candidate")
        if interior and (box[2] < 2.5 * box[3] or box[3] < 10 * scale):
            continue
        item = node("text", len(results) + 1, "text_region", box, 0.6)
        item.update(recognition_status="not_requested", detection_method="aligned_glyphs")
        results.append(item)
    results.sort(key=lambda item: (item["bbox"][1], item["bbox"][0]))
    for i, item in enumerate(results, 1):
        item["id"] = "text_{}".format(i)
    return results


def ocr_detection(image: np.ndarray, language: str, scale: float) -> List[Dict[str, Any]]:
    executable = shutil.which("tesseract")
    if executable is None:
        raise RuntimeError("--ocr 需要安装 Tesseract 和相应语言包；不加 --ocr 可仅检测文字区域。")
    enlarged = cv2.resize(image, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    with tempfile.TemporaryDirectory(prefix="scada-ocr-") as directory:
        path = Path(directory) / "input.png"
        write_image(path, enlarged)
        process = subprocess.run([executable, str(path), "stdout", "-l", language, "--psm", "11", "tsv"], capture_output=True, text=True, check=False, timeout=120)
    if process.returncode:
        raise RuntimeError("Tesseract 识别失败: {}".format(process.stderr.strip()))
    results = []
    for row in csv.DictReader(io.StringIO(process.stdout), delimiter="\t", quoting=csv.QUOTE_NONE):
        value = (row.get("text") or "").strip()
        score = float(row["conf"])
        if not value or score < 0:
            continue
        box = tuple(round(int(row[key]) / 2) for key in ("left", "top", "width", "height"))
        item = node("text", len(results) + 1, "text_region", box, score / 100)
        item.update(text=value, recognition_status="recognized", confidence_source="tesseract")
        item["line_key"] = [int(row[key]) for key in ("page_num", "block_num", "par_num", "line_num")]
        results.append(item)
    return results


def contains(outer: List[int], inner: List[int]) -> bool:
    x, y, w, h = outer
    ix, iy, iw, ih = inner
    return x - 3 <= ix and y - 3 <= iy and ix + iw <= x + w + 3 and iy + ih <= y + h + 3


def apply_ocr(texts: List[Dict[str, Any]], recognized: List[Dict[str, Any]]) -> None:
    matches = {item["id"]: [] for item in texts}
    for word in recognized:
        wx, wy, ww, wh = word["bbox"]
        ranked = []
        for region in texts:
            x, y, w, h = region["bbox"]
            overlap = max(0, min(x + w, wx + ww) - max(x, wx)) * max(0, min(y + h, wy + wh) - max(y, wy))
            coverage = overlap / max(1, ww * wh)
            if coverage >= 0.4:
                ranked.append((coverage, region["id"]))
        if ranked:
            matches[max(ranked)[1]].append(word)
    for region in texts:
        words = sorted(matches[region["id"]], key=lambda word: (word["bbox"][1], word["bbox"][0]))
        region["recognition_status"] = "recognized" if words else "not_recognized"
        if words:
            region["text"] = " ".join(word["text"] for word in words)
            region["recognition_confidence"] = round(sum(word["confidence"] for word in words) / len(words), 3)


def value_field_labels(controls: List[Dict[str, Any]], texts: List[Dict[str, Any]], scale: float) -> Dict[str, Dict[str, Any]]:
    equipment = [control for control in controls if control["type"] == "equipment_candidate" and max(control["bbox"][2:]) <= 80 * scale]
    fields = [control for control in controls if control["type"] == "value_field"]
    associations = {}
    for field in fields:
        fx, fy, fw, fh = field["bbox"]
        ranked = []
        for control in equipment:
            cx, cy, cw, ch = control["bbox"]
            gap_x = max(cx - fx - fw, fx - cx - cw, 0)
            gap_y = max(cy - fy - fh, fy - cy - ch, 0)
            distance = math.hypot(cx + cw / 2 - fx - fw / 2, cy + ch / 2 - fy - fh / 2)
            if math.hypot(gap_x, gap_y) <= max(cw, ch, fh) * 1.5:
                ranked.append((distance / max(cw, ch), control))
        ranked.sort(key=lambda pair: pair[0])
        if not ranked or (len(ranked) > 1 and ranked[1][0] - ranked[0][0] < 0.5):
            continue
        labels = []
        for item in texts:
            x, y, w, h = item["bbox"]
            offset = abs(x + w / 2 - fx - fw / 2)
            gap = fy - y - h
            if 1.4 * h <= w <= 4 * h and 0 <= gap <= h * 1.5 and offset <= max(w, fw) * 0.6:
                labels.append(item)
        if len(labels) == 1:
            associations.setdefault(labels[0]["id"], []).append(ranked[0][1])
    return {identifier: candidates[0] for identifier, candidates in associations.items() if len(candidates) == 1}


def assign_parents(controls: List[Dict[str, Any]], texts: List[Dict[str, Any]], scale: float) -> None:
    for control in controls:
        control["parent_id"] = "grid_1"
        control["label_bboxes"] = []
        control.pop("label_association", None)
    controls_by_id = {control["id"]: control for control in controls}
    equipment = [control for control in controls if control["type"] == "equipment_candidate"]
    field_labels = value_field_labels(controls, texts, scale)
    for item in texts:
        source = controls_by_id.get(item.get("source_control_id"))
        possible = [source] if source else [c for c in controls if contains(c["bbox"], item["bbox"])]
        if possible:
            parent = min(possible, key=lambda c: c["bbox"][2] * c["bbox"][3])
            item["parent_id"] = parent["id"]
            item["association"] = {"method": "containment", "confidence": 0.9}
            parent["label_bboxes"].append(item["bbox"])
            continue
        x, y, w, h = item["bbox"]
        ranked = []
        for control in equipment:
            cx, cy, cw, ch = control["bbox"]
            offset = abs(x + w / 2 - cx - cw / 2)
            gap = max(cy - y - h, y - cy - ch, 0)
            aligned = offset <= max(8 * scale, cw * 0.35, h * 0.5)
            outside = y >= cy + ch * 0.8 or y + h <= cy + 3 * scale
            if aligned and outside and gap <= max(12 * scale, h * 1.5, ch * 0.15) and w >= 2.5 * h:
                ranked.append((gap / max(h, 1) + offset / max(cw, h), control))
        ranked.sort(key=lambda pair: pair[0])
        if ranked and (len(ranked) == 1 or ranked[1][0] - ranked[0][0] >= 0.25):
            parent = ranked[0][1]
            item["parent_id"] = parent["id"]
            item["association"] = {"method": "aligned_label", "confidence": round(0.9 / (1 + ranked[0][0]), 3)}
            parent["label_bboxes"].append(item["bbox"])
        elif not ranked and item["id"] in field_labels:
            parent = field_labels[item["id"]]
            item["parent_id"] = parent["id"]
            item["association"] = {"method": "value_field_label", "confidence": 0.8}
            parent["label_bboxes"].append(item["bbox"])
            parent["label_association"] = "value_field_label"
        else:
            item["parent_id"] = "grid_1"
            item["association"] = {"method": "page", "confidence": 1.0}


def annotate(image: np.ndarray, items: List[Dict[str, Any]]) -> np.ndarray:
    output = image.copy()
    colors = {"controls": (255, 0, 180), "text": (0, 140, 0)}
    for item in items:
        x, y, w, h = item["bbox"]
        color = colors[item["layer"]]
        cv2.rectangle(output, (x, y), (x + w - 1, y + h - 1), color, 1)
        label = item["id"].replace("controls_", "C").replace("text_", "T")
        cv2.putText(output, label, (x, max(10, y - 3)), cv2.FONT_HERSHEY_SIMPLEX, 0.32, color, 1, cv2.LINE_AA)
    return output


def run_detection(
    input_path: Path, output_dir: Path, ocr: bool = False, language: str = "chi_sim+eng",
    remove_grid: bool = True,
) -> Tuple[np.ndarray, List[Dict[str, Any]], Dict[str, Any]]:
    image = read_image(input_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    filenames = ["01_controls.png", "02_text.png", "03_hierarchy.png", "detections_01.json"]
    legacy_filenames = ["03_components.png", "04_controls.png", "05_text.png", "06_hierarchy.png"]
    if input_path.resolve() in [(output_dir / name).resolve() for name in filenames + legacy_filenames]:
        raise ValueError("输入路径与结果文件路径冲突。")
    scale = image.shape[1] / 1920.0
    grid, _, cleaned = grid_detection(image, enabled=remove_grid)
    controls, occupied = controls_detection(cleaned, scale)
    components, component_mask = components_detection(cleaned, occupied, scale)
    controls = sorted(components + controls, key=lambda item: (item["bbox"][1], item["bbox"][0]))
    for i, control in enumerate(controls, 1):
        control["id"] = "controls_{}".format(i)
    texts = text_detection(image, component_mask, controls, scale)
    if ocr:
        ocr_image = np.full_like(image, 255)
        for region in texts:
            x, y, w, h = region["bbox"]
            ocr_image[y:y + h, x:x + w] = image[y:y + h, x:x + w]
        recognized = ocr_detection(ocr_image, language, scale)
        apply_ocr(texts, recognized)
        for i, region in enumerate(texts, 1):
            region["id"] = "text_{}".format(i)
    assign_parents(controls, texts, scale)
    items = [grid] + controls + texts
    children = {item["id"]: [] for item in items}
    for item in items:
        if item["parent_id"]:
            children[item["parent_id"]].append(item["id"])
    for item in items:
        item["children"] = children[item["id"]]
    result = {
        "schema_version": 2,
        "input": str(input_path.resolve()),
        "image_size": {"width": image.shape[1], "height": image.shape[0]},
        "bbox_format": "x_y_width_height",
        "ocr": {"enabled": ocr, "language": language if ocr else None},
        "text_filters": {"exclude_control_interior": False, "exclude_trailing_units": False, "exclude_hash_names": False},
        "limitations": ["设备为几何候选，未进行设备类别识别。", "邻近归属为启发式推断，需要人工核验。", "网格修复图用于检测，原图保持不变。", "设备检测假设背景大致均匀，连接管线与复杂背景需要核验。"],
        "counts": {"controls": len(controls), "texts": len(texts)},
        "nodes": items,
    }
    images = [annotate(image, controls), annotate(image, texts), annotate(image, controls + texts)]
    for name, rendered in zip(filenames[:-1], images):
        write_image(output_dir / name, rendered)
    exported = []
    for item in controls + texts:
        entry = {"id": item["id"], "type": item["layer"], "bbox": item["bbox"], "value": None}
        if item["layer"] == "controls":
            entry["label_bboxes"] = item["label_bboxes"]
            entry["control_kind"] = item["type"]
            if item.get("label_association"):
                entry["label_association"] = item["label_association"]
        else:
            entry["parent_id"] = item["parent_id"] if item["parent_id"] != "grid_1" else None
        exported.append(entry)
    for name in legacy_filenames:
        legacy_path = output_dir / name
        if legacy_path.is_file():
            legacy_path.unlink()
    return image, exported, result


def detect(input_path: Path, output_dir: Path, ocr: bool = False, language: str = "chi_sim+eng") -> Dict[str, Any]:
    _, exported, result = run_detection(input_path, output_dir, ocr, language)
    (output_dir / "detections_01.json").write_text(json.dumps(exported, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="SCADA 图像 Grid → Controls → Text 分层检测")
    parser.add_argument("input", nargs="?", type=Path, default=Path(__file__).with_name("output.png"))
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).with_name("opencv_output"))
    parser.add_argument("--ocr", action="store_true", help="使用 Tesseract 识别文字内容")
    parser.add_argument("--ocr-lang", default="chi_sim+eng", help="Tesseract 语言，默认 chi_sim+eng")
    args = parser.parse_args()
    try:
        result = detect(args.input, args.output_dir, args.ocr, args.ocr_lang)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        parser.exit(1, "检测失败: {}\n".format(error))
    print(json.dumps({"output_dir": str(args.output_dir.resolve()), **result["counts"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
