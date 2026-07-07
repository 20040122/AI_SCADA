from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from model.canva_agent import (
    QualityIssue,
    _calc_content_rect,
    _call_llm,
    _client,
    _dedupe_controls,
    _extract_control_names_from_query,
    _MODEL,
    _quality_check,
    _schema_validate,
    _select_top_controls,
)
from model.get_background import generate_layout
from data.sqlite.material_db import MaterialDB

logger = logging.getLogger(__name__)

GRID_ON_POST_DESERIALIZE = """__ht__function(json, dm, view) { function getTag(d) { return d.getTag ? d.getTag() : d.p && d.p('tag'); } function getAnchor(d) { if (d.getAnchor) return d.getAnchor(); return d.p ? d.p('anchor') : null; } function removeOldGridItems(ownerId) { const removes = []; dm.each(function(d) { if (d && d.a && d.a('_grid.owner') === ownerId) removes.push(d); }); removes.forEach(function(d) { dm.remove(d); }); } function layoutGrid(grid) { if (!grid) return; const ownerId = grid.getId ? grid.getId() : grid.getId; removeOldGridItems(ownerId); const items = grid.a('grid.content') || []; const col = Number(grid.a('grid.col')) || 1; const rowAttr = Number(grid.a('grid.row')); const row = rowAttr > 0 ? rowAttr : Math.ceil(items.length / col); const gap = Number(grid.a('grid.gap')) || 0; const w = grid.getWidth(); const h = grid.getHeight(); const pos = grid.getPosition(); const anchor = getAnchor(grid) || { x: 0.5, y: 0.5 }; const ax = anchor.x == null ? 0.5 : anchor.x; const ay = anchor.y == null ? 0.5 : anchor.y; const left = pos.x - w * ax; const top = pos.y - h * ay; const cellW = (w - gap * (col - 1)) / col; const cellH = (h - gap * (row - 1)) / row; items.forEach(function(item, index) { if (!item || !item.image) return; const r = Math.floor(index / col); const c = index % col; if (r >= row) return; const cellX = left + c * (cellW + gap); const cellY = top + r * (cellH + gap); const origin = item.origin || {}; const node = new ht.Node(); node.setDisplayName(item.displayName || item.name || ''); node.setImage(item.image); const finalW = Number(item.width) || Number(origin.width) || 160; const finalH = Number(item.height) || Number(origin.height) || 240; node.setWidth(finalW); node.setHeight(finalH); node.setPosition(cellX + cellW / 2, cellY + cellH / 2); node.s('2d.movable', true); node.s('2d.editable', true); node.a('_grid.owner', ownerId); node.a('_grid.index', index); node.a('_grid.origin', origin); dm.add(node); }); } dm.each(function(d) { if (getTag(d) === 'grid') layoutGrid(d); }); }"""

TITLE_SYSTEM_PROMPT = '从用户描述中提取简短的SCADA画面标题（2-8 个汉字，如"供气系统""排风系统"）。只输出标题文本，不要解释。'


@dataclass
class LayoutResult:
    json_data: dict
    content_rect: dict
    quality_issues: list[QualityIssue]
    missing_controls: list[str] = field(default_factory=list)


def _build_grid_system_prompt(controls: list[dict], canvas_w: int, canvas_h: int) -> str:
    lines = []
    for c in controls:
        nid = c.get("node_id") or c.get("displayName", "")
        name = c.get("displayName", "")
        cw = c.get("width") or 160
        ch = c.get("height") or 240
        lines.append(f"- {nid} = {name} ({cw}x{ch})")
    controls_info = "\n".join(lines) if lines else "- (无)"
    return (
        "SCADA 网格布局生成器。把控件排进单个网格。\n\n"
        "可用控件（node_id = 名称 (宽x高)）：\n"
        f"{controls_info}\n\n"
        f"画布尺寸：{canvas_w}x{canvas_h}\n\n"
        "输出网格规格 JSON：\n"
        "- row: 行数正整数\n"
        "- col: 列数正整数\n"
        "- gap: 单元间距像素正整数（默认48）\n"
        "- order: 控件 node_id 数组，按行优先（从左到右、从上到下）填入网格\n\n"
        "规则：\n"
        "1. row*col >= order 长度。未明确行列时按 col=ceil(根号n)、row=ceil(n/col)。\n"
        '2. "N列M行" 则 col=N、row=M；"间距X" 或 "间距Xpx" 则 gap=X。\n'
        "3. order 须遵循用户排列意图，未明确则保持上面列表顺序。\n"
        "4. order 只能用上面列出的 node_id，每个出现且仅出现一次，不得遗漏。\n"
        "5. 不得编造控件。\n\n"
        "只输出 JSON，不要解释：\n"
        '{"row":1,"col":2,"gap":48,"order":["名称_1"]}'
    )


def _llm_text(resp) -> str:
    if resp is None:
        return ""
    if isinstance(resp, str):
        return resp
    try:
        return resp.choices[0].message.content or ""
    except Exception:
        return ""


def _parse_json_lenient(text: str) -> Optional[dict]:
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    s = text.find("{")
    e = text.rfind("}")
    if s != -1 and e != -1 and e > s:
        try:
            return json.loads(text[s : e + 1])
        except Exception:
            pass
    return None


_FUZZY_THRESHOLD = 0.6
_LCS_MIN_CHARS = 2


def _fuzzy_match_control(
    name: str, available_names: list[str], threshold: float = _FUZZY_THRESHOLD
) -> Optional[str]:
    if not name or not available_names:
        return None
    if name in available_names:
        return name
    best: Optional[str] = None
    best_score = 0.0
    for cand in available_names:
        if not cand:
            continue
        if name in cand or cand in name:
            score = 0.9
        else:
            score = SequenceMatcher(None, name, cand).ratio()
        if score > best_score:
            best_score = score
            best = cand
    return best if best_score >= threshold else None


def _longest_common_substring_len(a: str, b: str) -> int:
    if not a or not b:
        return 0
    m = SequenceMatcher(None, a, b).find_longest_match(0, len(a), 0, len(b))
    return m.size


async def _load_controls_fuzzy(
    query: str,
    material_db,
    client=None,
    model=None,
) -> tuple[list[dict], list[str]]:
    if material_db is None:
        raise ValueError("未提供 material_db，无法加载控件")

    all_qr = await material_db.list_query_results("")
    if not all_qr:
        return [], []

    rep_rows: dict[str, dict] = {}
    for r in all_qr:
        name = r.get("displayName")
        if not name:
            continue
        cur = rep_rows.get(name)
        if cur is None or float(r.get("similarity", 0.0)) > float(cur.get("similarity", 0.0)):
            rep_rows[name] = r
    available_names = sorted(rep_rows.keys(), key=len, reverse=True)

    specs: list[dict] = []
    missing_names: list[str] = []
    try:
        specs, missing_names = await _extract_control_names_from_query(
            query, material_db, client, model
        )
    except Exception as exc:
        logger.warning("LLM 控件提取失败，使用模糊匹配兜底: %s", exc)

    if not specs:
        specs = []

    resolved_names: list[str] = []
    seen_resolved: set[str] = set()
    for spec in specs:
        raw = spec.get("name", "")
        if not raw:
            continue
        matched = _fuzzy_match_control(raw, available_names)
        if matched and matched not in seen_resolved:
            resolved_names.append(matched)
            seen_resolved.add(matched)
        elif raw not in missing_names:
            missing_names.append(raw)

    q = query or ""
    for name in available_names:
        if name in seen_resolved:
            continue
        if name in q:
            resolved_names.append(name)
            seen_resolved.add(name)
            continue
        if _longest_common_substring_len(q, name) >= _LCS_MIN_CHARS:
            resolved_names.append(name)
            seen_resolved.add(name)

    if not resolved_names:
        return [], missing_names

    spec_count: dict[str, int] = {}
    for spec in specs:
        matched_name = _fuzzy_match_control(spec.get("name", ""), available_names)
        if matched_name:
            spec_count[matched_name] = max(1, int(spec.get("count", 1)))

    matched_controls: list[dict] = []
    for name in resolved_names:
        rows = await material_db.search_query_results_by_name(name)
        if not rows:
            if name not in missing_names:
                missing_names.append(name)
            continue
        count = spec_count.get(name, 1)
        matched_controls.extend(_select_top_controls(rows, name, count))

    return matched_controls, missing_names


def _extract_grid_spec_local(query: str, controls: list[dict]) -> dict:
    n = len(controls)
    q = query or ""
    gap = 48
    m = re.search(r"间距\s*(\d+)", q)
    if m:
        gap = int(m.group(1))
    col = None
    row = None
    m = re.search(r"(\d+)\s*[列条]", q)
    if m:
        col = int(m.group(1))
    m = re.search(r"(\d+)\s*行", q)
    if m:
        row = int(m.group(1))
    default_col = max(1, math.ceil(math.sqrt(n))) if n else 1
    if col is None:
        col = default_col
    if row is None:
        row = max(1, math.ceil(n / col)) if n else 1
    order = [c.get("node_id") or c.get("displayName", "") for c in controls]
    return {"row": int(row), "col": int(col), "gap": int(gap), "order": order}


async def _extract_grid_spec(
    query: str,
    controls: list[dict],
    canvas_w: int,
    canvas_h: int,
    client,
    model,
) -> dict:
    local = _extract_grid_spec_local(query, controls)
    if not client or not model:
        return local
    system_prompt = _build_grid_system_prompt(controls, canvas_w, canvas_h)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": query or ""},
    ]
    try:
        resp = await _call_llm(
            client,
            model,
            messages,
            temperature=0.2,
            stream=False,
            response_format={"type": "json_object"},
        )
        spec = _parse_json_lenient(_llm_text(resp))
        if not spec:
            return local
        order = spec.get("order") or []
        controls_by_id = {c.get("node_id") or c.get("displayName", ""): c for c in controls}
        valid = [o for o in order if o in controls_by_id]
        if len(valid) != len(controls):
            return local
        row = int(spec.get("row") or local["row"])
        col = int(spec.get("col") or local["col"])
        gap = int(spec.get("gap") or local["gap"])
        if row * col < len(valid):
            return local
        return {"row": row, "col": col, "gap": gap, "order": valid}
    except Exception:
        logger.exception("grid spec LLM call failed, using local fallback")
        return local


async def _derive_title(query: str, client, model) -> str:
    if not query:
        return "测试系统"
    if not client or not model:
        return query[:8]
    messages = [
        {"role": "system", "content": TITLE_SYSTEM_PROMPT},
        {"role": "user", "content": query},
    ]
    try:
        resp = await _call_llm(client, model, messages, temperature=0.2, stream=False)
        t = _llm_text(resp).strip().strip('"').strip()
        return t[:8] if t else "测试系统"
    except Exception:
        logger.exception("title LLM call failed, using fallback")
        return query[:8]


def _find_title_bar_bottom(canvas_json: dict) -> float:
    for n in canvas_json.get("d", []):
        p = n.get("p") or {}
        name = p.get("displayName", "") or ""
        if "标题栏" in name:
            pos = p.get("position", {}) or {}
            y = pos.get("y")
            hh = p.get("height")
            if y is not None and hh:
                return y + hh / 2
    return 93


def _compute_grid_geometry(canvas_w: int, canvas_h: int, title_bottom: float) -> dict:
    top_gap = max(20, round(canvas_h * 0.02))
    grid_top = title_bottom + top_gap
    side = max(40, round(canvas_w * 0.03))
    bottom = max(40, round(canvas_h * 0.06))
    grid_w = max(100, canvas_w - side * 2)
    grid_h = max(100, canvas_h - grid_top - bottom)
    return {
        "position": {"x": round(canvas_w / 2), "y": round(grid_top)},
        "anchor": {"x": 0.5, "y": 0},
        "width": grid_w,
        "height": grid_h,
    }


def _alloc_ids(canvas_json: dict):
    max_i = 0
    for n in canvas_json.get("d", []):
        i = n.get("i")
        if isinstance(i, int) and i > max_i:
            max_i = i
    grid_i = max_i + 1
    counter = {"v": grid_i}

    def nxt() -> int:
        counter["v"] += 1
        return counter["v"]

    return grid_i, nxt


def _build_content(order: list[str], controls_by_id: dict[str, dict]) -> list[dict]:
    content = []
    for nid in order:
        ctrl = controls_by_id.get(nid)
        if not ctrl:
            continue
        cw = ctrl.get("width") or 160
        ch = ctrl.get("height") or 240
        content.append(
            {
                "displayName": ctrl.get("displayName", ""),
                "image": ctrl.get("image", ""),
                "fit": "contain",
                "origin": {"x": 0, "y": 0, "width": cw, "height": ch},
            }
        )
    return content


def _build_grid_node(grid_i: int, geom: dict, row: int, col: int, gap: int, content: list[dict]) -> dict:
    return {
        "c": "ht.Node",
        "i": grid_i,
        "p": {
            "displayName": "gridLayout",
            "tag": "grid",
            "image": "symbols/Agent/gridLayout.json",
            "position": geom["position"],
            "anchor": geom["anchor"],
            "width": round(geom["width"]),
            "height": round(geom["height"]),
        },
        "s": {"layout.v": "topbottom", "layout.h": "leftright"},
        "a": {
            "grid.row": str(row),
            "grid.col": col,
            "grid.gap": gap,
            "grid.content": content,
        },
    }


def _build_grid_children(
    grid_i: int,
    next_id,
    content: list[dict],
    row: int,
    col: int,
    gap: int,
    geom: dict,
) -> list[dict]:
    ax = geom["anchor"].get("x", 0.5)
    ay = geom["anchor"].get("y", 0.5)
    left = geom["position"]["x"] - geom["width"] * ax
    top = geom["position"]["y"] - geom["height"] * ay
    cell_w = (geom["width"] - gap * (col - 1)) / col
    cell_h = (geom["height"] - gap * (row - 1)) / row
    children = []
    for index, item in enumerate(content):
        r = index // col
        c = index % col
        if r >= row:
            break
        cell_x = left + c * (cell_w + gap)
        cell_y = top + r * (cell_h + gap)
        origin = item.get("origin", {}) or {}
        final_w = item.get("width") or origin.get("width") or 160
        final_h = item.get("height") or origin.get("height") or 240
        children.append(
            {
                "c": "ht.Node",
                "i": next_id(),
                "p": {
                    "displayName": item.get("displayName", ""),
                    "image": item.get("image", ""),
                    "position": {
                        "x": round(cell_x + cell_w / 2),
                        "y": round(cell_y + cell_h / 2),
                    },
                    "width": final_w,
                    "height": final_h,
                },
                "a": {
                    "_grid.owner": grid_i,
                    "_grid.index": index,
                    "_grid.origin": origin,
                },
            }
        )
    return children


def _flatten_children(children: list[dict]) -> list[dict]:
    flat = []
    for ch in children:
        p = ch.get("p") or {}
        pos = p.get("position", {}) or {}
        flat.append(
            {
                "x": pos.get("x", 0),
                "y": pos.get("y", 0),
                "width": p.get("width", 0) or 0,
                "height": p.get("height", 0) or 0,
                "displayName": p.get("displayName", ""),
            }
        )
    return flat


class LayoutAgent:
    def __init__(self, db=None, client=None, model=None):
        self._db = db
        self._client = client if client is not None else _client
        self._model = model if model is not None else _MODEL

    async def create_canvas(
        self,
        title: str,
        width: int,
        height: int,
        query: Optional[str] = None,
    ) -> dict:
        if not title:
            if query:
                title = await _derive_title(query, self._client, self._model)
            else:
                title = "测试系统"
        return generate_layout(title, width, height)

    async def apply_grid_layout(
        self,
        canvas_json: dict,
        query: str,
        controls: Optional[list[dict]] = None,
    ) -> LayoutResult:
        a = canvas_json.get("a", {}) or {}
        w = int(a.get("width") or 0)
        h = int(a.get("height") or 0)
        if w <= 0 or h <= 0:
            raise ValueError("canvas_json 缺少 a.width / a.height")

        title_bottom = _find_title_bar_bottom(canvas_json)

        missing: list[str] = []
        if controls is None:
            controls, missing = await _load_controls_fuzzy(
                query, self._db, self._client, self._model
            )
            controls = _dedupe_controls(controls)
            for c in controls:
                idx = c.get("_instance_index")
                c["node_id"] = (
                    f"{c['displayName']}_{idx}" if idx is not None else c["displayName"]
                )
        if not controls:
            raise ValueError("无可用控件，无法进行网格布局")

        spec = await _extract_grid_spec(query, controls, w, h, self._client, self._model)
        controls_by_id = {c.get("node_id") or c.get("displayName", ""): c for c in controls}
        content = _build_content(spec["order"], controls_by_id)

        geom = _compute_grid_geometry(w, h, title_bottom)
        grid_i, child_id_iter = _alloc_ids(canvas_json)
        grid_node = _build_grid_node(
            grid_i, geom, spec["row"], spec["col"], spec["gap"], content
        )
        children = _build_grid_children(
            grid_i, child_id_iter, content, spec["row"], spec["col"], spec["gap"], geom
        )

        out = dict(canvas_json)
        out["d"] = list(canvas_json.get("d", [])) + [grid_node] + children
        new_a = dict(canvas_json.get("a", {}) or {})
        new_a["onPostDeserialize"] = GRID_ON_POST_DESERIALIZE
        out["a"] = new_a

        flat = _flatten_children(children)
        out["contentRect"] = _calc_content_rect(flat)

        errors = await _schema_validate(out)
        if errors:
            logger.warning("schema 校验失败: %s", errors)
        quality = _quality_check(flat, w, h)

        return LayoutResult(
            json_data=out,
            content_rect=out["contentRect"],
            quality_issues=quality,
            missing_controls=list(missing),
        )


def _cli() -> None:
    query = input("query: ").strip()
    w = int(input("width [1920]: ").strip() or "1920")
    h = int(input("height [1080]: ").strip() or "1080")
    title = input("title (空=自动): ").strip()

    async def run() -> LayoutResult:
        db = MaterialDB()
        try:
            await db.init_db()
        except Exception:
            logger.exception("MaterialDB init failed")
        agent = LayoutAgent(db=db)
        canvas = await agent.create_canvas(title, w, h, query=query or None)
        return await agent.apply_grid_layout(canvas, query or "测试")

    result = asyncio.run(run())
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path("output")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"layout_{ts}.json"
    out_path.write_text(
        json.dumps(result.json_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"saved: {out_path}")
    print(f"content_rect: {result.content_rect}")
    print(f"quality_issues: {len(result.quality_issues)}")
    for qi in result.quality_issues:
        print(f"  [{qi.severity}] {qi.issue_type}: {qi.message}")
    print(f"missing_controls: {result.missing_controls}")


if __name__ == "__main__":
    _cli()
