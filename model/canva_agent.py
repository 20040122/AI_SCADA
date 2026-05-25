import sys
import warnings
warnings.simplefilter("ignore")
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
import logging
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

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
你是工业SCADA组态布局分析专家。根据用户描述和控件列表，提取布局需求。

## 可用控件列表
{controls_info}

## 提取要求
1. 识别用户描述中的主设备（核心被控对象，如"高低温试验箱"、"水泵"等）
2. 将控件分为三类：
   - main_devices: 主设备，是组态画面的核心对象
   - auxiliary_controls: 控制类控件（按钮、开关、启停控制等）
   - display_controls: 显示/仪表类控件（参数值、指示灯、图表等）
3. 提取控件间的连接关系（哪个控制件控制哪个设备，哪个显示件显示哪个设备的状态）
4. 控件的displayName必须严格来自上方控件列表，不可编造

## 输出JSON格式
{{
  "main_devices": ["displayName1", ...],
  "auxiliary_controls": ["displayName1", ...],
  "display_controls": ["displayName1", ...],
  "connections": [
    {{"from": "控件displayName", "to": "设备displayName", "relation": "控制|显示"}}
  ]
}}
"""

SKELETON_PROMPT = """\
你是工业SCADA组态布局规划专家。根据布局需求，为每个控件分配区域和初步位置。

## 画布尺寸
宽: {canvas_width}px, 高: {canvas_height}px

## 布局需求
{requirement_json}

## 区域规划规则
1. 设备区(device_zone)：位于画布左中区域
   - 起始坐标约 (canvas_w*0.30, canvas_h*0.45)
   - 主设备纵向排列，间距按设备高度自适应
2. 控制面板区(control_zone)：位于画布右侧
   - 起始坐标约 (canvas_w*0.72, canvas_h*0.15)
   - 控制类控件纵向排列，间距约60px
3. 显示区(display_zone)：位于画布右下方
   - 起始坐标约 (canvas_w*0.72, canvas_h*0.55)
   - 显示类控件纵向排列，间距约60px

## 分配要求
1. 每个控件必须且只能分配到一个区域
2. 主设备必须分配到device_zone
3. 控制类控件必须分配到control_zone
4. 显示类控件必须分配到display_zone
5. 同类控件在同一区域内纵向排列

## 输出JSON格式
{{
  "zones": [
    {{
      "name": "device_zone",
      "controls": ["displayName1", ...],
      "x": 数字,
      "y": 数字,
      "width": 数字,
      "height": 数字
    }},
    {{
      "name": "control_zone",
      "controls": ["displayName1", ...],
      "x": 数字,
      "y": 数字,
      "width": 数字,
      "height": 数字
    }},
    {{
      "name": "display_zone",
      "controls": ["displayName1", ...],
      "x": 数字,
      "y": 数字,
      "width": 数字,
      "height": 数字
    }}
  ],
  "connections": [
    {{"from": "控件displayName", "to": "设备displayName"}}
  ]
}}
"""

REFINE_PROMPT = """\
你是工业SCADA组态布局微调专家。以下是力导向算法生成的初始布局，请微调使其更合理。

## 画布尺寸
宽: {canvas_width}px, 高: {canvas_height}px

## 初始布局（JSON）
{layout_json}

## 微调规则
1. 确保同类控件聚合，同类控件之间距离应小于200px
2. 控制类控件放在右侧区域
3. 显示/仪表类控件放在右侧偏下区域
4. 主设备放在左中区域
5. 避免控件重叠
6. 坐标精度不超过1px（取整）

## 输出格式
只输出与输入相同结构的JSON，不要输出任何解释。
"""


CONTROL_KEYWORDS = {"按钮", "开关", "控制", "启动", "急停", "下行控制"}
DISPLAY_KEYWORDS = {"参数值", "仪表", "指示灯", "图表", "图", "表"}
LARGE_DEVICE_SIZE = 200


@dataclass
class LayoutRequirement:
    canvas_width: int
    canvas_height: int
    controls: list[dict]
    main_devices: list[str]
    auxiliary_controls: list[str]
    display_controls: list[str]
    connections: list[dict]


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


def _extract_layout_requirements(
    query: str, controls: list[dict], canvas_w: int, canvas_h: int
) -> LayoutRequirement:
    heuristic = _classify_controls(controls)
    controls_info = "\n".join(
        f"- {c['displayName']} (宽{c.get('width',0)}x高{c.get('height',0)})"
        for c in controls
    )
    prompt = EXTRACT_PROMPT.format(controls_info=controls_info)
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

    llm_main = data.get("main_devices", [])
    llm_aux = data.get("auxiliary_controls", [])
    llm_disp = data.get("display_controls", [])
    llm_conn = data.get("connections", [])

    all_names = {c["displayName"] for c in controls}
    main_devices = [n for n in llm_main if n in all_names] or heuristic["main_devices"]
    auxiliary = [n for n in llm_aux if n in all_names] or heuristic["auxiliary"]
    display = [n for n in llm_disp if n in all_names] or heuristic["display"]

    assigned = set(main_devices + auxiliary + display)
    for ctrl in controls:
        name = ctrl["displayName"]
        if name not in assigned:
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

    return LayoutRequirement(
        canvas_width=canvas_w,
        canvas_height=canvas_h,
        controls=controls,
        main_devices=main_devices,
        auxiliary_controls=auxiliary,
        display_controls=display,
        connections=llm_conn,
    )


def _generate_skeleton(requirement: LayoutRequirement) -> LayoutSkeleton:
    req_dict = {
        "canvas_width": requirement.canvas_width,
        "canvas_height": requirement.canvas_height,
        "main_devices": requirement.main_devices,
        "auxiliary_controls": requirement.auxiliary_controls,
        "display_controls": requirement.display_controls,
        "controls_detail": [
            {
                "displayName": c["displayName"],
                "width": c.get("width", 0),
                "height": c.get("height", 0),
            }
            for c in requirement.controls
        ],
    }
    prompt = SKELETON_PROMPT.format(
        canvas_width=requirement.canvas_width,
        canvas_height=requirement.canvas_height,
        requirement_json=json.dumps(req_dict, ensure_ascii=False),
    )
    response = _client.chat.completions.create(
        model=_MODEL,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": "请为以上控件分配区域并规划布局骨架。"},
        ],
        stream=False,
        reasoning_effort="low",
        response_format={"type": "json_object"},
        extra_body={"thinking": {"type": "enabled"}},
    )
    data = json.loads(response.choices[0].message.content)

    zones = []
    for z in data.get("zones", []):
        zones.append(LayoutZone(
            name=z["name"],
            x=z.get("x", 0),
            y=z.get("y", 0),
            width=z.get("width", 0),
            height=z.get("height", 0),
            controls=z.get("controls", []),
        ))

    standard_zones = _apply_layout_constraints(zones, requirement)
    return LayoutSkeleton(zones=standard_zones, connections=data.get("connections", []))


def _apply_layout_constraints(
    zones: list[LayoutZone], requirement: LayoutRequirement
) -> list[LayoutZone]:
    cw = requirement.canvas_width
    ch = requirement.canvas_height
    ctrl_map = {c["displayName"]: c for c in requirement.controls}

    device_controls = list(requirement.main_devices)
    aux_controls = list(requirement.auxiliary_controls)
    disp_controls = list(requirement.display_controls)

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
        if n.get("width"):
            n["width"] = round(n["width"] * scale, 1)
        if n.get("height"):
            n["height"] = round(n["height"] * scale, 1)
    return nodes


def _force_directed_layout(
    skeleton: LayoutSkeleton,
    controls: list[dict],
    canvas_w: int,
    canvas_h: int,
    iterations: int = 100,
) -> list[dict]:
    ctrl_map = {c["displayName"]: c for c in controls}
    all_names = [c["displayName"] for c in controls]

    positions: dict[str, list[float]] = {}
    zone_center: dict[str, list[float]] = {}
    for zone in skeleton.zones:
        zx = zone.x + zone.width / 2
        zy = zone.y + zone.height / 2
        zone_center[zone.name] = [zx, zy]
        for name in zone.controls:
            if name not in positions:
                import random
                positions[name] = [zx + random.uniform(-30, 30), zy + random.uniform(-30, 30)]

    for name in all_names:
        if name not in positions:
            import random
            positions[name] = [canvas_w / 2 + random.uniform(-50, 50), canvas_h / 2 + random.uniform(-50, 50)]

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
    layout_json = json.dumps(nodes, ensure_ascii=False, indent=2)
    prompt = REFINE_PROMPT.format(
        canvas_width=canvas_w,
        canvas_height=canvas_h,
        layout_json=layout_json,
    )
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
    if isinstance(data, list):
        return data
    return data.get("nodes", data.get("d", nodes))


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
                "fitContent": True,
                "zoomable": False,
                "pannable": False,
            },
            "d": d_nodes,
            "contentRect": content_rect,
        }

        errors = _schema_validate(json_data)
        if errors:
            logger.warning("  Schema校验问题: %s", errors)
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

        controls = db.list_query_results(query)
        if not controls:
            controls = db.search_query_results_by_name(query)
        if not controls:
            print(f"未找到与查询 '{query}' 匹配的控件，请先运行 control_agent.py 检索")
            continue

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