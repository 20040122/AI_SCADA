from __future__ import annotations

import argparse
import asyncio
import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from model.generate_gird import LayoutFile, LayoutGroup, validate_layout_file


@dataclass
class _Limits:
    min_w: float
    min_h: float
    max_w: float
    max_h: float
    preferred_w: float
    preferred_h: float


@dataclass
class _PlacedNode:
    group_id: str
    node_id: str
    instance_index: int
    device_type: str
    image: str
    x: float
    y: float
    width: float
    height: float


@dataclass
class _RoleEntry:
    keywords: list[str]
    limits: _Limits


@dataclass
class LayoutConfig:
    root_role_name: str
    roles: dict[str, _RoleEntry]


_DEFAULT_LAYOUT_CONFIG = LayoutConfig(
    root_role_name="root",
    roles={
        "root": _RoleEntry([], _Limits(120, 120, 180, 260, 160, 240)),
        "pipe": _RoleEntry(["管"], _Limits(80, 20, 180, 50, 120, 30)),
        "valve": _RoleEntry(["阀"], _Limits(40, 40, 80, 80, 60, 60)),
        "meter": _RoleEntry(["流量", "表"], _Limits(50, 50, 100, 100, 80, 80)),
        "sensor": _RoleEntry(["传感", "压力"], _Limits(50, 40, 110, 90, 80, 60)),
        "default": _RoleEntry([], _Limits(50, 40, 120, 120, 80, 80)),
    },
)

_LAYOUT_CONFIG: Optional[LayoutConfig] = None


def _load_layout_config() -> LayoutConfig:
    global _LAYOUT_CONFIG
    if _LAYOUT_CONFIG is not None:
        return _LAYOUT_CONFIG
    try:
        from app.config import settings

        path = Path(settings.layout_config_path)
    except Exception:
        _LAYOUT_CONFIG = _DEFAULT_LAYOUT_CONFIG
        return _LAYOUT_CONFIG
    if not path.is_file():
        _LAYOUT_CONFIG = _DEFAULT_LAYOUT_CONFIG
        return _LAYOUT_CONFIG
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        root_name = raw.get("root_role_name", "root")
        roles: dict[str, _RoleEntry] = {}
        for name, entry in raw.get("roles", {}).items():
            lim = entry.get("limits", {})
            roles[name] = _RoleEntry(
                list(entry.get("keywords", [])),
                _Limits(
                    lim.get("min_w", 50),
                    lim.get("min_h", 40),
                    lim.get("max_w", 120),
                    lim.get("max_h", 120),
                    lim.get("preferred_w", 80),
                    lim.get("preferred_h", 80),
                ),
            )
        for name, entry in _DEFAULT_LAYOUT_CONFIG.roles.items():
            roles.setdefault(name, entry)
        _LAYOUT_CONFIG = LayoutConfig(root_role_name=root_name, roles=roles)
    except (OSError, json.JSONDecodeError, TypeError):
        _LAYOUT_CONFIG = _DEFAULT_LAYOUT_CONFIG
    return _LAYOUT_CONFIG

_REGION_ORDER = ["left", "center", "right"]


class MissingMaterialError(ValueError):
    pass


def convert_layout_file(
    data: dict,
    controls: Optional[list[dict]] = None,
    width: int = 1920,
    height: int = 1080,
) -> list[dict]:
    layout_file = LayoutFile.model_validate(data)
    errors, _ = validate_layout_file(layout_file)
    if errors:
        message = "; ".join("%s: %s" % (e.path, e.message) for e in errors)
        raise ValueError(message)
    material_map = _material_map(controls or [])
    device_types = {
        node.deviceType
        for group in layout_file.layoutIntent.groups
        for node in [group.unit.root, *group.unit.attachments]
    }
    missing = sorted(device_type for device_type in device_types if not _find_material(device_type, material_map))
    if missing:
        raise MissingMaterialError("query_results 缺少控件素材：" + "、".join(missing))
    nodes = compute_nodes(layout_file, controls or [], width, height)
    return build_nodes(nodes)


def compute_nodes(
    layout_file: LayoutFile,
    controls: Optional[list[dict]] = None,
    width: int = 1920,
    height: int = 1080,
) -> list[dict]:
    material_map = _material_map(controls or [])
    content_rect = _content_rect(width, height)
    slots = compute_group_slots(
        layout_file.layoutIntent.groups,
        content_rect,
    )
    result = []
    for group in layout_file.layoutIntent.groups:
        group_slots = slots.get(group.id, [])
        for index, slot in enumerate(group_slots, start=1):
            result.extend(compute_unit_layout(group, slot, index, material_map))
    return result


def compute_group_slots(
    groups: list[LayoutGroup], content_rect: dict
) -> dict[str, list[dict]]:
    relations = _group_relations(groups)
    if relations:
        return _compute_related_group_slots(groups, content_rect, relations)
    region_gap = _outer_gap(content_rect["width"])
    regions = _region_rects(groups, content_rect, region_gap)
    result = {}
    for region in _REGION_ORDER:
        region_groups = [group for group in groups if group.region == region]
        if not region_groups:
            continue
        rect = regions[region]
        group_count = len(region_groups)
        gap = _fit_gap(rect["height"], group_count, _outer_gap(rect["height"]))
        group_h = (rect["height"] - gap * (group_count - 1)) / group_count
        for index, group in enumerate(region_groups):
            top = rect["y"] + index * (group_h + gap)
            group_rect = {
                "x": rect["x"],
                "y": top,
                "width": rect["width"],
                "height": group_h,
            }
            result[group.id] = _arrange_slots(group, group_rect)
    return result


def _compute_related_group_slots(
    groups: list[LayoutGroup], content_rect: dict, relations: dict[str, tuple[str, str]]
) -> dict[str, list[dict]]:
    groups_by_id = {group.id: group for group in groups}
    columns = {
        group.id: _group_column(group, groups_by_id, relations, {})
        for group in groups
    }
    levels = sorted(set(columns.values()))
    gap = _fit_gap(content_rect["width"], len(levels), _outer_gap(content_rect["width"]))
    column_width = (content_rect["width"] - gap * (len(levels) - 1)) / len(levels)
    result = {}
    for level_index, level in enumerate(levels):
        column_groups = [group for group in groups if columns[group.id] == level]
        group_gap = _fit_gap(
            content_rect["height"], len(column_groups), _outer_gap(content_rect["height"])
        )
        group_height = (
            content_rect["height"] - group_gap * (len(column_groups) - 1)
        ) / len(column_groups)
        for group_index, group in enumerate(column_groups):
            result[group.id] = _arrange_slots(
                group,
                {
                    "x": content_rect["x"] + level_index * (column_width + gap),
                    "y": content_rect["y"] + group_index * (group_height + group_gap),
                    "width": column_width,
                    "height": group_height,
                },
            )
    return result


def _group_column(
    group: LayoutGroup,
    groups_by_id: dict[str, LayoutGroup],
    relations: dict[str, tuple[str, str]],
    cache: dict[str, int],
) -> int:
    if group.id in cache:
        return cache[group.id]
    relation = relations.get(group.id)
    if relation is None:
        column = _REGION_ORDER.index(group.region)
    else:
        parent_id, side = relation
        parent = groups_by_id[parent_id]
        parent_column = _group_column(parent, groups_by_id, relations, cache)
        if side == "right":
            column = parent_column + 1
        elif side == "left":
            column = parent_column - 1
        else:
            column = parent_column
    cache[group.id] = column
    return column


def _group_relations(groups: list[LayoutGroup]) -> dict[str, tuple[str, str]]:
    return {
        group.id: (group.relativeTo, group.side)
        for group in groups
        if group.relativeTo is not None and group.side is not None
    }


def compute_unit_layout(
    group: LayoutGroup,
    slot: dict,
    instance_index: int,
    material_map: dict[str, dict],
) -> list[dict]:
    local_nodes = _compute_local_unit(group, instance_index, material_map)
    fitted = _fit_unit_to_slot(local_nodes, slot)
    return [
        {
            "group_id": node.group_id,
            "node_id": node.node_id,
            "instance_index": node.instance_index,
            "device_type": node.device_type,
            "image": node.image,
            "x": node.x,
            "y": node.y,
            "width": node.width,
            "height": node.height,
        }
        for node in fitted
    ]


def build_nodes(nodes: list[dict]) -> list[dict]:
    name_counts: dict[str, int] = {}
    result: list[dict] = []
    for index, node in enumerate(nodes):
        display_name = _display_name(node["device_type"], name_counts)
        result.append(
            {
                "c": "ht.Node",
                "i": 17092 + index,
                "p": {
                    "displayName": display_name,
                    "image": node["image"],
                    "position": {
                        "x": _round(node["x"]),
                        "y": _round(node["y"]),
                    },
                    "width": _round(node["width"]),
                    "height": _round(node["height"]),
                },
                "a": {
                    "layout.group": node["group_id"],
                    "layout.node": node["node_id"],
                    "layout.instance": node["instance_index"],
                },
            }
        )
    return result


async def convert_layout_file_from_query_results(
    data: dict,
    db,
    query: str = "",
    width: int = 1920,
    height: int = 1080,
) -> list[dict]:
    controls = await db.list_query_results(query)
    return convert_layout_file(data, controls, width, height)


def _content_rect(width: int, height: int) -> dict:
    title_bottom = max(80, round(height * 0.086))
    top = title_bottom + max(20, round(height * 0.02))
    side = max(40, round(width * 0.03))
    bottom = max(40, round(height * 0.06))
    return {
        "x": side,
        "y": top,
        "width": max(100, width - side * 2),
        "height": max(100, height - top - bottom),
    }


def _region_rects(groups: list[LayoutGroup], content_rect: dict, gap: float) -> dict[str, dict]:
    present = {group.region for group in groups}
    if present == {"left", "right"}:
        return _split_regions(content_rect, ["left", "right"], gap)
    if present == {"left"}:
        return _single_side_region(content_rect, "left", gap)
    if present == {"right"}:
        return _single_side_region(content_rect, "right", gap)
    if present == {"center"}:
        return {"center": dict(content_rect)}
    regions = [region for region in _REGION_ORDER if region in present]
    return _split_regions(content_rect, regions, gap)


def _split_regions(content_rect: dict, regions: list[str], gap: float) -> dict[str, dict]:
    count = len(regions)
    gap = _fit_gap(content_rect["width"], count, gap)
    width = (content_rect["width"] - gap * (count - 1)) / count
    result = {}
    for index, region in enumerate(regions):
        result[region] = {
            "x": content_rect["x"] + index * (width + gap),
            "y": content_rect["y"],
            "width": width,
            "height": content_rect["height"],
        }
    return result


def _single_side_region(content_rect: dict, region: str, gap: float) -> dict[str, dict]:
    gap = _fit_gap(content_rect["width"], 2, gap)
    width = (content_rect["width"] - gap) / 2
    x = content_rect["x"]
    if region == "right":
        x += width + gap
    return {
        region: {
            "x": x,
            "y": content_rect["y"],
            "width": width,
            "height": content_rect["height"],
        }
    }


def _arrange_slots(group: LayoutGroup, rect: dict) -> list[dict]:
    count = max(1, group.count)
    rows, cols = _slot_shape(group, count)
    gap = _gap_for(group.gapHint)
    gap_x = _fit_gap(rect["width"], cols, gap)
    gap_y = _fit_gap(rect["height"], rows, gap)
    cell_w = (rect["width"] - gap_x * (cols - 1)) / cols
    cell_h = (rect["height"] - gap_y * (rows - 1)) / rows
    result = []
    for index in range(count):
        if group.order == "col-major" and group.arrangement == "grid":
            row = index % rows
            col = index // rows
        else:
            row = index // cols
            col = index % cols
        result.append(
            {
                "x": rect["x"] + col * (cell_w + gap_x) + cell_w / 2,
                "y": rect["y"] + row * (cell_h + gap_y) + cell_h / 2,
                "width": cell_w,
                "height": cell_h,
            }
        )
    return result


def _slot_shape(group: LayoutGroup, count: int) -> tuple[int, int]:
    if count <= 1:
        return 1, 1
    if group.arrangement == "horizontal":
        return 1, count
    if group.arrangement == "grid":
        cols = group.columns or 0
        rows = group.rows or 0
        if cols <= 0:
            cols = int(math.ceil(count / rows))
        if rows <= 0:
            rows = int(math.ceil(count / cols))
        return rows, cols
    return count, 1


def _compute_local_unit(
    group: LayoutGroup,
    instance_index: int,
    material_map: dict[str, dict],
) -> list[_PlacedNode]:
    gap = _gap_for(group.gapHint)
    root = group.unit.root
    root_node = _new_local_node(
        group.id,
        root.id,
        instance_index,
        root.deviceType,
        True,
        material_map,
        0,
        0,
        root.role,
    )
    nodes = [root_node]
    placed = {root.id: root_node}
    for attachment in group.unit.attachments:
        parent = placed[attachment.relativeTo]
        child_count = attachment.count or 1
        for child_index in range(child_count):
            node_id = attachment.id if child_index == 0 else "%s_%s" % (attachment.id, child_index + 1)
            child = _new_local_node(
                group.id,
                node_id,
                instance_index,
                attachment.deviceType,
                False,
                material_map,
                0,
                0,
                attachment.role,
            )
            _place_child(parent, child, attachment.side, gap, child_index, child_count)
            nodes.append(child)
            placed[node_id] = child
            if child_index == 0:
                placed[attachment.id] = child
    return nodes


def _new_local_node(
    group_id: str,
    node_id: str,
    instance_index: int,
    device_type: str,
    is_root: bool,
    material_map: dict[str, dict],
    x: float,
    y: float,
    explicit_role: Optional[str] = None,
) -> _PlacedNode:
    material = _match_material(device_type, material_map)
    width, height = _fit_size(device_type, is_root, material, explicit_role)
    image = material.get("image") or "symbols/Agent/%s.json" % device_type
    return _PlacedNode(group_id, node_id, instance_index, device_type, image, x, y, width, height)


def _place_child(
    parent: _PlacedNode,
    child: _PlacedNode,
    side: str,
    gap: float,
    index: int,
    count: int,
) -> None:
    offset_index = index - (count - 1) / 2
    if side == "top":
        child.x = parent.x + offset_index * (child.width + gap)
        child.y = parent.y - parent.height / 2 - gap - child.height / 2
    elif side == "bottom":
        child.x = parent.x + offset_index * (child.width + gap)
        child.y = parent.y + parent.height / 2 + gap + child.height / 2
    elif side == "left":
        child.x = parent.x - parent.width / 2 - gap - child.width / 2
        child.y = parent.y + offset_index * (child.height + gap)
    else:
        child.x = parent.x + parent.width / 2 + gap + child.width / 2
        child.y = parent.y + offset_index * (child.height + gap)


def _fit_unit_to_slot(nodes: list[_PlacedNode], slot: dict) -> list[_PlacedNode]:
    bbox = _node_bbox(nodes)
    usable_w = slot["width"] * 0.86
    usable_h = slot["height"] * 0.86
    scale = min(usable_w / bbox["width"], usable_h / bbox["height"], 1)
    center_x = bbox["x"] + bbox["width"] / 2
    center_y = bbox["y"] + bbox["height"] / 2
    result = []
    for node in nodes:
        result.append(
            _PlacedNode(
                node.group_id,
                node.node_id,
                node.instance_index,
                node.device_type,
                node.image,
                slot["x"] + (node.x - center_x) * scale,
                slot["y"] + (node.y - center_y) * scale,
                node.width * scale,
                node.height * scale,
            )
        )
    return result


def _node_bbox(nodes: list[_PlacedNode]) -> dict:
    min_x = min(node.x - node.width / 2 for node in nodes)
    min_y = min(node.y - node.height / 2 for node in nodes)
    max_x = max(node.x + node.width / 2 for node in nodes)
    max_y = max(node.y + node.height / 2 for node in nodes)
    return {"x": min_x, "y": min_y, "width": max(max_x - min_x, 1), "height": max(max_y - min_y, 1)}


def _fit_size(device_type: str, is_root: bool, material: dict, explicit_role: Optional[str] = None) -> tuple[float, float]:
    config = _load_layout_config()
    role = _role(device_type, is_root, explicit_role, config)
    entry = config.roles.get(role)
    if entry is None:
        entry = _DEFAULT_LAYOUT_CONFIG.roles["default"]
    limits = entry.limits
    raw_w = _number(material.get("width"), limits.preferred_w)
    raw_h = _number(material.get("height"), limits.preferred_h)
    if raw_w <= 0 or raw_h <= 0:
        raw_w = limits.preferred_w
        raw_h = limits.preferred_h
    min_scale = max(limits.min_w / raw_w, limits.min_h / raw_h)
    max_scale = min(limits.max_w / raw_w, limits.max_h / raw_h)
    if min_scale > max_scale:
        return limits.preferred_w, limits.preferred_h
    scale = min(1, max_scale)
    if scale < min_scale:
        scale = min_scale
    return raw_w * scale, raw_h * scale


def _role(
    device_type: str,
    is_root: bool,
    explicit_role: Optional[str] = None,
    config: Optional[LayoutConfig] = None,
) -> str:
    if config is None:
        config = _load_layout_config()
    if explicit_role:
        return explicit_role
    if is_root:
        return config.root_role_name
    for name, entry in config.roles.items():
        if name == config.root_role_name or name == "default":
            continue
        for keyword in entry.keywords:
            if keyword and keyword in device_type:
                return name
    return "default"


def _material_map(controls: list[dict]) -> dict[str, dict]:
    result = {}
    for control in controls:
        if not _is_control_material(control):
            continue
        name = str(control.get("displayName") or "")
        if name and name not in result:
            result[name] = control
    return result


def _is_control_material(control: dict) -> bool:
    if not isinstance(control, dict):
        return False
    if _is_canvas_json(control):
        return False
    name = str(control.get("displayName") or "")
    if not name:
        return False
    image = str(control.get("image") or "")
    if image and _is_canvas_json_path(image):
        return False
    return True


def _is_canvas_json(data: dict) -> bool:
    if not isinstance(data, dict):
        return False
    props = data.get("p")
    attrs = data.get("a")
    return (
        isinstance(data.get("v"), str)
        and isinstance(props, dict)
        and isinstance(attrs, dict)
        and isinstance(data.get("d"), list)
        and isinstance(data.get("contentRect"), dict)
        and "width" in attrs
        and "height" in attrs
    )


def _is_canvas_json_path(image: str) -> bool:
    if not image.lower().endswith(".json"):
        return False
    path = Path(image)
    candidates = (
        [path]
        if path.is_absolute()
        else [Path.cwd() / path, Path(__file__).resolve().parent.parent / path]
    )
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return False
        return _is_canvas_json(data)
    return False


def _match_material(device_type: str, material_map: dict[str, dict]) -> dict:
    material = _find_material(device_type, material_map)
    if material is None:
        raise MissingMaterialError("query_results 缺少控件素材：" + device_type)
    return material


def _find_material(device_type: str, material_map: dict[str, dict]) -> Optional[dict]:
    if device_type in material_map:
        return material_map[device_type]
    for name, material in material_map.items():
        if device_type in name or name in device_type:
            return material
    return None


def _gap_for(gap_hint: Optional[str]) -> int:
    if gap_hint == "tight":
        return 20
    if gap_hint == "loose":
        return 70
    return 40


def _outer_gap(size: float) -> int:
    return int(min(48, max(20, round(size * 0.03))))


def _fit_gap(size: float, count: int, gap: float) -> float:
    if count <= 1:
        return 0
    return min(gap, max(0, (size - count) / (count - 1)))


def _display_name(base: str, counts: dict[str, int]) -> str:
    counts[base] = counts.get(base, 0) + 1
    if counts[base] == 1:
        return base
    return "%s%s" % (base, counts[base])


def _number(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _round(value: float):
    rounded = round(value, 2)
    if rounded == int(rounded):
        return int(rounded)
    return rounded


async def _load_query_results(query: str) -> list[dict]:
    from data.sqlite.material_db import MaterialDB

    db = MaterialDB()
    await db.init_query_results_db()
    try:
        return await db.list_query_results(query)
    finally:
        await db.close()


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="根据布局意图计算 HT 控件坐标")
    parser.add_argument("--input", default="layout/ir.json")
    parser.add_argument("--output", default="")
    parser.add_argument("--query", default="")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    input_path = Path(args.input)
    data = json.loads(input_path.read_text(encoding="utf-8"))
    controls = asyncio.run(_load_query_results(args.query))
    nodes = convert_layout_file(data, controls, args.width, args.height)
    if args.output:
        output_path = Path(args.output)
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = Path("output") / ("position_%s.json" % ts)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(nodes, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
