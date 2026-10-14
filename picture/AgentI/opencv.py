import argparse
import csv
import io
import json
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


def grid_detection(image: np.ndarray) -> Tuple[Dict[str, Any], np.ndarray, np.ndarray]:
    height, width = image.shape[:2]
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
    gray_indicator[:round(height * 0.84), :] = 0
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
                valid = 65 * scale <= w <= 160 * scale and 23 * scale <= h <= 55 * scale and ratio >= 1.6
            if not valid or area / (w * h) < 0.38 or y < 18 * scale or x < 20 * scale:
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
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    foreground = cv2.inRange(hsv, (0, 45, 35), (179, 255, 255))
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    neutral = np.where((gray < 200) & (hsv[:, :, 1] < 45), 255, 0).astype(np.uint8)
    expanded_controls = cv2.dilate(occupied, np.ones((max(3, round(5 * scale)), max(3, round(5 * scale))), np.uint8))
    neutral[expanded_controls > 0] = 0
    neutral = cv2.morphologyEx(neutral, cv2.MORPH_CLOSE, np.ones((max(2, round(3 * scale)), max(2, round(3 * scale))), np.uint8))
    neutral_boxes = boxes(neutral)
    for x, y, w, h, area in list(neutral_boxes):
        if 35 * scale < w <= 100 * scale and 35 * scale <= h <= 65 * scale:
            top = neutral[y:y + max(1, h - round(18 * scale)), x:x + w]
            neutral_boxes.extend((x + bx, y + by, bw, bh, size) for bx, by, bw, bh, size in boxes(top))
    for x, y, w, h, area in neutral_boxes:
        if 10 * scale <= w <= 35 * scale and 20 * scale <= h <= 45 * scale and area >= 100 * scale * scale:
            foreground[y:y + h, x:x + w] |= neutral[y:y + h, x:x + w]
    foreground[expanded_controls > 0] = 0
    foreground[:max(1, round(18 * scale)), :] = 0
    foreground[:, :max(1, round(40 * scale))] = 0
    kernel_size = max(3, round(7 * scale))
    merged = cv2.morphologyEx(foreground, cv2.MORPH_CLOSE, np.ones((kernel_size, kernel_size), np.uint8))
    results = []
    mask = np.zeros(image.shape[:2], np.uint8)
    for x, y, w, h, area in boxes(merged):
        if w < 13 * scale or h < 17 * scale or area < 160 * scale * scale:
            continue
        if w > 270 * scale or h > 230 * scale or y > image.shape[0] * 0.84:
            continue
        if w / h > 5 or h / w > 8:
            continue
        item = node("controls", len(results) + 1, "equipment_candidate", (x, y, w, h), min(0.85, 0.4 + area / (w * h) * 0.4))
        item["parent_id"] = "grid_1"
        results.append(item)
        mask[y:y + h, x:x + w] |= foreground[y:y + h, x:x + w]
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


def contains_hash(mask: np.ndarray, scale: float) -> bool:
    pattern = ["00110010", "00110010", "00110110", "11111111", "01100110", "01100100", "01100110", "11111111", "01001100", "01001100", "11001000"]
    reference = np.array([[int(pixel) for pixel in row] for row in pattern], np.uint8)
    for x, y, w, h, area in boxes(mask):
        if not (6 * scale <= h <= 24 * scale and 0.4 <= w / h <= 1.0 and x >= mask.shape[1] * 0.45):
            continue
        symbol = cv2.resize((mask[y:y + h, x:x + w] > 0).astype(np.uint8), (8, 11), interpolation=cv2.INTER_NEAREST)
        intersection = np.count_nonzero(symbol & reference)
        union = np.count_nonzero(symbol | reference)
        if intersection / max(1, union) >= 0.62:
            return True
    height, width = mask.shape
    for template_height in range(max(5, round(9 * scale)), min(height, round(15 * scale)) + 1):
        for template_width in range(max(3, round(template_height * 0.55)), round(template_height * 0.85) + 1):
            if template_width > width:
                continue
            template = cv2.resize(reference * 255, (template_width, template_height), interpolation=cv2.INTER_NEAREST)
            scores = cv2.matchTemplate(mask, template, cv2.TM_CCOEFF_NORMED)
            start = max(round(width * 0.55), width - template_width - round(12 * scale))
            stop = width - template_width - max(2, round(3 * scale))
            if start <= stop and float(scores[:, start:stop + 1].max()) >= 0.57:
                return True
    return False


def is_unit(box: Tuple[int, ...], controls: List[Dict[str, Any]], scale: float) -> bool:
    x, y, w, h = box[:4]
    if w > 45 * scale or h > 14 * scale:
        return False
    for control in controls:
        if control["type"] not in ("value_field", "equipment_candidate"):
            continue
        cx, cy, cw, ch = control["bbox"]
        gap = x - cx - cw
        if -2 * scale <= gap <= 40 * scale and abs(y + h / 2 - cy - ch / 2) <= max(8 * scale, ch * 0.5):
            return True
    return False


def text_detection(image: np.ndarray, component_mask: np.ndarray, controls: List[Dict[str, Any]], scale: float) -> List[Dict[str, Any]]:
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    dark = np.where((gray < 135) & ((hsv[:, :, 1] < 110) | (gray < 105)), 255, 0).astype(np.uint8)
    external = dark.copy()
    opened = cv2.morphologyEx(component_mask, cv2.MORPH_OPEN, np.ones((max(2, round(3 * scale)), max(2, round(3 * scale))), np.uint8))
    equipment_body = np.zeros_like(external)
    for control in controls:
        if control["type"] != "equipment_candidate":
            continue
        x, y, w, h = control["bbox"]
        parts = boxes(opened[y:y + h, x:x + w])
        if not parts:
            continue
        minimum_area = max(9, round(12 * scale * scale))
        substantial_area = max(part[4] for part in parts) * 0.15
        parts = [part for part in parts if part[4] >= minimum_area and (part[4] >= substantial_area or part[1] < h * 0.6)]
        if not parts:
            continue
        body = np.zeros((h, w), np.uint8)
        for px, py, pw, ph, _ in parts:
            body[py:py + ph, px:px + pw] |= opened[y + py:y + py + ph, x + px:x + px + pw]
        rows = np.flatnonzero(np.any(body, axis=1))
        left_edges = [int(np.flatnonzero(body[row])[0]) for row in rows]
        right_edges = [int(np.flatnonzero(body[row])[-1]) for row in rows]
        for row in range(int(rows[0]), int(rows[-1]) + 1):
            left = round(float(np.interp(row, rows, left_edges)))
            right = round(float(np.interp(row, rows, right_edges)))
            equipment_body[y + row, x + left:x + right + 1] = 255
    margin = max(1, round(2 * scale))
    equipment_body = cv2.dilate(equipment_body, np.ones((2 * margin + 1, 2 * margin + 1), np.uint8))
    external[equipment_body > 0] = 0
    results = []
    for control in controls:
        x, y, w, h = control["bbox"]
        if control["type"] == "equipment_candidate":
            continue
        external[max(0, y - 2):y + h + 2, max(0, x - 2):x + w + 2] = 0
    external[:max(1, round(18 * scale)), :] = 0
    external[:, :max(1, round(45 * scale))] = 0
    candidates = glyph_mask(external, scale)
    merged = cv2.dilate(candidates, np.ones((max(2, round(3 * scale)), max(3, round(9 * scale))), np.uint8))
    for x, y, w, h, area in boxes(merged):
        selected = candidates[y:y + h, x:x + w]
        if not np.any(selected):
            continue
        box = tight_box(selected, (x, y))
        if not (4 * scale <= box[2] <= 260 * scale and 5 * scale <= box[3] <= 28 * scale):
            continue
        if any(contains(control["bbox"], list(box)) for control in controls):
            continue
        if is_unit(box, controls, scale) or contains_hash(dark[box[1]:box[1] + box[3], box[0]:box[0] + box[2]], scale):
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
    enlarged[:max(1, round(36 * scale)), :] = 255
    enlarged[:, :max(1, round(90 * scale))] = 255
    with tempfile.TemporaryDirectory(prefix="scada-ocr-") as directory:
        path = Path(directory) / "input.png"
        write_image(path, enlarged)
        process = subprocess.run([executable, str(path), "stdout", "-l", language, "--psm", "11", "tsv"], capture_output=True, text=True, check=False, timeout=120)
    if process.returncode:
        raise RuntimeError("Tesseract 识别失败: {}".format(process.stderr.strip()))
    results = []
    for row in csv.DictReader(io.StringIO(process.stdout), delimiter="\t"):
        value = (row.get("text") or "").strip()
        score = float(row["conf"])
        if not value or score < 0:
            continue
        box = tuple(round(int(row[key]) / 2) for key in ("left", "top", "width", "height"))
        item = node("text", len(results) + 1, "text_region", box, score / 100)
        item.update(text=value, recognition_status="recognized", confidence_source="tesseract")
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


def distance(a: List[int], b: List[int]) -> float:
    x, y, w, h = a
    bx, by, bw, bh = b
    dx = max(x - bx - bw, bx - x - w, 0)
    dy = max(y - by - bh, by - y - h, 0)
    return float(np.hypot(dx, dy))


def assign_parents(controls: List[Dict[str, Any]], texts: List[Dict[str, Any]], scale: float) -> None:
    for control in controls:
        control["parent_id"] = "grid_1"
    controls_by_id = {control["id"]: control for control in controls}
    equipment = [control for control in controls if control["type"] == "equipment_candidate"]
    for item in texts:
        source = controls_by_id.get(item.get("source_control_id"))
        possible = [source] if source else [c for c in controls if contains(c["bbox"], item["bbox"])]
        if possible:
            parent = min(possible, key=lambda c: c["bbox"][2] * c["bbox"][3])
            item["parent_id"] = parent["id"]
            item["association"] = {"method": "containment", "confidence": 0.9}
            continue
        nearby = sorted(equipment, key=lambda c: distance(item["bbox"], c["bbox"]))
        limit = 60 * scale
        if nearby and distance(item["bbox"], nearby[0]["bbox"]) <= limit and item["bbox"][1] < 880 * scale:
            gap = distance(item["bbox"], nearby[0]["bbox"])
            item["parent_id"] = nearby[0]["id"]
            item["association"] = {"method": "nearest_candidate", "confidence": round(0.7 * (1 - gap / (limit * 1.5)), 3), "distance": round(gap, 2)}
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


def detect(input_path: Path, output_dir: Path, ocr: bool = False, language: str = "chi_sim+eng") -> Dict[str, Any]:
    image = read_image(input_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    filenames = ["01_grid_mask.png", "02_grid_removed.png", "03_controls.png", "04_text.png", "05_hierarchy.png", "detections_01.json"]
    legacy_filenames = ["03_components.png", "04_controls.png", "05_text.png", "06_hierarchy.png"]
    if input_path.resolve() in [(output_dir / name).resolve() for name in filenames + legacy_filenames]:
        raise ValueError("输入路径与结果文件路径冲突。")
    scale = image.shape[1] / 1920.0
    grid, grid_mask, cleaned = grid_detection(image)
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
        texts = [region for region in texts if "#" not in (region["text"] or "")]
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
        "text_filters": {"exclude_control_interior": True, "exclude_trailing_units": True, "exclude_hash_names": True, "hash_detection": "glyph_template"},
        "limitations": ["设备为几何候选，未进行设备类别识别。", "邻近归属为启发式推断，需要人工核验。", "网格修复图用于检测，原图保持不变。", "小单位通过尺寸与邻近位置过滤，带 # 名称通过字形模板过滤；其他字体和布局需要核验。"],
        "counts": {"controls": len(controls), "texts": len(texts)},
        "nodes": items,
    }
    images = [grid_mask, cleaned, annotate(image, controls), annotate(image, texts), annotate(image, controls + texts)]
    for name, rendered in zip(filenames[:-1], images):
        write_image(output_dir / name, rendered)
    exported = [{"id": item["id"], "type": item["layer"], "bbox": item["bbox"], "value": None} for item in controls + texts]
    (output_dir / "detections_01.json").write_text(json.dumps(exported, ensure_ascii=False, indent=2), encoding="utf-8")
    for name in legacy_filenames:
        legacy_path = output_dir / name
        if legacy_path.is_file():
            legacy_path.unlink()
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
