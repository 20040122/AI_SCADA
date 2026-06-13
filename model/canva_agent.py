from __future__ import annotations
import asyncio
import json
import logging
import math
import os
import random
import re
import sys
from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path
import jsonschema
from dotenv import load_dotenv
from openai import AsyncOpenAI

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))
from data.material_db import MaterialDB
logger = logging.getLogger(__name__)
load_dotenv(".env.local")

_client = AsyncOpenAI(
    api_key=os.environ.get("DEEPSEEK_API_KEY"),
    base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
)
_MODEL = os.environ.get("DEEPSEEK_MODEL")
_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "data" / "canvas_schema.json"


EXTRACT_HINTS_PROMPT = """\
SCADA 组态意图提取器。从用户描述中提取明确表达的布局偏好。

可用控件：
{controls_info}

可选 region 枚举：
- left, right, top, bottom, center
- left_top, right_top, left_bottom, right_bottom

规则：
1. 只能使用上面列出的控件名称，不得编造
2. 仅当用户明确表达了位置意图时才输出（如"右上角"、"靠左"、"放在中间"等）
3. placement_hints 中每个对象包含 target（控件名）和 region（方位）

只输出 JSON，不要解释：
{{
  "placement_hints": [
    {{"target": "", "region": "left"}}
  ]
}}
"""

FALLBACK_EXTRACT_PROMPT = """\
SCADA 组态语义分析器。根据用户描述，为每个控件分配布局位置。
要求：
1. 只能使用query_results中的displayName,不得编造名称。
2. placements: 为每个控件分配一个region，表示其应放置的方向区域。
   可选 region 枚举：
   - left, right, top, bottom, center
   - left_top, right_top, left_bottom, right_bottom
3. placement_hints 表示用户明确表达的布局意图，只能使用上述 region 枚举。
4. 只有当用户明确表达了位置意图时才输出 placement_hints。
只输出 JSON,不要解释:
{{
  "placements": [
    {{"target": "", "region": "left"}}
  ],
  "placement_hints": [
    {{"target": "", "region": "left"}}
  ]
}}
"""

EXTRACT_CONTROLS_PROMPT = """\
SCADA 控件检索器。从用户描述中提取需要的控件名称和数量。
给定可用控件列表:
{controls_list}
要求：
1. 只能从上面的可用控件列表中选取名称，不得编造。
2. name 必须与列表中的 displayName 完全匹配。
3. count 是用户需要的数量，未明确数量时默认为1。
4. 如果用户描述中没有提到任何控件，返回空数组。
只输出 JSON,不要解释:
[
  {{"name": "", "count": 1}}
]
"""

REFINE_PROMPT = """\
SCADA 画布布局微调器。你只能调整节点的 x 和 y 坐标。
画布尺寸：
width={canvas_width}, height={canvas_height}
输入节点 JSON:
{layout_json}
硬性约束：
1. 不得新增、删除、重命名节点。
2. 不得修改 displayName、image、width、height。
3. 所有节点必须完整位于画布内。
4. 尽量避免重叠。
5. 各控件保持在原有大致区域（左上/上/右上/左/中/右/左下/下/右下），微调时避免跨区域大幅移动。
6. x、y 必须是整数。
只输出 JSON,不要解释:
{{"nodes":[{{"displayName":"","image":"","width":0,"height":0,"x":0,"y":0}}]}}
"""

DSL_PROMPT = """\
SCADA 控制流图生成器。根据用户描述和可用控件，生成 Mermaid flowchart DSL。
方向选择：画布 {canvas_width}x{canvas_height}，width>=height时用LR，否则用TB。

可用控件（仅使用这些名称作为节点label）：
{controls_list}

已知用户位置意图（仅供参考，可在flowchart中体现）：
{hints_text}

规则：
1. 节点格式为 id[label]，label 必须是上面列出的控件 displayName，id 使用英文或拼音缩写
2. 主流程使用 -->（实线箭头）
3. 控制/调节关系使用 -.->（虚线箭头）
4. 只包含可用控件列表中的名称，不得编造
5. 用 direction LR 或 TB 声明方向

只输出 Mermaid flowchart，不要任何解释：
flowchart LR
    ...
"""


VALID_REGIONS = {
    "left", "right", "top", "bottom", "center",
    "left_top", "right_top", "left_bottom", "right_bottom",
}
REGION_SYNONYMS = {
    "左": "left",
    "左侧": "left",
    "左面": "left",
    "靠左": "left",
    "右": "right",
    "右侧": "right",
    "右面": "right",
    "靠右": "right",
    "上": "top",
    "上方": "top",
    "顶部": "top",
    "下": "bottom",
    "下方": "bottom",
    "底部": "bottom",
    "中间": "center",
    "居中": "center",
    "左上": "left_top",
    "左上角": "left_top",
    "右上": "right_top",
    "右上角": "right_top",
    "左下": "left_bottom",
    "左下角": "left_bottom",
    "右下": "right_bottom",
    "右下角": "right_bottom",
}

REGION_ANCHORS = {
    "left_top": (0.15, 0.12),
    "top": (0.50, 0.12),
    "right_top": (0.85, 0.12),
    "left": (0.15, 0.50),
    "center": (0.50, 0.50),
    "right": (0.85, 0.50),
    "left_bottom": (0.15, 0.88),
    "bottom": (0.50, 0.88),
    "right_bottom": (0.85, 0.88),
}


@dataclass
class GraphNode:
    id: str
    label: str


@dataclass
class GraphEdge:
    from_id: str
    to_id: str
    type: str


@dataclass
class FlowGraph:
    direction: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]


@dataclass
class PlacementHint:
    target: str
    region: str


@dataclass
class LayoutRequirement:
    canvas_width: int
    canvas_height: int
    controls: list[dict]
    placements: list[PlacementHint]
    placement_hints: list[PlacementHint]


@dataclass
class LayoutZone:
    name: str
    x: float
    y: float
    width: float
    height: float
    controls: list[str]


@dataclass
class LayoutSkeleton:
    zones: list[LayoutZone]


@dataclass
class QualityIssue:
    severity: str
    issue_type: str
    message: str
    controls: list[str]


@dataclass
class CanvasResult:
    json_data: dict
    content_rect: dict
    quality_issues: list[QualityIssue]
    skeleton: LayoutSkeleton
    missing_controls: list[str] = field(default_factory=list)


def _normalize_region(region: str) -> str:
    if not region:
        return ""
    value = region.strip().lower()
    if value in VALID_REGIONS:
        return value
    return REGION_SYNONYMS.get(region.strip(), "")


def _extract_placement_hints_from_query(query: str, controls: list[dict]) -> list[PlacementHint]:
    hints: list[PlacementHint] = []
    seen: set[str] = set()
    for ctrl in controls:
        name = ctrl["displayName"]
        idx = query.find(name)
        if idx < 0:
            continue
        window_start = max(0, idx - 8)
        window_end = min(len(query), idx + len(name) + 8)
        context = query[window_start:window_end]
        region = ""
        for keyword in sorted(REGION_SYNONYMS, key=len, reverse=True):
            if keyword in context:
                region = REGION_SYNONYMS[keyword]
                break
        if not region or name in seen:
            continue
        hints.append(PlacementHint(target=name, region=region))
        seen.add(name)
    return hints


def _sanitize_placement_hints(hints: list[dict], controls: list[dict]) -> list[PlacementHint]:
    all_names = {c["displayName"] for c in controls}
    clean: list[PlacementHint] = []
    seen: set[str] = set()
    for hint in hints:
        target = hint.get("target")
        region = _normalize_region(hint.get("region", ""))
        if target not in all_names or not region or target in seen:
            continue
        clean.append(PlacementHint(target=target, region=region))
        seen.add(target)
    return clean


def _build_requirement_from_data(
    data: dict,
    controls: list[dict],
    canvas_w: int,
    canvas_h: int,
) -> LayoutRequirement:
    all_names = {c["displayName"] for c in controls}

    llm_placements = data.get("placements", [])
    assigned: set[str] = set()
    placements: list[PlacementHint] = []
    for item in llm_placements:
        name = item.get("target", "")
        region = item.get("region", "")
        if name in all_names and region in VALID_REGIONS:
            placements.append(PlacementHint(target=name, region=region))
            assigned.add(name)

    LARGE_DEVICE_SIZE = 200
    for ctrl in controls:
        name = ctrl["displayName"]
        if name in assigned:
            continue
        w = ctrl.get("width") or 0
        h = ctrl.get("height") or 0
        if w >= LARGE_DEVICE_SIZE or h >= LARGE_DEVICE_SIZE:
            placements.append(PlacementHint(target=name, region="left"))
        else:
            placements.append(PlacementHint(target=name, region="right_top"))

    placement_hints = _sanitize_placement_hints(data.get("placement_hints", []), controls)
    if not placement_hints:
        placement_hints = _extract_placement_hints_from_query(data.get("_source_query", ""), controls)
    return LayoutRequirement(
        canvas_width=canvas_w,
        canvas_height=canvas_h,
        controls=controls,
        placements=placements,
        placement_hints=placement_hints,
    )


async def _extract_layout_requirements(
    query: str, controls: list[dict], canvas_w: int, canvas_h: int
) -> LayoutRequirement:
    controls_info = "\n".join(
        f"- {c['displayName']} (宽{c.get('width',0)}x高{c.get('height',0)})"
        for c in controls
    )
    prompt = FALLBACK_EXTRACT_PROMPT.format(controls_info=controls_info)
    data: dict = {}
    if not _MODEL:
        logger.warning("未配置 DEEPSEEK_MODEL，使用本地尺寸兜底布局")
    else:
        try:
            response = await _client.chat.completions.create(
                model=_MODEL,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": query},
                ],
                stream=False,
                reasoning_effort="low",
                response_format={"type": "json_object"},
                extra_body={"thinking": {"type": "enabled"}},
            )
            data = json.loads(response.choices[0].message.content)
        except Exception as exc:
            logger.warning("布局需求抽取失败，使用本地尺寸兜底: %s", exc)
    data["_source_query"] = query

    return _build_requirement_from_data(data, controls, canvas_w, canvas_h)


async def _extract_hints_only(query: str, controls: list[dict]) -> list[PlacementHint]:
    controls_info = "\n".join(
        f"- {c['displayName']} (宽{c.get('width',0)}x高{c.get('height',0)})"
        for c in controls
    )
    prompt = EXTRACT_HINTS_PROMPT.format(controls_info=controls_info)
    hints: list[PlacementHint] = []
    if not _MODEL:
        logger.warning("未配置 DEEPSEEK_MODEL，使用本地正则提取 hints")
    else:
        try:
            response = await _client.chat.completions.create(
                model=_MODEL,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": query},
                ],
                stream=False,
                reasoning_effort="low",
                response_format={"type": "json_object"},
                extra_body={"thinking": {"type": "enabled"}},
            )
            data = json.loads(response.choices[0].message.content)
            hints = _sanitize_placement_hints(data.get("placement_hints", []), controls)
        except Exception as exc:
            logger.warning("hints 提取失败，使用本地正则兜底: %s", exc)

    if not hints:
        hints = _extract_placement_hints_from_query(query, controls)
    return hints


async def _generate_flow_dsl(
    query: str,
    controls: list[dict],
    hints: list[PlacementHint],
    cw: int,
    ch: int,
) -> str:
    controls_list = "\n".join(f"- {c['displayName']}" for c in controls)
    hints_text = " ".join(f"{h.target}放{h.region}" for h in hints) if hints else "无"
    prompt = DSL_PROMPT.format(
        canvas_width=cw,
        canvas_height=ch,
        controls_list=controls_list,
        hints_text=hints_text,
    )
    if not _MODEL:
        logger.warning("未配置 DEEPSEEK_MODEL，跳过 DSL 生成")
        return ""
    try:
        response = await _client.chat.completions.create(
            model=_MODEL,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": query},
            ],
            stream=False,
            reasoning_effort="low",
            response_format={"type": "text"},
            extra_body={"thinking": {"type": "enabled"}},
        )
        content = response.choices[0].message.content
        return content.strip() if content else ""
    except Exception as exc:
        logger.warning("DSL 生成失败: %s", exc)
        return ""


_NODE_RE = re.compile(
    r'(\w+)\s*(?:\[([^\]]+)\]|\(([^)]+)\)|\{([^}]+)\}|\(\(([^)]+)\)\)|>([^\]]+)\])'
)
_EDGE_SPLIT_RE = re.compile(r'\s*(-+\.?\.*\-+>|==+>)\s*')


def _fuzzy_match_label(label: str, name_set: set[str]) -> str | None:
    if label in name_set:
        return label
    candidates = []
    for name in name_set:
        if label in name or name in label:
            candidates.append((name, len(name)))
    if candidates:
        candidates.sort(key=lambda x: -x[1])
        return candidates[0][0]
    return None


_BARE_ID_RE = re.compile(r'^\w+$')
_EDGE_LABEL_STRIP_RE = re.compile(r'^\|[^|]*\|\s*')


def _parse_flow_dsl(dsl: str, controls: list[dict]) -> FlowGraph | None:
    lines = dsl.strip().splitlines()
    direction = "LR"
    all_nodes: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("%%"):
            continue

        dir_match = re.match(r'flowchart\s+(LR|TB|RL|BT)', line, re.IGNORECASE)
        if dir_match:
            direction = dir_match.group(1).upper()
            continue

        for m in _NODE_RE.finditer(line):
            nid = m.group(1)
            label = m.group(2) or m.group(3) or m.group(4) or m.group(5) or m.group(6) or ""
            label = label.strip()
            if nid not in all_nodes:
                all_nodes[nid] = GraphNode(id=nid, label=label)

        parts = _EDGE_SPLIT_RE.split(line)
        parts = [_EDGE_LABEL_STRIP_RE.sub('', p).strip() for p in parts]
        parts = [p for p in parts if p]
        if len(parts) < 3:
            continue

        chain_ids: list[str] = []
        for part in parts:
            m = _NODE_RE.match(part)
            if m:
                chain_ids.append(m.group(1))
            elif _BARE_ID_RE.match(part) and part in all_nodes:
                chain_ids.append(part)

        for i in range(len(chain_ids) - 1):
            edge_str = parts[i * 2 + 1]
            etype = "dotted" if "." in edge_str else "solid"
            edges.append(GraphEdge(
                from_id=chain_ids[i],
                to_id=chain_ids[i + 1],
                type=etype,
            ))

    if not all_nodes:
        return None

    name_set = {c["displayName"] for c in controls}
    for node in list(all_nodes.values()):
        if node.label in name_set:
            continue
        best = _fuzzy_match_label(node.label, name_set)
        if best:
            node.label = best

    return FlowGraph(direction=direction, nodes=list(all_nodes.values()), edges=edges)


def _topological_layers(graph: FlowGraph) -> list[list[str]]:
    in_degree: dict[str, int] = {n.id: 0 for n in graph.nodes}
    adj: dict[str, list[str]] = {n.id: [] for n in graph.nodes}

    for edge in graph.edges:
        if edge.from_id in adj and edge.to_id in in_degree:
            adj[edge.from_id].append(edge.to_id)
            in_degree[edge.to_id] += 1

    layers: list[list[str]] = []
    queue = [nid for nid, deg in in_degree.items() if deg == 0]

    while queue:
        layers.append(queue[:])
        next_queue: list[str] = []
        for nid in queue:
            for neighbor in adj.get(nid, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    next_queue.append(neighbor)
        queue = next_queue

    return layers


def _graph_to_region_map(graph: FlowGraph, hints: list[PlacementHint]) -> dict[str, str]:
    layers = _topological_layers(graph)
    num_layers = len(layers)
    region_map: dict[str, str] = {}

    for layer_idx, node_ids in enumerate(layers):
        layer_nodes = [n for n in graph.nodes if n.id in node_ids]
        n_in_layer = len(layer_nodes)

        for pos_idx, node in enumerate(layer_nodes):
            if graph.direction in ("LR", "RL"):
                if num_layers == 1:
                    h = "center"
                elif layer_idx == 0:
                    h = "left"
                elif layer_idx == num_layers - 1:
                    h = "right"
                else:
                    ratio = layer_idx / (num_layers - 1)
                    if ratio < 0.33:
                        h = "left"
                    elif ratio > 0.67:
                        h = "right"
                    else:
                        h = "center"

                if n_in_layer == 1:
                    v = ""
                elif pos_idx == 0:
                    v = "_top"
                elif pos_idx == n_in_layer - 1:
                    v = "_bottom"
                else:
                    v = ""
                region = f"{h}{v}" or h
            else:
                if num_layers == 1:
                    v = "center"
                elif layer_idx == 0:
                    v = "top"
                elif layer_idx == num_layers - 1:
                    v = "bottom"
                else:
                    ratio = layer_idx / (num_layers - 1)
                    if ratio < 0.33:
                        v = "top"
                    elif ratio > 0.67:
                        v = "bottom"
                    else:
                        v = "center"

                if n_in_layer == 1:
                    h = ""
                elif pos_idx == 0:
                    h = "left_"
                elif pos_idx == n_in_layer - 1:
                    h = "right_"
                else:
                    h = ""
                region = f"{h}{v}" or v

            region_map[node.label] = region

    control_ids = {e.from_id for e in graph.edges if e.type == "dotted"}
    if graph.direction in ("LR", "RL"):
        for node in graph.nodes:
            if node.id in control_ids and node.label in region_map:
                region_map[node.label] = "right_top"
    else:
        for node in graph.nodes:
            if node.id in control_ids and node.label in region_map:
                region_map[node.label] = "right_bottom"

    for hint in hints:
        region_map[hint.target] = hint.region

    return region_map


def _generate_skeleton(requirement: LayoutRequirement, region_map: dict[str, str]) -> LayoutSkeleton:
    zones = _apply_layout_constraints(requirement, region_map)
    return LayoutSkeleton(zones=zones)


def _sort_controls_for_region(names: list[str], hint_map: dict[str, str]) -> list[str]:
    order = {
        "left_top": 0,
        "right_top": 0,
        "top": 1,
        "left": 2,
        "center": 3,
        "right": 4,
        "bottom": 5,
        "left_bottom": 6,
        "right_bottom": 6,
    }
    return sorted(names, key=lambda name: (order.get(hint_map.get(name, ""), 3), name))


def _resolve_zone_overlaps(zones: list[LayoutZone], cw: int, ch: int, gap: float) -> None:
    for _ in range(6):
        moved = False
        for i in range(len(zones)):
            for j in range(i + 1, len(zones)):
                z1, z2 = zones[i], zones[j]
                ox = max(0.0, min(z1.x + z1.width, z2.x + z2.width) - max(z1.x, z2.x))
                oy = max(0.0, min(z1.y + z1.height, z2.y + z2.height) - max(z1.y, z2.y))
                if ox <= 0 or oy <= 0:
                    continue
                if ox < oy:
                    dx = (ox + gap) / 2.0
                    if z1.x < z2.x:
                        z1.x -= dx
                        z2.x += dx
                    else:
                        z1.x += dx
                        z2.x -= dx
                else:
                    dy = (oy + gap) / 2.0
                    if z1.y < z2.y:
                        z1.y -= dy
                        z2.y += dy
                    else:
                        z1.y += dy
                        z2.y -= dy
                moved = True
        if not moved:
            break

    for z in zones:
        z.x = round(max(gap, min(cw - z.width - gap, z.x)))
        z.y = round(max(gap, min(ch - z.height - gap, z.y)))


def _apply_layout_constraints(requirement: LayoutRequirement, region_map: dict[str, str]) -> list[LayoutZone]:
    cw = requirement.canvas_width
    ch = requirement.canvas_height
    ctrl_map = {c["displayName"]: c for c in requirement.controls}

    region_groups: dict[str, list[str]] = {}
    for ctrl in requirement.controls:
        name = ctrl["displayName"]
        region = region_map.get(name, "center")
        if region not in region_groups:
            region_groups[region] = []
        region_groups[region].append(name)

    for region in region_groups:
        region_groups[region] = _sort_controls_for_region(region_groups[region], region_map)

    gap = 40
    padding = 20
    zones: list[LayoutZone] = []

    for region, control_names in region_groups.items():
        region_ctrls = [ctrl_map[n] for n in control_names if n in ctrl_map]
        if not region_ctrls:
            continue

        total_h = sum(c.get("height") or 0 for c in region_ctrls) + padding * (len(region_ctrls) - 1)
        max_w = max((c.get("width") or 0 for c in region_ctrls), default=0)
        zone_w = max(max_w + gap * 2, 100)
        zone_h = max(total_h + gap * 2, 100)

        anchor_x_ratio, anchor_y_ratio = REGION_ANCHORS.get(region, (0.5, 0.5))
        anchor_x = cw * anchor_x_ratio
        anchor_y = ch * anchor_y_ratio
        zone_x = round(anchor_x - zone_w / 2)
        zone_y = round(anchor_y - zone_h / 2)

        zone_x = max(gap, min(cw - zone_w - gap, zone_x))
        zone_y = max(gap, min(ch - zone_h - gap, zone_y))

        zones.append(LayoutZone(
            name=region,
            x=zone_x,
            y=zone_y,
            width=round(zone_w),
            height=round(zone_h),
            controls=control_names,
        ))

    _resolve_zone_overlaps(zones, cw, ch, gap * 0.75)
    return zones


def _compute_coordinates(
    skeleton: LayoutSkeleton,
    controls: list[dict],
    canvas_w: int,
    canvas_h: int,
) -> list[dict]:
    ctrl_map = {c["displayName"]: c for c in controls}
    total = len(controls)

    if total > 20:
        return _force_directed_layout(skeleton, controls, canvas_w, canvas_h)

    PADDING = {
        "left": 30,
        "left_top": 20,
        "left_bottom": 20,
        "center": 25,
        "right": 20,
        "right_top": 20,
        "right_bottom": 20,
        "top": 20,
        "bottom": 20,
    }

    nodes = []
    for zone in skeleton.zones:
        zone_controls = zone.controls
        if not zone_controls:
            continue

        zone_ctrls = [ctrl_map[n] for n in zone_controls if n in ctrl_map]
        if not zone_ctrls:
            continue

        padding = PADDING.get(zone.name, 20)

        sizes = [(c.get("width") or 0, c.get("height") or 0) for c in zone_ctrls]
        total_h = sum(h for _, h in sizes) + padding * (len(sizes) - 1)

        if len(zone_ctrls) <= 6:
            start_y = zone.y + (zone.height - total_h) / 2
            cx = zone.x + zone.width / 2
            cursor_y = start_y
            for ctrl, (w, h) in zip(zone_ctrls, sizes):
                nodes.append({
                    "displayName": ctrl["displayName"],
                    "image": ctrl.get("image", ""),
                    "width": w,
                    "height": h,
                    "x": round(cx),
                    "y": round(cursor_y + h / 2),
                })
                cursor_y += h + padding
        else:
            MARGIN = 20
            content_h = zone.height - MARGIN * 2
            cols = []
            cur_col: list[dict] = []
            cur_h = 0.0
            for ctrl, (w, h) in zip(zone_ctrls, sizes):
                space = h + (padding if cur_col else 0)
                if cur_col and cur_h + space > content_h:
                    cols.append(cur_col)
                    cur_col = [ctrl]
                    cur_h = h
                else:
                    cur_col.append(ctrl)
                    cur_h += space
            if cur_col:
                cols.append(cur_col)

            col_widths = [max(c.get("width") or 0 for c in col) for col in cols]
            content_x = zone.x + MARGIN
            content_w = zone.width - MARGIN * 2
            total_col_w = sum(col_widths) + padding * (len(cols) - 1)
            col_start_x = content_x + (content_w - total_col_w) / 2

            offset_x = col_start_x
            for col, col_w in zip(cols, col_widths):
                col_cx = offset_x + col_w / 2
                col_h = sum(c.get("height") or 0 for c in col) + padding * (len(col) - 1)
                col_start_y = zone.y + (zone.height - col_h) / 2
                cursor_y = col_start_y
                for ctrl in col:
                    h = ctrl.get("height") or 0
                    nodes.append({
                        "displayName": ctrl["displayName"],
                        "image": ctrl.get("image", ""),
                        "width": ctrl.get("width", 0),
                        "height": h,
                        "x": round(col_cx),
                        "y": round(cursor_y + h / 2),
                    })
                    cursor_y += h + padding
                offset_x += col_w + padding

    return nodes


def _scale_to_canvas(nodes: list[dict], canvas_w: int, canvas_h: int) -> list[dict]:
    if not nodes:
        return nodes
    margin = 20
    rect = _calc_content_rect(nodes)
    if rect["width"] <= 0 or rect["height"] <= 0:
        return nodes

    max_scale = 2.0
    needed_w = rect["width"] + margin * 2
    needed_h = rect["height"] + margin * 2
    scale_x = canvas_w / needed_w
    scale_y = canvas_h / needed_h
    scale = min(scale_x, scale_y, max_scale)

    new_w = canvas_w - margin * 2
    new_h = canvas_h - margin * 2
    for n in nodes:
        n["x"] = round(margin + (n["x"] - rect["x"]) * scale + (new_w - rect["width"] * scale) / 2)
        n["y"] = round(margin + (n["y"] - rect["y"]) * scale + (new_h - rect["height"] * scale) / 2)
    _clamp_nodes_to_canvas(nodes, canvas_w, canvas_h)
    return nodes


def _clamp_nodes_to_canvas(nodes: list[dict], canvas_w: int, canvas_h: int) -> None:
    for n in nodes:
        w = (n.get("width") or 0) or 60
        h = (n.get("height") or 0) or 40
        half_w = w / 2
        half_h = h / 2
        if canvas_w > 0:
            n["x"] = round(max(half_w, min(canvas_w - half_w, n.get("x", 0))))
        if canvas_h > 0:
            n["y"] = round(max(half_h, min(canvas_h - half_h, n.get("y", 0))))


def _force_directed_layout(
    skeleton: LayoutSkeleton,
    controls: list[dict],
    canvas_w: int,
    canvas_h: int,
    iterations: int = 100,
) -> list[dict]:
    all_names = [c["displayName"] for c in controls]
    rng = random.Random(0)

    positions: dict[str, list[float]] = {}
    zone_center: dict[str, list[float]] = {}
    for zone in skeleton.zones:
        zx = zone.x + zone.width / 2
        zy = zone.y + zone.height / 2
        zone_center[zone.name] = [zx, zy]
        for name in zone.controls:
            if name not in positions:
                positions[name] = [zx + rng.uniform(-30, 30), zy + rng.uniform(-30, 30)]

    for name in all_names:
        if name not in positions:
            positions[name] = [canvas_w / 2 + rng.uniform(-50, 50), canvas_h / 2 + rng.uniform(-50, 50)]

    repulsion_k = 5000.0
    zone_attract_k = 0.02
    dampening = 0.9

    velocities: dict[str, list[float]] = {n: [0.0, 0.0] for n in all_names}

    for _ in range(iterations):
        forces: dict[str, list[float]] = {n: [0.0, 0.0] for n in all_names}

        for i, n1 in enumerate(all_names):
            for j, n2 in enumerate(all_names):
                if i >= j:
                    continue
                dx = positions[n1][0] - positions[n2][0]
                dy = positions[n1][1] - positions[n2][1]
                dist = math.sqrt(dx * dx + dy * dy) + 1e-6
                f_mag = repulsion_k / (dist * dist)
                fx = f_mag * dx / dist
                fy = f_mag * dy / dist
                forces[n1][0] += fx
                forces[n1][1] += fy
                forces[n2][0] -= fx
                forces[n2][1] -= fy

        for zone in skeleton.zones:
            zx = zone_center[zone.name][0]
            zy = zone_center[zone.name][1]
            for name in zone.controls:
                if name in forces:
                    dx = zx - positions[name][0]
                    dy = zy - positions[name][1]
                    forces[name][0] += zone_attract_k * dx
                    forces[name][1] += zone_attract_k * dy

        for name in all_names:
            velocities[name][0] = (velocities[name][0] + forces[name][0]) * dampening
            velocities[name][1] = (velocities[name][1] + forces[name][1]) * dampening
            positions[name][0] += velocities[name][0]
            positions[name][1] += velocities[name][1]
            positions[name][0] = max(50, min(canvas_w - 50, positions[name][0]))
            positions[name][1] = max(50, min(canvas_h - 50, positions[name][1]))

    for name in all_names:
        positions[name][0] = round(positions[name][0])
        positions[name][1] = round(positions[name][1])

    nodes = []
    for c in controls:
        name = c["displayName"]
        pos = positions.get(name, [canvas_w / 2, canvas_h / 2])
        nodes.append({
            "displayName": name,
            "image": c.get("image", ""),
            "width": c.get("width", 0),
            "height": c.get("height", 0),
            "x": pos[0],
            "y": pos[1],
        })

    return nodes


async def _refine_layout_with_llm(
    nodes: list[dict], canvas_w: int, canvas_h: int
) -> list[dict]:
    if not _MODEL:
        logger.warning("未配置 DEEPSEEK_MODEL，跳过 LLM 布局微调")
        return nodes

    layout_json = json.dumps(nodes, ensure_ascii=False, indent=2)
    prompt = REFINE_PROMPT.format(
        canvas_width=canvas_w,
        canvas_height=canvas_h,
        layout_json=layout_json,
    )
    try:
        response = await _client.chat.completions.create(
            model=_MODEL,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": "请微调以上布局坐标，使其更合理。"},
            ],
            stream=False,
            reasoning_effort="low",
            response_format={"type": "json_object"},
            extra_body={"thinking": {"type": "enabled"}},
        )
        data = json.loads(response.choices[0].message.content)
    except Exception as exc:
        logger.warning("LLM 布局微调失败，保留规则布局: %s", exc)
        return nodes

    refined = data if isinstance(data, list) else data.get("nodes", data.get("d", []))
    return _merge_refined_nodes(nodes, refined, canvas_w, canvas_h)


def _merge_refined_nodes(
    original: list[dict], refined: list[dict], canvas_w: int, canvas_h: int
) -> list[dict]:
    if not isinstance(refined, list):
        return original

    refined_by_name = {
        n.get("displayName"): n
        for n in refined
        if isinstance(n, dict) and n.get("displayName")
    }
    result: list[dict] = []
    for node in original:
        merged = dict(node)
        refined_node = refined_by_name.get(node["displayName"], {})
        try:
            merged["x"] = round(float(refined_node.get("x", node["x"])))
            merged["y"] = round(float(refined_node.get("y", node["y"])))
        except (TypeError, ValueError):
            merged["x"] = node["x"]
            merged["y"] = node["y"]
        result.append(merged)

    _clamp_nodes_to_canvas(result, canvas_w, canvas_h)
    return result


def _calc_content_rect(nodes: list[dict]) -> dict:
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


def _quality_check(nodes: list[dict], canvas_w: int = 0, canvas_h: int = 0) -> list[QualityIssue]:
    issues: list[QualityIssue] = []

    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            n1 = nodes[i]
            n2 = nodes[j]
            overlap = _compute_overlap_ratio(n1, n2)
            if overlap > 0.10:
                issues.append(QualityIssue(
                    severity="warning",
                    issue_type="overlap",
                    message=f"控件 {n1['displayName']} 与 {n2['displayName']} 重叠率 {overlap:.1%}",
                    controls=[n1["displayName"], n2["displayName"]],
                ))

    if canvas_w > 0 and canvas_h > 0:
        for n in nodes:
            w = (n.get("width") or 0) or 60
            h = (n.get("height") or 0) or 40
            x_min = n.get("x", 0) - w / 2
            x_max = n.get("x", 0) + w / 2
            y_min = n.get("y", 0) - h / 2
            y_max = n.get("y", 0) + h / 2
            overflow_parts = []
            if x_min < 0 or x_max > canvas_w:
                overflow_parts.append(f"水平({'%.0f' % x_min},{'%.0f' % x_max})")
            if y_min < 0 or y_max > canvas_h:
                overflow_parts.append(f"垂直({'%.0f' % y_min},{'%.0f' % y_max})")
            if overflow_parts:
                issues.append(QualityIssue(
                    severity="error",
                    issue_type="overflow",
                    message=f"控件 {n['displayName']} 超出画布边界 ({canvas_w}x{canvas_h}): {'; '.join(overflow_parts)}",
                    controls=[n["displayName"]],
                ))

    return issues


def _compute_overlap_ratio(n1: dict, n2: dict) -> float:
    w1 = (n1.get("width") or 0) or 60
    h1 = (n1.get("height") or 0) or 40
    w2 = (n2.get("width") or 0) or 60
    h2 = (n2.get("height") or 0) or 40

    x1_min = n1.get("x", 0) - w1 / 2
    x1_max = n1.get("x", 0) + w1 / 2
    y1_min = n1.get("y", 0) - h1 / 2
    y1_max = n1.get("y", 0) + h1 / 2
    x2_min = n2.get("x", 0) - w2 / 2
    x2_max = n2.get("x", 0) + w2 / 2
    y2_min = n2.get("y", 0) - h2 / 2
    y2_max = n2.get("y", 0) + h2 / 2

    overlap_w = max(0, min(x1_max, x2_max) - max(x1_min, x2_min))
    overlap_h = max(0, min(y1_max, y2_max) - max(y1_min, y2_min))
    overlap_area = overlap_w * overlap_h
    area1 = w1 * h1
    area2 = w2 * h2
    smaller = min(area1, area2)
    if smaller == 0:
        return 0.0
    return overlap_area / smaller


async def _schema_validate(json_data: dict) -> list[str]:
    schema_text = await asyncio.to_thread(
        lambda: _SCHEMA_PATH.read_text(encoding="utf-8")
    )
    schema = json.loads(schema_text)
    try:
        jsonschema.validate(instance=json_data, schema=schema)
        return []
    except jsonschema.ValidationError as e:
        return [str(e.message)]


def _select_top_controls(rows: list[dict], keyword: str, count: int) -> list[dict]:
    best_by_name: dict[str, dict] = {}
    for row in rows:
        name = row.get("displayName")
        if not name:
            continue
        current = best_by_name.get(name)
        if current is None or row.get("similarity", 0.0) > current.get("similarity", 0.0):
            best_by_name[name] = row

    candidates = list(best_by_name.values())
    candidates.sort(
        key=lambda row: (
            0 if row.get("displayName") == keyword else 1,
            -float(row.get("similarity", 0.0)),
            row.get("displayName", ""),
        )
    )
    if not candidates:
        return []

    best = candidates[0]
    selected: list[dict] = []
    for idx in range(count):
        clone = dict(best)
        clone["_instance_index"] = idx + 1
        selected.append(clone)
    return selected


def _dedupe_controls(controls: list[dict]) -> list[dict]:
    result: list[dict] = []
    seen: set = set()
    for ctrl in controls:
        name = ctrl.get("displayName")
        instance = ctrl.get("_instance_index")
        key = (name, instance) if instance else name
        if not name or key in seen:
            continue
        seen.add(key)
        result.append(ctrl)
    return result


async def _extract_control_names_from_query(query: str, material_db) -> tuple[list[dict], list[str]]:
    all_qr = await material_db.list_query_results("")
    available_names = sorted({r["displayName"] for r in all_qr if r.get("displayName")})
    if not available_names:
        return [], []
    controls_list = "\n".join(f"- {name}" for name in available_names)
    prompt = EXTRACT_CONTROLS_PROMPT.format(controls_list=controls_list)
    if not _MODEL:
        raise RuntimeError("未配置 DEEPSEEK_MODEL")
    response = await _client.chat.completions.create(
        model=_MODEL,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": query},
        ],
        stream=False,
        reasoning_effort="low",
        response_format={"type": "json_object"},
        extra_body={"thinking": {"type": "enabled"}},
    )
    content = response.choices[0].message.content
    data = json.loads(content) if content else []
    if isinstance(data, dict):
        data = data.get("controls", data.get("items", []))
    if not isinstance(data, list):
        return [], []
    name_set = set(available_names)
    specs: list[dict] = []
    missing_names: list[str] = []
    for item in data:
        name = item.get("name", "")
        if name in name_set:
            specs.append({"name": name, "count": max(1, int(item.get("count", 1)))})
        else:
            missing_names.append(name)
    return specs, missing_names


async def _load_controls_from_query_results(query: str, material_db) -> tuple[list[dict], list[str], list[str]]:
    specs: list[dict] | None = None
    missing_names: list[str] = []
    try:
        specs, missing_names = await _extract_control_names_from_query(query, material_db)
    except Exception as exc:
        logger.warning("LLM 控件提取失败，使用本地名称匹配: %s", exc)

    if not specs:
        all_qr = await material_db.list_query_results("")
        qr_names = list({r["displayName"] for r in all_qr if r.get("displayName")})
        specs = []
        for name in sorted(qr_names, key=len, reverse=True):
            if name in query:
                specs.append({"name": name, "count": 1})

    if not specs:
        return [], [], missing_names

    matched: list[dict] = []
    matched_keywords: list[str] = []
    for spec in specs:
        rows = await material_db.search_query_results_by_name(spec["name"])
        if rows:
            matched.extend(_select_top_controls(rows, spec["name"], spec.get("count", 1)))
            matched_keywords.append(spec["name"])
        else:
            if spec["name"] not in missing_names:
                missing_names.append(spec["name"])

    return matched, matched_keywords, missing_names


class CanvasAgent:
    def __init__(self, db: Optional[MaterialDB] = None):
        self._db = db

    async def layout(
        self,
        query: str,
        controls: Optional[list[dict]] = None,
        canvas_width: int = 800,
        canvas_height: int = 800,
    ) -> CanvasResult:
        missing_controls: list[str] = []
        if controls is None:
            if self._db is None:
                raise ValueError("controls 未提供且 CanvasAgent 未注入 material_db")
            controls, _, missing_controls = await _load_controls_from_query_results(query, self._db)
        controls = _dedupe_controls(controls)
        logger.info("自动布局流程")
        logger.info("━" * 40)
        logger.info("📐 画布尺寸: %dx%d", canvas_width, canvas_height)
        logger.info("📦 控件数量: %d", len(controls))

        logger.info("━" * 40)
        logger.info("🔍 Step0.5: 提取用户意图 hints")
        step1_hints = await _extract_hints_only(query, controls)
        logger.info("  hints: %s", [(h.target, h.region) for h in step1_hints])

        logger.info("━" * 40)
        logger.info("🕸 Step0.6: 生成 Mermaid 控制流图")
        flow_dsl = await _generate_flow_dsl(query, controls, step1_hints, canvas_width, canvas_height)
        flow_graph: FlowGraph | None = None
        region_map: dict[str, str] = {}

        if flow_dsl:
            logger.info("  DSL:\n%s", flow_dsl)
            try:
                flow_graph = _parse_flow_dsl(flow_dsl, controls)
                if flow_graph and flow_graph.nodes:
                    region_map = _graph_to_region_map(flow_graph, step1_hints)
                    logger.info("  DSL 解析成功: direction=%s, nodes=%d, edges=%d",
                                flow_graph.direction, len(flow_graph.nodes), len(flow_graph.edges))
                else:
                    logger.warning("  DSL 解析结果为空，降级到传统流程")
                    flow_graph = None
            except Exception as exc:
                logger.warning("  DSL 解析失败: %s，降级到传统流程", exc)
                flow_graph = None
        else:
            logger.warning("  DSL 生成失败，降级到传统流程")

        if flow_graph is None:
            logger.info("━" * 40)
            logger.info("🔍 Step1(Fallback): 提取布局需求")
            requirement = await _extract_layout_requirements(query, controls, canvas_width, canvas_height)
            region_map = {p.target: p.region for p in requirement.placements}
            for h in requirement.placement_hints:
                region_map[h.target] = h.region
            logger.info("  分区配置: %s", [(k, v) for k, v in region_map.items()])
        else:
            requirement = LayoutRequirement(
                canvas_width=canvas_width,
                canvas_height=canvas_height,
                controls=controls,
                placements=[],
                placement_hints=step1_hints,
            )
            logger.info("  分区配置(DSL): %s", [(k, v) for k, v in region_map.items()])

        logger.info("━" * 40)
        logger.info("🦴 Step2: 生成布局骨架")
        skeleton = _generate_skeleton(requirement, region_map)
        for z in skeleton.zones:
            logger.info("  %s: %d个控件 %s", z.name, len(z.controls), z.controls)

        logger.info("━" * 40)
        logger.info("📍 Step3: 计算坐标")
        nodes = _compute_coordinates(skeleton, controls, canvas_width, canvas_height)

        total = len(controls)
        if total > 20:
            logger.info("  元素数量>%d，使用力导向布局+LLM微调", 20)
            nodes = await _refine_layout_with_llm(nodes, canvas_width, canvas_height)

        nodes = _scale_to_canvas(nodes, canvas_width, canvas_height)

        for n in nodes:
            logger.info("  %s → (%d, %d)", n["displayName"], n["x"], n["y"])

        logger.info("━" * 40)
        logger.info("🔍 Step4: 质量检测")
        issues = _quality_check(nodes, canvas_width, canvas_height)
        for issue in issues:
            logger.info("  [%s] %s: %s", issue.severity, issue.issue_type, issue.message)

        logger.info("━" * 40)
        logger.info("✅ Step5: 组装JSON & Schema校验")
        d_nodes = []
        for idx, n in enumerate(nodes):
            node_dict: dict = {
                "c": "ht.Node",
                "i": 17092 + idx,
            }
            p: dict = {
                "displayName": n["displayName"],
                "image": n.get("image", ""),
                "position": {"x": n["x"], "y": n["y"]},
            }
            if n.get("width") and n.get("height"):
                p["width"] = n["width"]
                p["height"] = n["height"]
            node_dict["p"] = p
            d_nodes.append(node_dict)

        content_rect = _calc_content_rect(nodes)

        json_data = {
            "v": "8.0.5",
            "p": {
                "layers": [{"name": "0", "visible": True, "selectable": True, "movable": True, "editable": True}],
                "autoAdjustIndex": True,
                "hierarchicalRendering": True,
            },
            "a": {
                "width": canvas_width,
                "height": canvas_height,
                "fitContent": True,
                "rectSelectable": False,
                "zoomable": False,
                "pannable": False,
            },
            "d": d_nodes,
            "contentRect": content_rect,
        }

        errors = await _schema_validate(json_data)
        if errors:
            logger.warning("  Schema校验问题: %s", errors)
            issues.extend(
                QualityIssue(
                    severity="error",
                    issue_type="schema",
                    message=error,
                    controls=[],
                )
                for error in errors
            )
        else:
            logger.info("  Schema校验通过 ✓")

        return CanvasResult(
            json_data=json_data,
            content_rect=json_data["contentRect"],
            quality_issues=issues,
            skeleton=skeleton,
            missing_controls=missing_controls,
        )


def _cli() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )

    query = input("查询描述: ").strip()
    if not query:
        print("查询描述不能为空", file=sys.stderr)
        sys.exit(1)

    w_str = input("画布宽度 (默认 800): ").strip()
    h_str = input("画布高度 (默认 800): ").strip()
    canvas_w = int(w_str) if w_str else 800
    canvas_h = int(h_str) if h_str else 800

    async def run() -> CanvasResult:
        db = MaterialDB()
        await db.init_db()
        agent = CanvasAgent(db=db)
        return await agent.layout(query=query, canvas_width=canvas_w, canvas_height=canvas_h)

    result = asyncio.run(run())
    output_path = Path(__file__).resolve().parent.parent / "output" / "canvas.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result.json_data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("已保存到 %s", output_path)
    logger.info("控件数: %d, 质量问题: %d", len(result.json_data.get("d", [])), len(result.quality_issues))


if __name__ == "__main__":
    _cli()
