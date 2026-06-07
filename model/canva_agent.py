import sys
import warnings
warnings.simplefilter("ignore")
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import json
import logging
import math
import os
import random
import re
from dataclasses import dataclass
from pathlib import Path
import jsonschema
from dotenv import load_dotenv
from openai import OpenAI
logger = logging.getLogger(__name__)
load_dotenv(".env.local")
_client = OpenAI(
    api_key=os.environ.get("DEEPSEEK_API_KEY"),
    base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
)
_MODEL = os.environ.get("DEEPSEEK_MODEL")
_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "data" / "canvas_schema.json"


EXTRACT_PROMPT = """\
SCADA 组态语义分析器。根据用户描述，从给定控件列表中识别控件、连接关系和布局意图。

可用控件列表：
{controls_info}

要求：
1. 只能使用控件列表中的 displayName,不得编造名称。
2. main_devices:主设备/核心被控对象。
3. auxiliary_controls:控制类控件，如按钮、开关、启停、急停、控制器。
4. display_controls:显示类控件，如仪表、参数值、指示灯、图表、趋势图。
5. connections 表示控制或显示关系：
   - 控制类控件 -> 主设备,relation="控制"
   - 显示类控件 -> 主设备,relation="显示"
6. placement_hints 表示明确的布局意图，只能使用这些 region 枚举：
   - left, right, top, bottom, center
   - left_top, right_top, left_bottom, right_bottom
7. 只有当用户明确表达了位置意图时才输出 placement_hints。
8. 不确定的连接不要输出。

只输出 JSON,不要解释:
{{
  "main_devices": [],
  "auxiliary_controls": [],
  "display_controls": [],
  "connections": [
    {{"from": "", "to": "", "relation": "控制"}}
  ],
  "placement_hints": [
    {{"target": "", "region": "left"}}
  ]
}}
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
5. 控制类控件靠右上，显示类控件靠右下，主设备靠左中。
6. x、y 必须是整数。

只输出 JSON,不要解释:
{{"nodes":[{{"displayName":"","image":"","width":0,"height":0,"x":0,"y":0}}]}}
"""


CONTROL_KEYWORDS = {"按钮", "开关", "控制", "启动", "急停", "下行控制"}
DISPLAY_KEYWORDS = {"参数值", "仪表", "指示灯", "图表", "图", "表"}
LARGE_DEVICE_SIZE = 200
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
COUNT_PATTERN = re.compile(r"([0-9]+)\s*个?")
CN_NUM_MAP = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


@dataclass
class PlacementHint:
    target: str
    region: str


@dataclass
class QueryIntent:
    keyword: str
    count: int


@dataclass
class LayoutRequirement:
    canvas_width: int
    canvas_height: int
    controls: list[dict]
    main_devices: list[str]
    auxiliary_controls: list[str]
    display_controls: list[str]
    connections: list[dict]
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
    connections: list[dict]


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


def _classify_controls(controls: list[dict]) -> dict[str, list[str]]:
    auxiliary = []
    display = []
    main_devices = []
    for ctrl in controls:
        name = ctrl.get("displayName", "")
        w = ctrl.get("width") or 0
        h = ctrl.get("height") or 0
        is_aux = any(kw in name for kw in CONTROL_KEYWORDS)
        is_disp = any(kw in name for kw in DISPLAY_KEYWORDS)
        if is_aux:
            auxiliary.append(name)
        elif is_disp:
            display.append(name)
        elif w >= LARGE_DEVICE_SIZE or h >= LARGE_DEVICE_SIZE:
            main_devices.append(name)
    return {"main_devices": main_devices, "auxiliary": auxiliary, "display": display}


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
    heuristic: dict[str, list[str]],
    controls: list[dict],
    canvas_w: int,
    canvas_h: int,
) -> LayoutRequirement:
    all_names = {c["displayName"] for c in controls}

    llm_main = data.get("main_devices", [])
    llm_aux = data.get("auxiliary_controls", [])
    llm_disp = data.get("display_controls", [])

    main_devices = [n for n in llm_main if n in all_names] or heuristic["main_devices"]
    auxiliary = [n for n in llm_aux if n in all_names] or heuristic["auxiliary"]
    display = [n for n in llm_disp if n in all_names] or heuristic["display"]

    assigned = set(main_devices + auxiliary + display)
    for ctrl in controls:
        name = ctrl["displayName"]
        if name in assigned:
            continue
        w = ctrl.get("width") or 0
        h = ctrl.get("height") or 0
        if w >= LARGE_DEVICE_SIZE or h >= LARGE_DEVICE_SIZE:
            main_devices.append(name)
        elif any(kw in name for kw in CONTROL_KEYWORDS):
            auxiliary.append(name)
        elif any(kw in name for kw in DISPLAY_KEYWORDS):
            display.append(name)
        else:
            auxiliary.append(name)
        assigned.add(name)

    connections = _sanitize_connections(data.get("connections", []), controls)
    placement_hints = _sanitize_placement_hints(data.get("placement_hints", []), controls)
    if not placement_hints:
        placement_hints = _extract_placement_hints_from_query(data.get("_source_query", ""), controls)
    return LayoutRequirement(
        canvas_width=canvas_w,
        canvas_height=canvas_h,
        controls=controls,
        main_devices=main_devices,
        auxiliary_controls=auxiliary,
        display_controls=display,
        connections=connections,
        placement_hints=placement_hints,
    )


def _sanitize_connections(connections: list[dict], controls: list[dict]) -> list[dict]:
    all_names = {c["displayName"] for c in controls}
    clean: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for conn in connections:
        from_name = conn.get("from")
        to_name = conn.get("to")
        if from_name not in all_names or to_name not in all_names or from_name == to_name:
            continue
        relation = conn.get("relation") or "关联"
        item = (from_name, to_name, relation)
        if item in seen:
            continue
        seen.add(item)
        clean.append({"from": from_name, "to": to_name, "relation": relation})
    return clean


def _extract_layout_requirements(
    query: str, controls: list[dict], canvas_w: int, canvas_h: int
) -> LayoutRequirement:
    heuristic = _classify_controls(controls)
    controls_info = "\n".join(
        f"- {c['displayName']} (宽{c.get('width',0)}x高{c.get('height',0)})"
        for c in controls
    )
    prompt = EXTRACT_PROMPT.format(controls_info=controls_info)
    data: dict = {}
    if not _MODEL:
        logger.warning("未配置 DEEPSEEK_MODEL，使用本地启发式布局分类")
    else:
        try:
            response = _client.chat.completions.create(
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
            logger.warning("布局需求抽取失败，使用本地启发式分类: %s", exc)
    data["_source_query"] = query

    return _build_requirement_from_data(data, heuristic, controls, canvas_w, canvas_h)


def _generate_skeleton(requirement: LayoutRequirement) -> LayoutSkeleton:
    zones = _apply_layout_constraints(requirement)
    return LayoutSkeleton(zones=zones, connections=requirement.connections)


def _default_zone_for_control(
    name: str,
    main_devices: set[str],
    auxiliary_controls: set[str],
    display_controls: set[str],
) -> str:
    if name in main_devices:
        return "device_zone"
    if name in display_controls:
        return "display_zone"
    if name in auxiliary_controls:
        return "control_zone"
    return "control_zone"


def _zone_for_region(region: str, default_zone: str) -> str:
    if region in {"left", "left_top", "left_bottom"}:
        return "device_zone"
    if region in {"right", "right_top"}:
        return "control_zone" if default_zone == "control_zone" else "display_zone"
    if region == "right_bottom":
        return "display_zone"
    if region in {"top", "center", "bottom"}:
        return default_zone
    return default_zone


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


def _apply_layout_constraints(requirement: LayoutRequirement) -> list[LayoutZone]:
    cw = requirement.canvas_width
    ch = requirement.canvas_height
    ctrl_map = {c["displayName"]: c for c in requirement.controls}
    main_set = set(requirement.main_devices)
    aux_set = set(requirement.auxiliary_controls)
    disp_set = set(requirement.display_controls)
    hint_map = {hint.target: hint.region for hint in requirement.placement_hints}

    zone_assignments = {
        "device_zone": [],
        "control_zone": [],
        "display_zone": [],
    }
    for ctrl in requirement.controls:
        name = ctrl["displayName"]
        default_zone = _default_zone_for_control(name, main_set, aux_set, disp_set)
        zone_name = _zone_for_region(hint_map.get(name, ""), default_zone)
        zone_assignments[zone_name].append(name)

    device_controls = _sort_controls_for_region(zone_assignments["device_zone"], hint_map)
    aux_controls = _sort_controls_for_region(zone_assignments["control_zone"], hint_map)
    disp_controls = _sort_controls_for_region(zone_assignments["display_zone"], hint_map)

    gap = 40

    device_ctrls = [ctrl_map[n] for n in device_controls if n in ctrl_map]
    aux_ctrls = [ctrl_map[n] for n in aux_controls if n in ctrl_map]
    disp_ctrls = [ctrl_map[n] for n in disp_controls if n in ctrl_map]

    device_padding = 30
    device_total_h = sum(c.get("height") or 0 for c in device_ctrls) + device_padding * (len(device_ctrls) - 1) if device_ctrls else 0
    device_max_w = max((c.get("width") or 0 for c in device_ctrls), default=0)

    aux_padding = 20
    aux_total_h = sum(c.get("height") or 0 for c in aux_ctrls) + aux_padding * (len(aux_ctrls) - 1) if aux_ctrls else 0
    aux_max_w = max((c.get("width") or 0 for c in aux_ctrls), default=0)

    disp_padding = 20
    disp_total_h = sum(c.get("height") or 0 for c in disp_ctrls) + disp_padding * (len(disp_ctrls) - 1) if disp_ctrls else 0
    disp_max_w = max((c.get("width") or 0 for c in disp_ctrls), default=0)

    device_zone_w = max(cw * 0.40, device_max_w + gap * 2)
    device_zone_h = max(ch * 0.50, device_total_h + gap * 2)
    device_zone = LayoutZone(
        name="device_zone",
        x=round(gap),
        y=round(max(gap, (ch - device_zone_h) / 2)),
        width=round(device_zone_w),
        height=round(device_zone_h),
        controls=device_controls,
    )

    right_x = round(device_zone.x + device_zone.width + gap)
    right_w = max(cw * 0.22, max(aux_max_w, disp_max_w) + gap * 2)
    if right_x + right_w > cw - gap:
        right_w = cw - gap - right_x

    control_zone_h = max(ch * 0.35, aux_total_h + gap * 2)
    control_zone = LayoutZone(
        name="control_zone",
        x=right_x,
        y=round(gap),
        width=round(right_w),
        height=round(control_zone_h),
        controls=aux_controls,
    )

    display_zone_y = round(control_zone.y + control_zone.height + gap)
    display_zone_h = max(ch * 0.35, disp_total_h + gap * 2)
    if display_zone_y + display_zone_h > ch - gap:
        display_zone_h = ch - gap - display_zone_y
    if display_zone_h < gap * 2:
        display_zone_h = gap * 2
    display_zone = LayoutZone(
        name="display_zone",
        x=right_x,
        y=display_zone_y,
        width=round(right_w),
        height=round(display_zone_h),
        controls=disp_controls,
    )

    return [device_zone, control_zone, display_zone]


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
        "device_zone": 30,
        "control_zone": 20,
        "display_zone": 20,
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

        cursor_y = zone.y + padding
        for ctrl in zone_ctrls:
            cx = zone.x + padding + (ctrl.get("width") or 0) / 2
            cy = cursor_y + (ctrl.get("height") or 0) / 2
            nodes.append({
                "displayName": ctrl["displayName"],
                "image": ctrl.get("image", ""),
                "width": ctrl.get("width", 0),
                "height": ctrl.get("height", 0),
                "x": round(cx),
                "y": round(cy),
            })
            cursor_y += (ctrl.get("height") or 0) + padding

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

    conn_pairs: set[tuple[str, str]] = set()
    for conn in skeleton.connections:
        f = conn.get("from", "")
        t = conn.get("to", "")
        if f and t:
            conn_pairs.add((f, t))

    repulsion_k = 5000.0
    spring_k = 0.01
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

        for (f_name, t_name) in conn_pairs:
            if f_name not in positions or t_name not in positions:
                continue
            dx = positions[t_name][0] - positions[f_name][0]
            dy = positions[t_name][1] - positions[f_name][1]
            dist = math.sqrt(dx * dx + dy * dy) + 1e-6
            fx = spring_k * dx
            fy = spring_k * dy
            forces[f_name][0] += fx
            forces[f_name][1] += fy
            forces[t_name][0] -= fx
            forces[t_name][1] -= fy

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


def _refine_layout_with_llm(
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
        response = _client.chat.completions.create(
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


def _quality_check(nodes: list[dict], connections: list[dict], canvas_w: int = 0, canvas_h: int = 0) -> list[QualityIssue]:
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

    display_names_lower = {n["displayName"].lower() for n in nodes if any(
        kw in n["displayName"] for kw in DISPLAY_KEYWORDS
    )}
    conn_names = set()
    for conn in connections:
        f = conn.get("from", "")
        t = conn.get("to", "")
        conn_names.add(f)
        conn_names.add(t)

    for n in nodes:
        name = n["displayName"]
        if name.lower() in display_names_lower:
            continue
        if name not in conn_names:
            issues.append(QualityIssue(
                severity="warning",
                issue_type="isolated",
                message=f"控件 {name} 无连接关系且非显示类，可能是孤立控件",
                controls=[name],
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


def _schema_validate(json_data: dict) -> list[str]:
    schema_text = _SCHEMA_PATH.read_text(encoding="utf-8")
    schema = json.loads(schema_text)
    try:
        jsonschema.validate(instance=json_data, schema=schema)
        return []
    except jsonschema.ValidationError as e:
        return [str(e.message)]


def _longest_common_substring(a: str, b: str) -> str:
    if not a or not b:
        return ""

    prev = [0] * (len(b) + 1)
    best_len = 0
    best_end = 0
    for i, char_a in enumerate(a, start=1):
        curr = [0] * (len(b) + 1)
        for j, char_b in enumerate(b, start=1):
            if char_a == char_b:
                curr[j] = prev[j - 1] + 1
                if curr[j] > best_len:
                    best_len = curr[j]
                    best_end = i
        prev = curr
    return a[best_end - best_len:best_end]


def _parse_count_from_text(text: str) -> int:
    match = COUNT_PATTERN.search(text)
    if match:
        return max(1, int(match.group(1)))
    for token in sorted(CN_NUM_MAP, key=len, reverse=True):
        pos = text.find(token)
        if pos >= 0 and "个" in text[pos:pos + 2]:
            return CN_NUM_MAP[token]
    return 1


def _extract_query_intents(query: str, material_db) -> list[QueryIntent]:
    intents: list[QueryIntent] = []

    def add_intent(keyword: str, count: int = 1) -> None:
        keyword = keyword.strip()
        if len(keyword) < 2:
            return
        for intent in intents:
            if intent.keyword == keyword:
                intent.count = max(intent.count, count)
                return
        for existing in [intent.keyword for intent in intents]:
            if keyword in existing:
                return
        intents[:] = [intent for intent in intents if intent.keyword not in keyword]
        intents.append(QueryIntent(keyword=keyword, count=max(1, count)))

    controls = material_db.list_all()
    names = sorted(
        (row["displayName"] for row in controls if row.get("displayName")),
        key=len,
        reverse=True,
    )
    for name in names:
        if name in query:
            idx = query.find(name)
            window_start = max(0, idx - 6)
            count = _parse_count_from_text(query[window_start:idx])
            add_intent(name, count)
            continue
        common = _longest_common_substring(query, name)
        if len(common) >= 3 or common in CONTROL_KEYWORDS or common in DISPLAY_KEYWORDS:
            add_intent(common)

    for keyword in sorted(CONTROL_KEYWORDS | DISPLAY_KEYWORDS, key=len, reverse=True):
        if keyword not in query:
            continue
        idx = query.find(keyword)
        window_start = max(0, idx - 6)
        count = _parse_count_from_text(query[window_start:idx])
        add_intent(keyword, count)

    return intents


def _extract_query_keywords(query: str, material_db) -> list[str]:
    return [intent.keyword for intent in _extract_query_intents(query, material_db)]


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
    seen: set[str] = set()
    for ctrl in controls:
        name = ctrl.get("displayName")
        if not name or name in seen:
            continue
        seen.add(name)
        result.append(ctrl)
    return result


def _load_controls_from_query_results(query: str, material_db) -> tuple[list[dict], list[str]]:
    controls = material_db.list_query_results(query)
    if controls:
        return controls, []

    controls = material_db.search_query_results_by_name(query)
    if controls:
        return _select_top_controls(controls, query, 1), [query]

    intents = _extract_query_intents(query, material_db)
    matched: list[dict] = []
    matched_keywords: list[str] = []
    for intent in intents:
        rows = material_db.search_query_results_by_name(intent.keyword)
        if not rows:
            continue
        matched.extend(_select_top_controls(rows, intent.keyword, intent.count))
        matched_keywords.append(f"{intent.keyword}x{intent.count}")

    return matched, matched_keywords


class CanvasAgent:
    def layout(
        self,
        query: str,
        controls: list[dict],
        canvas_width: int = 800,
        canvas_height: int = 800,
    ) -> CanvasResult:
        logger.info("自动布局流程")
        logger.info("━" * 40)
        logger.info("📐 画布尺寸: %dx%d", canvas_width, canvas_height)
        logger.info("📦 控件数量: %d", len(controls))

        logger.info("━" * 40)
        logger.info("🔍 Step1: 提取布局需求")
        requirement = _extract_layout_requirements(query, controls, canvas_width, canvas_height)
        logger.info("  主设备: %s", requirement.main_devices)
        logger.info("  控制类: %s", requirement.auxiliary_controls)
        logger.info("  显示类: %s", requirement.display_controls)
        logger.info("  连接数: %d", len(requirement.connections))

        logger.info("━" * 40)
        logger.info("🦴 Step2: 生成布局骨架")
        skeleton = _generate_skeleton(requirement)
        for z in skeleton.zones:
            logger.info("  %s: %d个控件 %s", z.name, len(z.controls), z.controls)

        logger.info("━" * 40)
        logger.info("📍 Step3: 计算坐标")
        nodes = _compute_coordinates(skeleton, controls, canvas_width, canvas_height)

        total = len(controls)
        if total > 20:
            logger.info("  元素数量>%d，使用力导向布局+LLM微调", 20)
            nodes = _refine_layout_with_llm(nodes, canvas_width, canvas_height)

        nodes = _scale_to_canvas(nodes, canvas_width, canvas_height)

        for n in nodes:
            logger.info("  %s → (%d, %d)", n["displayName"], n["x"], n["y"])

        logger.info("━" * 40)
        logger.info("🔍 Step4: 质量检测")
        issues = _quality_check(nodes, skeleton.connections, canvas_width, canvas_height)
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

        errors = _schema_validate(json_data)
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
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    from data.material_db import MaterialDB

    db = MaterialDB()
    db.init_db()
    agent = CanvasAgent()

    while True:
        try:
            query = input("\n布局 (q退出): ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not query or query.lower() == "q":
            break

        controls, matched_keywords = _load_controls_from_query_results(query, db)
        if not controls:
            keywords = _extract_query_keywords(query, db)
            if keywords:
                print(
                    f"已从输入中提取关键词 {keywords}，但 query_results 表中没有匹配控件；"
                    "请先在控件检索页保存这些控件结果"
                )
            else:
                print(f"未能从查询 '{query}' 中提取可用于 query_results 的控件关键词")
            continue
        if matched_keywords:
            print(f"按关键词从 query_results 命中: {', '.join(matched_keywords)}")

        try:
            w_input = input("画布宽度 (默认800): ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        canvas_w = int(w_input) if w_input else 800

        try:
            h_input = input("画布高度 (默认800): ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        canvas_h = int(h_input) if h_input else 800

        result = agent.layout(
            query=query, controls=controls,
            canvas_width=canvas_w, canvas_height=canvas_h,
        )

        output_dir = Path(__file__).resolve().parent.parent / "output"
        output_dir.mkdir(exist_ok=True)
        output_path = output_dir / "canvas.json"
        output_path.write_text(
            json.dumps(result.json_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n已保存到 {output_path}")
        print(f"质量检测: {len(result.quality_issues)} 个问题")
        for issue in result.quality_issues:
            print(f"  [{issue.severity}] {issue.issue_type}: {issue.message}")
