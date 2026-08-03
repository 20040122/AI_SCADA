from __future__ import annotations


def round2(value: float) -> float:
    return round(value, 2)


def fit_size(raw_w: float, raw_h: float, min_w: float, min_h: float, max_w: float, max_h: float) -> tuple[float, float]:
    min_scale = max(min_w / raw_w, min_h / raw_h)
    max_scale = min(max_w / raw_w, max_h / raw_h)
    if min_scale > max_scale:
        scale = max_scale
    else:
        scale = min(1, max_scale)
        if scale < min_scale:
            scale = min_scale
    return raw_w * scale, raw_h * scale


def inscribe_ratio(width: float, height: float, ratio: float) -> tuple[float, float]:
    if ratio <= 0:
        return width, height
    new_w = min(width, height * ratio)
    new_h = new_w / ratio
    return new_w, new_h


def ratio_error(width_a: float, height_a: float, width_b: float, height_b: float) -> float:
    if height_a <= 0 or height_b <= 0:
        return 0.0
    ratio_a = width_a / height_a
    ratio_b = width_b / height_b
    if ratio_b == 0:
        return 0.0
    return abs(ratio_a - ratio_b) / ratio_b


def content_rect_of_nodes(nodes: list[dict]) -> dict:
    if not nodes:
        return {"x": 0, "y": 0, "width": 0, "height": 0}
    min_x = float("inf")
    min_y = float("inf")
    max_x = float("-inf")
    max_y = float("-inf")
    for n in nodes:
        cx = n.get("x", 0)
        cy = n.get("y", 0)
        w = n.get("width", 0) or 0
        h = n.get("height", 0) or 0
        half_w, half_h = w / 2, h / 2
        min_x = min(min_x, cx - half_w)
        min_y = min(min_y, cy - half_h)
        max_x = max(max_x, cx + half_w)
        max_y = max(max_y, cy + half_h)
    return {
        "x": round(min_x, 5),
        "y": round(min_y, 5),
        "width": round(max_x - min_x, 5),
        "height": round(max_y - min_y, 5),
    }
