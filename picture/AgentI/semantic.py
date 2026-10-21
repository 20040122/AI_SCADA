from __future__ import annotations

import asyncio
import base64
import json
import math
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import cv2

if __package__:
    from .name import call_llm, default_client, default_model, encode_image, load_whitelist
    from .opencv import annotate, assign_parents, ocr_detection, write_image
else:
    from name import call_llm, default_client, default_model, encode_image, load_whitelist
    from opencv import annotate, assign_parents, ocr_detection, write_image


UI_NAMES = {"按钮", "数值显示", "绿色状态", "状态显示"}
PROMPT = """你是工业图纸设备实例定位器。逐一定位图中所有设备本体，读取每个设备自己的名称标签。
设备可以与其他像素相连，必须按语义分别定位每个设备实例。忽略所有连接线，不检测、不删除、不重建连接线。
设备框紧贴完整设备本体，包含设备支架和外壳，不包含外部名称、邻居、按钮、状态条和数值框。
颜色和外观不能覆盖名称证据，例如外观相同但标注不同的泵应按各自名称判定。
标签逐字转写，保留实例编号，支持“冷却泵1”和“冷却泵#1”等格式，也保留设备内部的名称文字。
只报告看得见的设备和文字，不按编号补齐不存在的设备。相邻设备分别输出，不得将多个设备框在一起。
类别参考：{categories}。使用最合适的类别原文，未包含的类别使用具体常规名称。
坐标为整张输入图片的归一化坐标，左上角(0,0)，右下角(1000,1000)。bbox严格为[x_min,y_min,x_max,y_max]，不是宽高。
只输出JSON：{{"devices":[{{"name":"类别","bbox":[0,0,0,0],"labels":[{{"text":"原始标签","bbox":[0,0,0,0]}}]}}]}}。
没有可读标签时labels为空数组，不得猜测标签。
"""


def overlap(a: List[int], b: List[int]) -> float:
    x, y, w, h = a
    bx, by, bw, bh = b
    return float(max(0, min(x + w, bx + bw) - max(x, bx)) * max(0, min(y + h, by + bh) - max(y, by)))


def text_lines(image: np.ndarray, language: str) -> List[Dict[str, Any]]:
    if np.ptp(image) == 0:
        return []
    words = ocr_detection(image, language, image.shape[1] / 1920.0)
    grouped: Dict[Tuple[int, ...], List[Dict[str, Any]]] = {}
    for word in words:
        if word["confidence"] >= 0.35:
            grouped.setdefault(tuple(word["line_key"]), []).append(word)
    lines = []
    for group in grouped.values():
        group.sort(key=lambda word: word["bbox"][0])
        value = "".join(word["text"] for word in group)
        if not re.search(r"[\u3400-\u9fff]", value):
            continue
        left = min(word["bbox"][0] for word in group)
        top = min(word["bbox"][1] for word in group)
        right = max(word["bbox"][0] + word["bbox"][2] for word in group)
        bottom = max(word["bbox"][1] + word["bbox"][3] for word in group)
        if bottom - top > image.shape[0] * 0.08:
            continue
        lines.append({"bbox": [left, top, right - left, bottom - top], "text": value})
    return lines


def review_reasons(detection: Dict[str, Any], lines: List[Dict[str, Any]]) -> List[str]:
    equipment = [item for item in detection["nodes"] if item["type"] == "equipment_candidate"]
    reasons = []
    if len(equipment) >= 3:
        unlabelled = sum(not item.get("label_bboxes") for item in equipment)
        if unlabelled / len(equipment) >= 0.5:
            reasons.append("多数设备候选没有关联名称")
    on_text = [item for item in equipment if any(overlap(item["bbox"], line["bbox"]) / max(1, item["bbox"][2] * item["bbox"][3]) >= 0.65 for line in lines)]
    if on_text and len(on_text) >= max(2, len(equipment) * 0.25):
        reasons.append("多个设备候选落在独立检测的文字区域内")
    numbered = [line for line in lines if re.search(r"[\u3400-\u9fff]{2,}#?\d+$", line["text"])]
    if numbered and len(numbered) > max(1, len(equipment)):
        reasons.append("独立检测的实例名称多于设备候选")
    return reasons


def pixel_box(value: Any, width: int, height: int) -> List[int]:
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError("语义定位bbox必须包含四个归一化坐标")
    if any(isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number) or number < 0 or number > 1000 for number in value):
        raise ValueError("语义定位坐标必须在0到1000之间")
    x1, y1, x2, y2 = value
    if x2 <= x1 or y2 <= y1:
        raise ValueError("语义定位bbox边界顺序无效")
    left, top = round(x1 * width / 1000), round(y1 * height / 1000)
    right, bottom = round(x2 * width / 1000), round(y2 * height / 1000)
    if right - left < 3 or bottom - top < 3:
        raise ValueError("语义定位框过小")
    return [left, top, right - left, bottom - top]


def parse_layout(content: str, width: int, height: int) -> List[Dict[str, Any]]:
    start, end = content.find("{"), content.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("语义定位没有返回JSON对象")
    result = json.loads(content[start:end + 1])
    if not isinstance(result, dict) or not isinstance(result.get("devices"), list) or not result["devices"]:
        raise ValueError("语义定位未返回设备列表")
    devices = []
    for entry in result["devices"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str) or not entry["name"].strip():
            raise ValueError("语义定位设备类别无效")
        if entry["name"].strip() in UI_NAMES:
            raise ValueError("语义定位不得替换界面控件")
        box = pixel_box(entry.get("bbox"), width, height)
        if box[2] * box[3] > width * height * 0.5:
            raise ValueError("语义定位设备框覆盖范围异常")
        labels = entry.get("labels", [])
        if not isinstance(labels, list):
            raise ValueError("语义定位标签必须是数组")
        parsed = []
        for label in labels:
            if not isinstance(label, dict) or not isinstance(label.get("text"), str) or not label["text"].strip():
                raise ValueError("语义定位标签文字无效")
            label_box = pixel_box(label.get("bbox"), width, height)
            gap_x = max(box[0] - label_box[0] - label_box[2], label_box[0] - box[0] - box[2], 0)
            gap_y = max(box[1] - label_box[1] - label_box[3], label_box[1] - box[1] - box[3], 0)
            if gap_x > max(box[2], label_box[2], label_box[3]) * 4 or gap_y > max(box[3], label_box[3]) * 4:
                raise ValueError("语义定位标签与设备距离异常")
            parsed.append({"text": label["text"].strip(), "bbox": label_box})
        if any(overlap(box, device["bbox"]) / max(1, box[2] * box[3] + device["bbox"][2] * device["bbox"][3] - overlap(box, device["bbox"])) > 0.75 for device in devices):
            raise ValueError("语义定位返回重复设备框")
        devices.append({"name": entry["name"].strip(), "bbox": box, "labels": parsed})
    return devices


async def locate_devices(image: np.ndarray, categories: List[str], model: Optional[str]) -> str:
    url = "data:image/png;base64,{}".format(base64.b64encode(encode_image(image)).decode("ascii"))
    messages = [
        {"role": "system", "content": PROMPT.format(categories="、".join(name for name in categories if name not in UI_NAMES))},
        {"role": "user", "content": [{"type": "text", "text": "定位完整设备与名称标签。图片尺寸为{}×{}，坐标仍使用0到1000。".format(image.shape[1], image.shape[0])}, {"type": "image_url", "image_url": {"url": url}}]},
    ]
    response = await call_llm(default_client, model or default_model, messages, temperature=0.0)
    return response.choices[0].message.content or ""


def anchor_devices(devices: List[Dict[str, Any]], detection: Dict[str, Any]) -> List[Dict[str, Any]]:
    ui_boxes = [node["bbox"] for node in detection["nodes"] if node["layer"] == "controls" and node["type"] != "equipment_candidate"]
    candidates = [node["bbox"] for node in detection["nodes"] if node["type"] == "equipment_candidate" and not any(overlap(node["bbox"], box) / max(1, node["bbox"][2] * node["bbox"][3]) > 0.5 for box in ui_boxes)]
    if not candidates or len(candidates) != len(devices):
        return devices
    from scipy.optimize import linear_sum_assignment

    centers = np.array([[box[0] + box[2] / 2, box[1] + box[3] / 2] for box in candidates])
    proposed = np.array([[device["bbox"][0] + device["bbox"][2] / 2, device["bbox"][1] + device["bbox"][3] / 2] for device in devices])
    distances = np.linalg.norm(proposed[:, None] - centers[None, :], axis=2)
    rows, columns = linear_sum_assignment(distances)
    for row, column in zip(rows, columns):
        box, target = devices[row]["bbox"], candidates[column]
        if not (0.5 <= target[2] / box[2] <= 2 and 0.5 <= target[3] / box[3] <= 2) or distances[row, column] > max(box[2], box[3]) * 4:
            return devices
    updated = deepcopy(devices)
    for row, column in zip(rows, columns):
        device, target = updated[row], candidates[column]
        box = device["bbox"]
        dx, dy = target[0] + target[2] / 2 - box[0] - box[2] / 2, target[1] + target[3] / 2 - box[1] - box[3] / 2
        device["bbox"] = list(target)
        device["geometry_source"] = "opencv"
        for label in device["labels"]:
            x, y, w, h = label["bbox"]
            label["bbox"] = [max(0, min(detection["image_size"]["width"] - w, x + round(dx))), max(0, min(detection["image_size"]["height"] - h, y + round(dy))), w, h]
    return updated


def refine_boxes(image: np.ndarray, devices: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[int]]:
    updated = deepcopy(devices)
    border = np.concatenate((image[0], image[-1], image[:, 0], image[:, -1]))
    background = np.median(border, axis=0)
    failed = []

    def runs(values):
        ids = np.flatnonzero(values)
        return np.split(ids, np.where(np.diff(ids) > 1)[0] + 1) if ids.size else []

    for index, device in enumerate(updated):
        if device.get("geometry_source") == "opencv":
            continue
        x, y, w, h = device["bbox"]
        left, top = max(0, x - round(w * 0.3)), max(0, y - round(h * 0.65))
        right, bottom = min(image.shape[1], x + w + round(w * 0.3)), min(image.shape[0], y + h + round(h * 0.65))
        crop = image[top:bottom, left:right]
        foreground = np.max(np.abs(crop.astype(np.float32) - background), axis=2) > 35
        column_counts = np.count_nonzero(foreground, axis=0)
        columns = [group for group in runs(column_counts > max(3, h * 0.18)) if len(group) > w * 0.35]
        if not columns:
            failed.append(index)
            continue
        columns = max(columns, key=lambda group: np.sum(column_counts[group]))
        x1, x2 = int(columns[0]), int(columns[-1]) + 1
        row_counts = np.count_nonzero(foreground[:, x1:x2], axis=1)
        rows = [group for group in runs(row_counts > max(3, (x2 - x1) * 0.15)) if len(group) > h * 0.3]
        if not rows:
            failed.append(index)
            continue
        rows = max(rows, key=lambda group: np.sum(row_counts[group]) * math.exp(-abs(top + float(np.mean(group)) - y - h / 2) / max(1, h * 0.6)))
        pad_x, pad_y = max(2, round((x2 - x1) * 0.06)), max(2, round(len(rows) * 0.06))
        new_left, new_top = max(0, left + x1 - pad_x), max(0, top + int(rows[0]) - pad_y)
        new_right, new_bottom = min(image.shape[1], left + x2 + pad_x), min(image.shape[0], top + int(rows[-1]) + 1 + pad_y)
        box = [new_left, new_top, new_right - new_left, new_bottom - new_top]
        if box[2] > w * 1.6 or box[3] > h * 1.8 or box[2] < w * 0.6 or box[3] < h * 0.6:
            failed.append(index)
            continue
        device["bbox"] = box
    return updated, failed


def align_labels(image: np.ndarray, devices: List[Dict[str, Any]], text_regions: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    updated = deepcopy(devices)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    mask = np.where((gray < 150) & (hsv[:, :, 1] < 90), 255, 0).astype(np.uint8)
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    glyphs = [tuple(int(value) for value in stats[index]) for index in range(1, count)]
    assigned_regions = set()
    for device in updated:
        for label in device["labels"]:
            x, y, w, h = label["bbox"]
            parts = label["text"].split()
            nearby = []
            for region in text_regions or []:
                rx, ry, rw, rh = region["bbox"]
                if tuple(region["bbox"]) in assigned_regions:
                    continue
                minimum_width = max(w * (0.25 if len(parts) > 1 else 0.5), min(h, 20) * 0.7)
                if rw < minimum_width or not h * 0.2 <= rh <= h * 1.8:
                    continue
                if re.fullmatch(r"[\u3400-\u9fff]+", label["text"]) and not len(label["text"]) * 0.6 <= rw / rh <= len(label["text"]) * 1.6:
                    continue
                dx, dy = abs(rx + rw / 2 - x - w / 2), abs(ry + rh / 2 - y - h / 2)
                if dx <= max(w, device["bbox"][2]) * 1.5 and dy <= max(h * 3, device["bbox"][3]):
                    nearby.append((dx / max(w, 1) + dy / max(h, 1), region["bbox"]))
            nearby.sort(key=lambda candidate: candidate[0])
            selected = [box for _, box in nearby[:max(1, len(parts))]]
            selected.sort(key=lambda box: box[1])
            multiline = len(parts) > 1 and len(selected) == len(parts) and all(0 <= b[1] - a[1] - a[3] <= max(a[3], b[3]) * 2 for a, b in zip(selected, selected[1:]))
            if selected and (len(parts) == 1 or multiline):
                left, top = min(box[0] for box in selected), min(box[1] for box in selected)
                right, bottom = max(box[0] + box[2] for box in selected), max(box[1] + box[3] for box in selected)
                label["bbox"] = [left, top, right - left, bottom - top]
                assigned_regions.update(tuple(box) for box in selected)
                if multiline:
                    label["text"] = "\n".join(parts)
                continue
            candidates = []
            for gx, gy, gw, gh, area in glyphs:
                if not (h * 0.4 <= gh <= h * 1.8 and h * 0.1 <= gw <= h * 2 and area >= h * h * 0.03):
                    continue
                if abs(gy + gh / 2 - y - h / 2) <= h and gx + gw >= x - w * 0.25 and gx <= x + w * 1.25:
                    candidates.append([gx, gy, gw, gh])
            groups: List[List[List[int]]] = []
            for glyph in sorted(candidates, key=lambda box: (box[1] + box[3], box[0])):
                compatible = [group for group in groups if abs(np.median([box[1] + box[3] for box in group]) - glyph[1] - glyph[3]) <= h * 0.3]
                if compatible:
                    compatible[0].append(glyph)
                else:
                    groups.append([glyph])
            ranked = []
            for group in groups:
                if len(group) < 2:
                    continue
                gx, gy = min(box[0] for box in group), min(box[1] for box in group)
                right, bottom = max(box[0] + box[2] for box in group), max(box[1] + box[3] for box in group)
                if right - gx < w * 0.6 or right - gx > w * 1.6:
                    continue
                score = abs((gx + right) / 2 - x - w / 2) / max(w, 1) + abs((gy + bottom) / 2 - y - h / 2) / max(h, 1)
                ranked.append((score, [gx, gy, right - gx, bottom - gy]))
            if ranked:
                gx, gy, gw, gh = min(ranked, key=lambda pair: pair[0])[1]
                left = max(0, min(x - round(h * 0.3), gx - round(h * 0.6)))
                right = min(image.shape[1], max(x + w + round(h * 0.3), gx + gw + round(h * 0.6)))
                patch = mask[gy:gy + gh, left:right]
                points = cv2.findNonZero(patch)
                if points is not None:
                    bx, by, bw, bh = cv2.boundingRect(points)
                    label["bbox"] = [left + bx, gy + by, bw, bh]
    return updated


def merge_layout(detection: Dict[str, Any], devices: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    updated = deepcopy(detection)
    grid = updated["nodes"][0]
    controls = [item for item in updated["nodes"] if item["layer"] == "controls" and item["type"] != "equipment_candidate"]
    semantic_controls, semantic_texts = [], []
    for index, device in enumerate(devices):
        if any(overlap(device["bbox"], item["bbox"]) / max(1, device["bbox"][2] * device["bbox"][3]) > 0.8 for item in controls):
            raise ValueError("语义设备框与已有界面控件重叠")
        identifier = "semantic_{}".format(index)
        semantic_controls.append({"id": identifier, "layer": "controls", "type": "equipment_candidate", "bbox": device["bbox"], "parent_id": grid["id"], "confidence": None, "confidence_source": "vision", "semantic_name": device["name"], "semantic_labels": [label["text"] for label in device["labels"]]})
        for label in device["labels"]:
            semantic_texts.append({"id": "label_{}".format(len(semantic_texts)), "layer": "text", "type": "text_region", "bbox": label["bbox"], "text": label["text"], "source_control_id": identifier, "confidence": None, "confidence_source": "vision", "recognition_status": "not_requested", "detection_method": "semantic"})
    texts = []
    for item in updated["nodes"]:
        if item["layer"] != "text":
            continue
        area = max(1, item["bbox"][2] * item["bbox"][3])
        if any(overlap(item["bbox"], label["bbox"]) / area >= 0.3 for label in semantic_texts):
            continue
        if any(overlap(item["bbox"], control["bbox"]) / area >= 0.8 for control in semantic_controls):
            continue
        item.pop("source_control_id", None)
        texts.append(item)
    controls = sorted(controls + semantic_controls, key=lambda item: (item["bbox"][1], item["bbox"][0]))
    remapped = {item["id"]: "controls_{}".format(index) for index, item in enumerate(controls, 1)}
    for item in controls:
        item["id"] = remapped[item["id"]]
    texts = sorted(texts + semantic_texts, key=lambda item: (item["bbox"][1], item["bbox"][0]))
    for index, item in enumerate(texts, 1):
        item["id"] = "text_{}".format(index)
        if item.get("source_control_id"):
            item["source_control_id"] = remapped[item["source_control_id"]]
    assign_parents(controls, texts, updated["image_size"]["width"] / 1920.0)
    nodes = [grid] + controls + texts
    children = {item["id"]: [] for item in nodes}
    for item in nodes[1:]:
        children[item["parent_id"]].append(item["id"])
    for item in nodes:
        item["children"] = children[item["id"]]
    updated["nodes"] = nodes
    updated["counts"] = {"controls": len(controls), "texts": len(texts)}
    updated["limitations"] = ["设备由语义定位与局部前景范围校验得到，模型定位误差仍需核验。", "连接线未作为检测对象，也未进行删除或重建。"]
    exported = []
    for item in controls + texts:
        entry = {"id": item["id"], "type": item["layer"], "bbox": item["bbox"], "value": None}
        if item["layer"] == "controls":
            entry["label_bboxes"] = item["label_bboxes"]
            entry["control_kind"] = item["type"]
            if item.get("semantic_name"):
                entry["semantic_name"] = item["semantic_name"]
                entry["semantic_labels"] = item.get("semantic_labels", [])
        else:
            entry["parent_id"] = item["parent_id"] if item["parent_id"] != grid["id"] else None
            if item.get("detection_method") == "semantic":
                entry["vision_value"] = item["text"]
        exported.append(entry)
    return exported, updated


def review_detection(
    image: np.ndarray,
    items: List[Dict[str, Any]],
    detection: Dict[str, Any],
    output_dir: Path,
    db_path: Path,
    model: Optional[str] = None,
    language: str = "chi_sim+eng",
    mode: str = "auto",
) -> Tuple[List[Dict[str, Any]], Dict[str, Any], Dict[str, Any]]:
    if mode not in ("auto", "off", "always"):
        raise ValueError("semantic_mode必须为auto、off或always")
    if mode == "off":
        return items, detection, {"status": "disabled"}
    summary: Dict[str, Any] = {"status": "not_needed", "mode": mode, "connection_processing": False}
    try:
        lines = text_lines(image, language)
        summary["independent_text_regions"] = len(lines)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "independent_text.json").write_text(json.dumps(lines, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as error:
        lines = []
        summary["text_detection_error"] = str(error)
    reasons = review_reasons(detection, lines)
    summary["reasons"] = reasons
    if mode == "auto" and not reasons:
        return items, detection, summary
    try:
        content = asyncio.run(locate_devices(image, load_whitelist(db_path), model))
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "semantic_response.json").write_text(content, encoding="utf-8")
        devices = anchor_devices(parse_layout(content, image.shape[1], image.shape[0]), detection)
        devices, failed_refinements = refine_boxes(image, devices)
        devices = align_labels(image, devices, [node for node in detection["nodes"] if node["layer"] == "text"])
        summary["refinement_failed"] = failed_refinements
        numbered = [line for line in lines if re.search(r"[\u3400-\u9fff]{2,}#?\d+$", line["text"])]
        uncovered = [line for line in numbered if not any(overlap(line["bbox"], label["bbox"]) / max(1, line["bbox"][2] * line["bbox"][3]) >= 0.3 for device in devices for label in device["labels"])]
        summary["uncovered_instance_labels"] = len(uncovered)
        if len(uncovered) > max(1, len(numbered) * 0.2):
            raise ValueError("语义定位结果遗漏多个独立检测的实例名称")
        merged, updated = merge_layout(detection, devices)
    except Exception as error:
        summary.update(status="failed", error="{}: {}".format(type(error).__name__, error))
        return items, detection, summary
    controls = [node for node in updated["nodes"] if node["layer"] == "controls"]
    texts = [node for node in updated["nodes"] if node["layer"] == "text"]
    for filename, nodes in [("01_controls.png", controls), ("02_text.png", texts), ("03_hierarchy.png", controls + texts)]:
        write_image(output_dir / filename, annotate(image, nodes))
    summary.update(status="applied", devices=len(devices), labels=sum(len(device["labels"]) for device in devices))
    return merged, updated, summary
