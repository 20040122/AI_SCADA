from __future__ import annotations
from copy import deepcopy
from dataclasses import dataclass
from typing import Callable, Optional

ROLE_FILL = "fill"
ROLE_EDGE_STRIP = "edge_strip"
ROLE_TEXT_OVERLAY = "text_overlay"
ROLE_FREE = "free"

def _is_fullcanvas(p: dict, canvas: tuple[float, float]) -> bool:
    if not canvas or not canvas[0]:
        return False
    w = p.get("width", 0)
    h = p.get("height", 0)
    return w >= canvas[0] * 0.95 and h >= canvas[1] * 0.95

@dataclass
class Rect:
    cx: float
    cy: float
    w: float
    h: float

    @property
    def left(self) -> float:
        return self.cx - self.w / 2

    @property
    def right(self) -> float:
        return self.cx + self.w / 2

    @property
    def top(self) -> float:
        return self.cy - self.h / 2

    @property
    def bottom(self) -> float:
        return self.cy + self.h / 2

def _rect_of(p: dict) -> Rect:
    pos = p.get("position", {"x": 0.0, "y": 0.0})
    return Rect(
        cx=float(pos.get("x", 0.0)),
        cy=float(pos.get("y", 0.0)),
        w=float(p.get("width", 0.0)),
        h=float(p.get("height", 0.0)),
    )

def _write_rect(p: dict, cx: float, cy: float, w: float, h: float) -> None:
    p["width"] = round(w, 2)
    p["height"] = round(h, 2)
    if "position" in p:
        p["position"] = {"x": round(cx, 2), "y": round(cy, 2)}

def _rescale_fill(
    node: dict, old_w: float, old_h: float, new_w: float, new_h: float
) -> None:
    p = node["p"]
    if p.get("displayName") == "container":
        _write_rect(p, cx=0.0, cy=0.0, w=new_w, h=new_h)
        p.pop("position", None)
    else:
        _write_rect(p, cx=new_w / 2, cy=new_h / 2, w=new_w, h=new_h)

def _rescale_edge_strip(
    node: dict, old_w: float, old_h: float, new_w: float, new_h: float,
    side: str = "top",
) -> dict:
    p = node["p"]
    r = _rect_of(p)
    left = r.left
    right = old_w - r.right
    bar_h = r.h

    new_w_bar = max(0.0, new_w - left - right)
    new_cx = left + new_w_bar / 2

    if side == "bottom":
        bottom = old_h - r.bottom
        new_cy = new_h - bottom - bar_h / 2
    else:
        top = r.top
        new_cy = top + bar_h / 2

    _write_rect(p, cx=new_cx, cy=new_cy, w=new_w_bar, h=bar_h)
    return {"cx": new_cx, "cy": new_cy, "w": new_w_bar, "h": bar_h}

def _rescale_text_overlay(
    node: dict, old_w: float, old_h: float, new_w: float, new_h: float,
    parent_geom: Optional[dict] = None,
) -> None:
    p = node["p"]
    r = _rect_of(p)

    if parent_geom is not None:
        dx = r.cx - parent_geom["old_cx"]
        dy = r.cy - parent_geom["old_cy"]
        new_cx = parent_geom["cx"] + dx
        new_cy = parent_geom["cy"] + dy
    else:
        dx = r.cx - old_w / 2
        new_cx = new_w / 2 + dx
        new_cy = r.cy

    _write_rect(p, cx=new_cx, cy=new_cy, w=r.w, h=r.h)

def _rescale_free(
    node: dict, sx: float, sy: float, old_w: float, old_h: float,
    new_w: float, new_h: float,
) -> None:
    p = node["p"]
    r = _rect_of(p)
    s = min(sx, sy)
    new_cx = r.cx * sx
    new_cy = r.cy * sy
    new_w = r.w * s
    new_h = r.h * s
    _write_rect(p, cx=new_cx, cy=new_cy, w=new_w, h=new_h)

@dataclass
class RoleRule:
    role: str
    matcher: Callable[[dict, float, float], bool]
    rescale: Callable

_DEFAULT_RULES: list[RoleRule] = [
    RoleRule(
        ROLE_FILL,
        lambda n, w, h: n.get("p", {}).get("displayName") == "container",
        _rescale_fill,
    ),
    RoleRule(
        ROLE_FILL,
        lambda n, w, h: (
            "背景" in (n.get("p", {}).get("displayName") or "")
            and _is_fullcanvas(n.get("p", {}), (w, h))
        ),
        _rescale_fill,
    ),
    RoleRule(
        ROLE_EDGE_STRIP,
        lambda n, w, h: (
            "标题栏" in (n.get("p", {}).get("displayName") or "")
            or "title" in (n.get("p", {}).get("displayName") or "").lower()
        ),
        _rescale_edge_strip,
    ),
    RoleRule(
        ROLE_TEXT_OVERLAY,
        lambda n, w, h: n.get("c") == "ht.Text",
        _rescale_text_overlay,
    ),
]

_CUSTOM_RULES: list[RoleRule] = []

def register_role(rule: RoleRule) -> None:
    _CUSTOM_RULES.insert(0, rule)

def _classify(node: dict, old_w: float, old_h: float) -> str:
    for rule in _CUSTOM_RULES + _DEFAULT_RULES:
        if rule.matcher(node, old_w, old_h):
            return rule.role
    return ROLE_FREE

def rescale_canvas(
    json_data: dict, new_width: int, new_height: int, *, inplace: bool = False
) -> dict:
    data = json_data if inplace else deepcopy(json_data)

    a = data.get("a", {})
    old_w = float(a.get("width", 0))
    old_h = float(a.get("height", 0))
    if old_w <= 0 or old_h <= 0:
        raise ValueError(f"invalid source canvas size: {old_w}x{old_h}")

    new_w = float(new_width)
    new_h = float(new_height)
    sx = new_w / old_w
    sy = new_h / old_h

    a["width"] = int(new_w)
    a["height"] = int(new_h)

    if "contentRect" in data:
        data["contentRect"] = {
            "x": 0, "y": 0, "width": int(new_w), "height": int(new_h),
        }

    d = data.get("d", [])
    roles = [_classify(node, old_w, old_h) for node in d]

    parent_for_text: Optional[dict] = None
    for node, role in zip(d, roles):
        if role == ROLE_FILL:
            _rescale_fill(node, old_w, old_h, new_w, new_h)
        elif role == ROLE_EDGE_STRIP:
            old_rect = _rect_of(node["p"])
            new_geom = _rescale_edge_strip(node, old_w, old_h, new_w, new_h)
            if parent_for_text is None:
                parent_for_text = {
                    "old_cx": old_rect.cx, "old_cy": old_rect.cy,
                    "cx": new_geom["cx"], "cy": new_geom["cy"],
                }

    for node, role in zip(d, roles):
        if role == ROLE_TEXT_OVERLAY:
            _rescale_text_overlay(node, old_w, old_h, new_w, new_h, parent_for_text)
        elif role == ROLE_FREE:
            _rescale_free(node, sx, sy, old_w, old_h, new_w, new_h)

    return data

_TEMPLATES: list[tuple[int, int, str]] = [
    (1920, 1080, "lt1.json"),
    (2560, 1440, "lt2.json"),
    (1280, 960, "lt3.json"),
]

def _layout_dir():
    from pathlib import Path
    return Path(__file__).resolve().parents[2] / "layout"

def _pick_base(width: int, height: int) -> str:
    target_ratio = width / height
    best = None
    best_key = None
    for tw, th, fname in _TEMPLATES:
        ratio_diff = abs((tw / th) - target_ratio)
        area_diff = abs((tw * th) - (width * height))
        key = (ratio_diff, area_diff)
        if best_key is None or key < best_key:
            best_key = key
            best = fname
    assert best is not None
    return best

def _set_title(data: dict, title: str) -> None:
    for node in data.get("d", []):
        if node.get("c") == "ht.Text":
            s = node.setdefault("s", {})
            s["text"] = title
            return

def generate_layout(title: str, width: int, height: int) -> dict:
    import json

    if width <= 0 or height <= 0:
        raise ValueError(f"invalid canvas size: {width}x{height}")

    hit = next(
        (fname for (tw, th, fname) in _TEMPLATES if tw == width and th == height),
        None,
    )
    path = _layout_dir() / (hit if hit else _pick_base(width, height))
    data = json.loads(path.read_text(encoding="utf-8"))

    if hit is None:
        data = rescale_canvas(data, width, height)

    _set_title(data, title)
    return data

if __name__ == "__main__":
    from pathlib import Path
    import json as _json
    _t = input("Title: ")
    _w = int(input("Width: "))
    _h = int(input("Height: "))
    result = generate_layout(_t, _w, _h)
    _out = Path(__file__).resolve().parents[2] / "data" / "bg_ir.json"
    _out.write_text(_json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(_json.dumps(result, ensure_ascii=False, indent=2))
