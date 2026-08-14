from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Optional

from model.layout_tools.control_size import resolve_control_size
from model.layout_tools.geometry import (
    content_rect_of_canvas,
    content_rect_of_nodes,
    inscribe_ratio,
)
from model.llm_client import default_client, default_model, call_llm


_DEFAULT_WIDTH = 60
_DEFAULT_HEIGHT = 40
_LABEL_COLOR = "rgb(255,255,255)"
_LABEL_FONT = "18px arial, sans-serif"
_LABEL_FIELD_KEYS = ("label", "label.color", "label.font")
_ALIGNMENTS = {"left", "right", "top", "bottom", "center_x", "center_y"}
_DISTRIBUTION_AXES = {"horizontal", "vertical"}
_ACTION_FIELDS = {
    "move": {"type", "target_ids", "dx", "dy", "x", "y"},
    "resize": {"type", "target_ids", "scale", "width", "height"},
    "delete": {"type", "target_ids"},
    "align": {"type", "target_ids", "alignment"},
    "distribute": {"type", "target_ids", "axis"},
    "add_label": {"type", "target_ids", "text", "names"},
    "add_control": {"type", "target_ids", "material_candidates", "sides"},
    "swap": {"type", "target_ids"},
}

_ADD_GAP = 40
_MIN_SCALE_PERCENT = 50
_SIDE_NAMES = {"left": "左侧", "right": "右侧", "top": "上方", "bottom": "下方"}
_ADD_TOLERANCE = 0.02


@dataclass
class RefineResult:
    patch: list[dict[str, Any]]
    message: str


class RefineInputError(ValueError):
    pass


class RefineUnavailableError(RuntimeError):
    pass


class RefineModelError(RuntimeError):
    pass


@dataclass
class _ControlGeometry:
    node_i: int
    index: int
    x: Any
    y: Any
    width: Any
    height: Any
    original_x: Any
    original_y: Any
    original_width: Any
    original_height: Any
    has_width: bool
    has_height: bool
    image: str = ""
    touched: bool = False
    deleted: bool = False
    aspect: Optional[float] = None
    node_type: Any = ""
    has_s: bool = False
    s_value: Any = None
    label_value: Optional[str] = None


@dataclass
class _LabelInfo:
    node_i: int
    index: int
    label_for: int
    x: Any
    y: Any
    width: Any
    height: Any
    text: str
    touched: bool = False
    deleted: bool = False


def _is_finite_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, TypeError, ValueError):
        return False


def _require_input_number(value: Any, name: str, positive: bool = False) -> Any:
    if not _is_finite_number(value) or (positive and value <= 0):
        raise RefineInputError(f"{name} must be a finite number")
    return value


def _require_model_number(value: Any, name: str, positive: bool = False) -> None:
    if not _is_finite_number(value) or (positive and value <= 0):
        raise RefineModelError(f"{name} must be a finite number")


def _clamp(value: Any, lower: Any, upper: Any) -> Any:
    return max(lower, min(value, upper))


def _aspect_from_attributes(item_attributes: dict[str, Any]) -> Optional[float]:
    raw_w = item_attributes.get("layout.sourceWidth")
    raw_h = item_attributes.get("layout.sourceHeight")
    if not isinstance(raw_w, (int, float)) or isinstance(raw_w, bool):
        return None
    if not isinstance(raw_h, (int, float)) or isinstance(raw_h, bool):
        return None
    if not (math.isfinite(raw_w) and math.isfinite(raw_h) and raw_w > 0 and raw_h > 0):
        return None
    return raw_w / raw_h


def _clamp_geometry(
    control: _ControlGeometry, canvas_width: Any, canvas_height: Any
) -> None:
    control.width = _clamp(control.width, 1, canvas_width)
    control.height = _clamp(control.height, 1, canvas_height)
    control.x = _clamp(
        control.x,
        control.width / 2,
        canvas_width - control.width / 2,
    )
    control.y = _clamp(
        control.y,
        control.height / 2,
        canvas_height - control.height / 2,
    )


def _clamp_ratio_geometry(
    control: _ControlGeometry, canvas_width: Any, canvas_height: Any
) -> None:
    if control.width < 1 or control.height < 1:
        floor_scale = 1 / min(control.width, control.height)
        control.width *= floor_scale
        control.height *= floor_scale
    if control.width > canvas_width or control.height > canvas_height:
        canvas_scale = min(canvas_width / control.width, canvas_height / control.height)
        control.width *= canvas_scale
        control.height *= canvas_scale
    control.x = _clamp(
        control.x,
        control.width / 2,
        canvas_width - control.width / 2,
    )
    control.y = _clamp(
        control.y,
        control.height / 2,
        canvas_height - control.height / 2,
    )


def _read_layout(
    json_data: dict[str, Any],
) -> tuple[
    Any,
    Any,
    dict[int, _ControlGeometry],
    list[dict[str, Any]],
    dict[int, _LabelInfo],
]:
    if not isinstance(json_data, dict):
        raise RefineInputError("json_data must be an object")
    attributes = json_data.get("a")
    entries = json_data.get("d")
    if not isinstance(attributes, dict) or not isinstance(entries, list):
        raise RefineInputError("json_data must contain canvas attributes and data")
    canvas_width = _require_input_number(
        attributes.get("width"), "canvas width", positive=True
    )
    canvas_height = _require_input_number(
        attributes.get("height"), "canvas height", positive=True
    )

    controls: dict[int, _ControlGeometry] = {}
    catalog: list[dict[str, Any]] = []
    control_node_is: set[int] = set()

    for index, item in enumerate(entries):
        if not isinstance(item, dict):
            continue
        item_attributes = item.get("a")
        if (
            not isinstance(item_attributes, dict)
            or item_attributes.get("layout.node") is None
        ):
            continue
        properties = item.get("p")
        if not isinstance(properties, dict):
            raise RefineInputError("editable control properties must be an object")
        position = properties.get("position")
        if not isinstance(position, dict):
            raise RefineInputError("editable control position must be an object")

        node_i = item.get("i")
        if isinstance(node_i, bool) or not isinstance(node_i, int):
            raise RefineInputError("editable control IDs must be integers")
        if node_i in controls:
            raise RefineInputError("editable control IDs must be unique")
        control_node_is.add(node_i)
        node_type = item.get("c")
        s_value = item.get("s")
        has_s = "s" in item and s_value is not None
        x = _require_input_number(position.get("x"), f"control {node_i} x")
        y = _require_input_number(position.get("y"), f"control {node_i} y")
        has_width = "width" in properties
        has_height = "height" in properties
        width = _require_input_number(
            properties.get("width", _DEFAULT_WIDTH), f"control {node_i} width"
        )
        height = _require_input_number(
            properties.get("height", _DEFAULT_HEIGHT), f"control {node_i} height"
        )
        image = properties.get("image", "")
        if not isinstance(image, str):
            image = str(image)
        aspect = _aspect_from_attributes(item_attributes)
        control = _ControlGeometry(
            node_i=node_i,
            index=index,
            x=x,
            y=y,
            width=_clamp(width, 1, canvas_width),
            height=_clamp(height, 1, canvas_height),
            original_x=x,
            original_y=y,
            original_width=width,
            original_height=height,
            has_width=has_width,
            has_height=has_height,
            image=image,
            aspect=aspect,
            node_type=node_type,
            has_s=has_s,
            s_value=s_value,
        )
        controls[node_i] = control
        display_name = properties.get("displayName", "")
        if not isinstance(display_name, str):
            display_name = str(display_name)
        catalog.append(
            {
                "i": node_i,
                "displayName": display_name,
                "x": x,
                "y": y,
                "width": width,
                "height": height,
            }
        )

    labels: dict[int, _LabelInfo] = {}
    label_node_is: set[int] = set()
    for index, item in enumerate(entries):
        if not isinstance(item, dict):
            continue
        item_attributes = item.get("a")
        if not isinstance(item_attributes, dict):
            continue
        if (
            item.get("c") != "ht.Text"
            or item_attributes.get("layout.role") != "control-label"
        ):
            continue
        label_for = item_attributes.get("layout.labelFor")
        if not isinstance(label_for, int) or isinstance(label_for, bool):
            raise RefineInputError("layout.labelFor must be an integer")
        if label_for not in controls:
            raise RefineInputError(
                f"labelFor {label_for} does not reference an editable control"
            )
        if label_for in labels:
            raise RefineInputError(f"duplicate label for control {label_for}")

        node_i = item.get("i")
        if isinstance(node_i, bool) or not isinstance(node_i, int):
            raise RefineInputError("label node ID must be an integer")
        if node_i in control_node_is or node_i in label_node_is:
            raise RefineInputError(f"duplicate node ID {node_i}")
        label_node_is.add(node_i)

        properties = item.get("p")
        if not isinstance(properties, dict):
            raise RefineInputError("label properties must be an object")
        position = properties.get("position")
        if not isinstance(position, dict):
            raise RefineInputError("label position must be an object")

        s = item.get("s")
        if not isinstance(s, dict):
            s = {}

        labels[label_for] = _LabelInfo(
            node_i=node_i,
            index=index,
            label_for=label_for,
            x=_require_input_number(position.get("x"), f"label {node_i} x"),
            y=_require_input_number(position.get("y"), f"label {node_i} y"),
            width=_require_input_number(
                properties.get("width", 0), f"label {node_i} width"
            ),
            height=_require_input_number(
                properties.get("height", 0), f"label {node_i} height"
            ),
            text=s.get("text", ""),
        )

    return canvas_width, canvas_height, controls, catalog, labels


def _build_prompt(
    canvas_width: Any,
    canvas_height: Any,
    catalog: list[dict[str, Any]],
    selected_node_ids: tuple[int, ...],
    materials: Optional[list[dict[str, Any]]] = None,
) -> str:
    selected = "none" if not selected_node_ids else ",".join(str(i) for i in selected_node_ids)
    catalog_json = json.dumps(catalog, ensure_ascii=False, indent=2)
    materials_json = json.dumps(materials or [], ensure_ascii=False, indent=2)
    return f"""You refine an interactive SCADA canvas by returning semantic actions.
Canvas width: {canvas_width}
Canvas height: {canvas_height}
Selected control ID(s): {selected}
Control catalog with stable IDs and current geometry:
{catalog_json}

Materials available for adding controls (exact display names from the layout snapshot):
{materials_json}

When the user says "these controls" or "选中控件", apply the action to the current selected ID(s).
When the user explicitly names a control or ID, use that specific target — do not merge with the current selection.
If there is no selection and no explicit target, return empty actions and a clarifying message.
Always return a non-empty string in "message", including when actions are generated.

Return exactly one JSON object with only "message" and "actions".
Supported actions are:
{{"type":"move","target_ids":[12],"dx":200,"dy":0}}
{{"type":"move","target_ids":[12],"x":300,"y":200}}
{{"type":"resize","target_ids":[12],"scale":1.2}}
{{"type":"resize","target_ids":[12],"width":120,"height":80}}
{{"type":"delete","target_ids":[12]}}
{{"type":"align","target_ids":[12,13],"alignment":"left"}}
{{"type":"distribute","target_ids":[12,13,14],"axis":"horizontal"}}
{{"type":"swap","target_ids":[12,13]}}
{{"type":"add_label","target_ids":[12]}}
{{"type":"add_label","target_ids":[12],"text":"入口阀"}}
{{"type":"add_label","target_ids":[12,13],"text":"阀门"}}
{{"type":"add_label","target_ids":[12,13],"names":{{"12":"入口阀","13":"出口阀"}}}}
{{"type":"add_control","target_ids":[12],"material_candidates":["状态面板"],"sides":["left"]}}
Allowed alignments: left, right, top, bottom, center_x, center_y.
Allowed distribution axes: horizontal, vertical.
For swap: exchange the positions of exactly two controls; keep their sizes unchanged.
For naming: text and names are mutually exclusive; without either, each control uses its own displayName.
names keys must be JSON strings matching control IDs exactly, e.g. "12" for control 12.
Do not add fields outside the selected action schema.

Rules for add_control:
- Use it only when the user asks to add a control; it must be the ONLY action in the response.
- target_ids must be exactly the single currently selected control ID; never name another control.
- material_candidates must use exact display names from the material list above. When the user's request could match several materials, return all plausible candidates (up to 5) and let the backend decide; never guess a single one.
- sides accepts a single "left"/"right"/"top"/"bottom", or ["left","right"], or ["top","bottom"]. "两侧" means left and right. When the user does not specify a side, omit sides and the backend will ask instead of guessing."""


def _response_data(response: Any) -> dict[str, Any]:
    if isinstance(response, str):
        content = response
    else:
        try:
            content = response.choices[0].message.content
        except Exception as exc:
            raise RefineModelError("model response has no content") from exc
    if not isinstance(content, str) or not content.strip():
        raise RefineModelError("model response is empty")
    try:
        data = json.loads(content)
    except (TypeError, ValueError) as exc:
        raise RefineModelError("model response is not JSON") from exc
    if not isinstance(data, dict):
        raise RefineModelError("model response must be an object")
    return data


def _validate_targets(action: dict[str, Any], known_ids: set[int]) -> list[int]:
    target_ids = action.get("target_ids")
    if not isinstance(target_ids, list) or not target_ids:
        raise RefineModelError("target_ids must be a non-empty array")
    if any(isinstance(value, bool) or not isinstance(value, int) for value in target_ids):
        raise RefineModelError("target IDs must be integers")
    if len(set(target_ids)) != len(target_ids):
        raise RefineModelError("target IDs must be unique")
    if any(value not in known_ids for value in target_ids):
        raise RefineModelError("model returned an unknown target ID")
    return target_ids


def _validate_action(action: Any, known_ids: set[int]) -> None:
    if not isinstance(action, dict):
        raise RefineModelError("each action must be an object")
    action_type = action.get("type")
    if not isinstance(action_type, str) or action_type not in _ACTION_FIELDS:
        raise RefineModelError("unsupported action type")
    required_fields = {"type", "target_ids"}
    if not required_fields.issubset(action) or not set(action).issubset(
        _ACTION_FIELDS[action_type]
    ):
        raise RefineModelError("action contains invalid fields")
    target_ids = _validate_targets(action, known_ids)

    if action_type == "move":
        coordinate_fields = {"x", "y", "dx", "dy"}.intersection(action)
        if not coordinate_fields:
            raise RefineModelError("move requires a coordinate")
        for name in coordinate_fields:
            _require_model_number(action[name], name)
        if ("x" in action and "dx" in action) or (
            "y" in action and "dy" in action
        ):
            raise RefineModelError("move cannot mix absolute and relative axes")
        if ("x" in action or "y" in action) and len(target_ids) != 1:
            raise RefineModelError("absolute move requires one target")
    elif action_type == "resize":
        resize_fields = {"scale", "width", "height"}.intersection(action)
        if not resize_fields:
            raise RefineModelError("resize requires a size")
        for name in resize_fields:
            _require_model_number(action[name], name, positive=True)
        if "scale" in action and ({"width", "height"}.intersection(action)):
            raise RefineModelError("resize cannot mix scale and exact dimensions")
    elif action_type == "align":
        if set(action) != {"type", "target_ids", "alignment"}:
            raise RefineModelError("align contains invalid fields")
        alignment = action["alignment"]
        if (
            len(target_ids) < 2
            or not isinstance(alignment, str)
            or alignment not in _ALIGNMENTS
        ):
            raise RefineModelError("invalid alignment action")
    elif action_type == "distribute":
        if set(action) != {"type", "target_ids", "axis"}:
            raise RefineModelError("distribute contains invalid fields")
        axis = action["axis"]
        if (
            len(target_ids) < 3
            or not isinstance(axis, str)
            or axis not in _DISTRIBUTION_AXES
        ):
            raise RefineModelError("invalid distribution action")
    elif action_type == "swap":
        if set(action) != {"type", "target_ids"}:
            raise RefineModelError("swap contains invalid fields")
        if len(target_ids) != 2:
            raise RefineModelError("swap requires exactly two targets")
    elif action_type == "add_label":
        if "text" in action and "names" in action:
            raise RefineModelError("add_label cannot have both text and names")
        if "names" in action:
            names = action["names"]
            if not isinstance(names, dict):
                raise RefineModelError("add_label names must be an object")
    elif action_type == "add_control":
        if not set(action).issubset(
            {"type", "target_ids", "material_candidates", "sides"}
        ):
            raise RefineModelError("add_control contains invalid fields")
        if "material_candidates" in action:
            candidates = action["material_candidates"]
            if not isinstance(candidates, list):
                raise RefineModelError("material_candidates must be an array")
            if not candidates:
                raise RefineModelError("material_candidates must not be empty")
            if any(not isinstance(value, str) for value in candidates):
                raise RefineModelError("material_candidates must be strings")
            if len(set(candidates)) > 5:
                raise RefineModelError(
                    "material_candidates must have at most 5 unique names"
                )
        if "sides" in action:
            sides = action["sides"]
            if isinstance(sides, str):
                if not sides:
                    raise RefineModelError("sides must not be empty")
            elif isinstance(sides, list):
                if not sides:
                    raise RefineModelError("sides must not be empty")
                if any(not isinstance(value, str) for value in sides):
                    raise RefineModelError("sides must be strings")
            else:
                raise RefineModelError("sides must be an array or string")


def _validate_model_data(data: dict[str, Any], known_ids: set[int]) -> None:
    if not set(data).issubset({"message", "actions"}) or "actions" not in data:
        raise RefineModelError("model response contains invalid fields")
    actions = data["actions"]
    if not isinstance(actions, list):
        raise RefineModelError("model actions must be an array")
    for action in actions:
        _validate_action(action, known_ids)
    message = data.get("message")
    if not isinstance(message, str) or not message.strip():
        if not actions:
            raise RefineModelError("model message must be a non-empty string")
        data["message"] = "已生成微调方案。"


def _align(controls: list[_ControlGeometry], alignment: str) -> None:
    if alignment == "left":
        edge = min(control.x - control.width / 2 for control in controls)
        for control in controls:
            control.x = edge + control.width / 2
    elif alignment == "right":
        edge = max(control.x + control.width / 2 for control in controls)
        for control in controls:
            control.x = edge - control.width / 2
    elif alignment == "top":
        edge = min(control.y - control.height / 2 for control in controls)
        for control in controls:
            control.y = edge + control.height / 2
    elif alignment == "bottom":
        edge = max(control.y + control.height / 2 for control in controls)
        for control in controls:
            control.y = edge - control.height / 2
    elif alignment == "center_x":
        left = min(control.x - control.width / 2 for control in controls)
        right = max(control.x + control.width / 2 for control in controls)
        center = (left + right) / 2
        for control in controls:
            control.x = center
    else:
        top = min(control.y - control.height / 2 for control in controls)
        bottom = max(control.y + control.height / 2 for control in controls)
        center = (top + bottom) / 2
        for control in controls:
            control.y = center


def _distribute(controls: list[_ControlGeometry], axis: str) -> None:
    if axis == "horizontal":
        ordered = sorted(controls, key=lambda control: (control.x, control.index))
        first_edge = ordered[0].x - ordered[0].width / 2
        last_edge = ordered[-1].x + ordered[-1].width / 2
        total_size = sum(control.width for control in ordered)
        gap = (last_edge - first_edge - total_size) / (len(ordered) - 1)
        cursor = first_edge
        for control in ordered:
            control.x = cursor + control.width / 2
            cursor += control.width + gap
    else:
        ordered = sorted(controls, key=lambda control: (control.y, control.index))
        first_edge = ordered[0].y - ordered[0].height / 2
        last_edge = ordered[-1].y + ordered[-1].height / 2
        total_size = sum(control.height for control in ordered)
        gap = (last_edge - first_edge - total_size) / (len(ordered) - 1)
        cursor = first_edge
        for control in ordered:
            control.y = cursor + control.height / 2
            cursor += control.height + gap


def _validate_label_text(text: str) -> str:
    if not isinstance(text, str):
        raise RefineInputError("label text must be a string")
    if not text or text.strip() != text:
        raise RefineInputError("label text must not be empty or have leading/trailing whitespace")
    for ch in text:
        if ord(ch) < 0x20 and ch not in ("\t", "\n", "\r"):
            raise RefineInputError("label text contains control characters")
    if "\n" in text:
        raise RefineInputError("label text must not contain newlines")
    return text


def _compute_label_geometry(
    control: _ControlGeometry,
    text: str,
    canvas_width: Any,
    canvas_height: Any,
) -> tuple[Any, Any, Any, Any]:
    label_height = 32
    text_width = len(text) * 20 + 16
    label_width = max(control.width, text_width)

    if label_width > canvas_width:
        raise RefineInputError(
            f"label text too long ({len(text)} characters, estimated width {label_width} > canvas {canvas_width})"
        )

    label_x = control.x
    half_label_width = label_width / 2
    if label_x - half_label_width < 0:
        label_x = half_label_width
    if label_x + half_label_width > canvas_width:
        label_x = canvas_width - half_label_width

    half_label_height = label_height / 2
    gap = 8

    above_y = control.y - control.height / 2 - gap - half_label_height
    if above_y - half_label_height >= 0:
        label_y = above_y
    else:
        below_y = control.y + control.height / 2 + gap + half_label_height
        if below_y + half_label_height <= canvas_height:
            label_y = below_y
        else:
            raise RefineInputError(
                f"no space for label {'above or ' if above_y < 0 else ''}below control {control.node_i}"
            )

    return label_width, label_height, label_x, label_y


def _make_label_map(
    action: dict[str, Any],
    controls: dict[int, _ControlGeometry],
    catalog: list[dict[str, Any]],
) -> dict[int, str]:
    target_ids = action["target_ids"]
    catalog_map = {entry["i"]: entry for entry in catalog}

    if len(target_ids) > 1:
        images = [controls[node_i].image for node_i in target_ids]
        if any(img != images[0] for img in images):
            raise RefineInputError(
                "multi-select add_label requires all targets to have the same image type"
            )

    for node_i in target_ids:
        control = controls[node_i]
        if control.node_type != "ht.Node":
            raise RefineInputError(
                f"control {node_i} is not an ht.Node and cannot be named"
            )
        if control.has_s and not isinstance(control.s_value, dict):
            raise RefineInputError(
                f"control {node_i} style must be an object to be named"
            )

    if "names" in action:
        names = action["names"]
        result: dict[int, str] = {}
        for raw_key, name_value in names.items():
            if isinstance(raw_key, bool) or not isinstance(raw_key, str):
                raise RefineInputError("add_label names keys must be JSON strings")
            if not isinstance(name_value, str):
                raise RefineInputError("add_label names values must be strings")
            if not raw_key.isdigit() or str(int(raw_key)) != raw_key:
                raise RefineInputError(
                    "add_label names keys must match integer IDs exactly"
                )
            node_i = int(raw_key)
            if node_i in result:
                raise RefineInputError(
                    "add_label names contains duplicate normalized IDs"
                )
            if node_i not in controls:
                raise RefineInputError(
                    f"add_label names references unknown ID {node_i}"
                )
            result[node_i] = _validate_label_text(name_value)
        for node_i in target_ids:
            if node_i not in result:
                raise RefineInputError(
                    f"add_label names missing entry for control {node_i}"
                )
        return result

    if "text" in action:
        base_text = action["text"]
        if not isinstance(base_text, str):
            raise RefineModelError("add_label text must be a string")
        _validate_label_text(base_text)
        if len(target_ids) == 1:
            return {target_ids[0]: base_text}
        return {
            node_i: f"{base_text}{idx + 1}"
            for idx, node_i in enumerate(target_ids)
        }

    result = {}
    for node_i in target_ids:
        entry = catalog_map.get(node_i)
        name = (entry.get("displayName") if entry else None) or ""
        if not name:
            raise RefineInputError(
                f"control {node_i} has no displayName and no text provided"
            )
        result[node_i] = _validate_label_text(name)
    return result


def _update_label_from_control(
    label: _LabelInfo,
    control: _ControlGeometry,
    canvas_width: Any,
    canvas_height: Any,
) -> None:
    label_width, label_height, label_x, label_y = _compute_label_geometry(
        control, label.text, canvas_width, canvas_height
    )
    label.x = label_x
    label.y = label_y
    label.width = label_width
    label.height = label_height
    label.touched = True


def _normalize_sides(sides: list[str]) -> list[str]:
    if len(sides) == 1:
        side = sides[0]
        if side not in _SIDE_NAMES:
            raise RefineInputError(f"不支持的方位：{side}")
        return [side]
    if len(sides) != 2:
        raise RefineInputError("仅支持单个方位或左右、上下成对方位")
    if sorted(sides) == ["left", "right"]:
        return ["left", "right"]
    if sorted(sides) == ["bottom", "top"]:
        return ["top", "bottom"]
    raise RefineInputError("仅支持成对添加左右两侧或上下两侧")


def _place_at(
    anchor: _ControlGeometry,
    side: str,
    width: float,
    height: float,
) -> tuple[float, float]:
    if side == "left":
        return anchor.x - anchor.width / 2 - _ADD_GAP - width / 2, anchor.y
    if side == "right":
        return anchor.x + anchor.width / 2 + _ADD_GAP + width / 2, anchor.y
    if side == "top":
        return anchor.x, anchor.y - anchor.height / 2 - _ADD_GAP - height / 2
    return anchor.x, anchor.y + anchor.height / 2 + _ADD_GAP + height / 2


def _rect_gap(
    x: float,
    y: float,
    width: float,
    height: float,
    ox: float,
    oy: float,
    ow: float,
    oh: float,
) -> float:
    left = x - width / 2
    right = x + width / 2
    top = y - height / 2
    bottom = y + height / 2
    o_left = ox - ow / 2
    o_right = ox + ow / 2
    o_top = oy - oh / 2
    o_bottom = oy + oh / 2
    gap_x = max(o_left - right, left - o_right, 0.0)
    gap_y = max(o_top - bottom, top - o_bottom, 0.0)
    if gap_x > 0 and gap_y > 0:
        return math.hypot(gap_x, gap_y)
    return max(gap_x, gap_y)


def _anchor_edge_gap(
    x: float,
    y: float,
    width: float,
    height: float,
    anchor: _ControlGeometry,
    side: str,
) -> float:
    if side == "left":
        return anchor.x - anchor.width / 2 - (x - width / 2)
    if side == "right":
        return x - width / 2 - (anchor.x + anchor.width / 2)
    if side == "top":
        return anchor.y - anchor.height / 2 - (y - height / 2)
    return y - height / 2 - (anchor.y + anchor.height / 2)


def _fits(
    x: float,
    y: float,
    width: float,
    height: float,
    safe: dict[str, Any],
    canvas_width: Any,
    canvas_height: Any,
    obstacles: list[_ControlGeometry],
) -> bool:
    left = x - width / 2
    right = x + width / 2
    top = y - height / 2
    bottom = y + height / 2
    if left < 0 or top < 0 or right > canvas_width or bottom > canvas_height:
        return False
    if (
        left < safe["x"]
        or top < safe["y"]
        or right > safe["x"] + safe["width"]
        or bottom > safe["y"] + safe["height"]
    ):
        return False
    for obstacle in obstacles:
        if (
            _rect_gap(
                x,
                y,
                width,
                height,
                obstacle.x,
                obstacle.y,
                obstacle.width,
                obstacle.height,
            )
            < _ADD_GAP
        ):
            return False
    return True


def _max_fit_scale(
    anchor: _ControlGeometry,
    side: str,
    base_width: float,
    base_height: float,
    safe: dict[str, Any],
    canvas_width: Any,
    canvas_height: Any,
    obstacles: list[_ControlGeometry],
) -> Optional[tuple[int, float, float, float, float]]:
    for percent in range(100, _MIN_SCALE_PERCENT - 1, -1):
        width = base_width * percent / 100
        height = base_height * percent / 100
        x, y = _place_at(anchor, side, width, height)
        if _fits(x, y, width, height, safe, canvas_width, canvas_height, obstacles):
            return percent, x, y, width, height
    return None


def _verify_placement(
    x: float,
    y: float,
    width: float,
    height: float,
    anchor: _ControlGeometry,
    side: str,
    safe: dict[str, Any],
    canvas_width: Any,
    canvas_height: Any,
    obstacles: list[_ControlGeometry],
) -> bool:
    left = x - width / 2
    right = x + width / 2
    top = y - height / 2
    bottom = y + height / 2
    if (
        left < -_ADD_TOLERANCE
        or top < -_ADD_TOLERANCE
        or right > canvas_width + _ADD_TOLERANCE
        or bottom > canvas_height + _ADD_TOLERANCE
    ):
        return False
    if (
        left < safe["x"] - _ADD_TOLERANCE
        or top < safe["y"] - _ADD_TOLERANCE
        or right > safe["x"] + safe["width"] + _ADD_TOLERANCE
        or bottom > safe["y"] + safe["height"] + _ADD_TOLERANCE
    ):
        return False
    if side in ("left", "right") and abs(y - anchor.y) > _ADD_TOLERANCE:
        return False
    if side in ("top", "bottom") and abs(x - anchor.x) > _ADD_TOLERANCE:
        return False
    if _anchor_edge_gap(x, y, width, height, anchor, side) < _ADD_GAP - _ADD_TOLERANCE:
        return False
    for obstacle in obstacles:
        if (
            _rect_gap(
                x,
                y,
                width,
                height,
                obstacle.x,
                obstacle.y,
                obstacle.width,
                obstacle.height,
            )
            < _ADD_GAP - _ADD_TOLERANCE
        ):
            return False
    return True


def _validate_snapshot_structure(json_data: dict[str, Any]) -> None:
    attributes = json_data.get("a")
    if not isinstance(attributes, dict):
        raise RefineInputError("canvas attributes must be an object")
    if "layout.materials" not in attributes:
        return
    snapshot = attributes["layout.materials"]
    if not isinstance(snapshot, list):
        raise RefineInputError("layout.materials must be an array")
    for item in snapshot:
        if not isinstance(item, dict):
            raise RefineInputError("layout.materials entries must be objects")
        name = item.get("displayName")
        if not isinstance(name, str) or not name:
            raise RefineInputError(
                "layout.materials displayName must be a non-empty string"
            )
        if "image" in item and not isinstance(item["image"], str):
            raise RefineInputError("layout.materials image must be a string")
        for key in ("width", "height"):
            if key in item and not _is_finite_number(item[key]):
                raise RefineInputError(
                    f"layout.materials {key} must be a finite number"
                )


def _unique_add_name(base: str, used_names: set[str]) -> str:
    name = base
    suffix = 2
    while name in used_names:
        name = f"{base}{suffix}"
        suffix += 1
    used_names.add(name)
    return name


def _round2(value: float):
    rounded = round(value, 2)
    if rounded == int(rounded):
        return int(rounded)
    return rounded


def _apply_add_control(
    actions: list[dict[str, Any]],
    json_data: dict[str, Any],
    controls: dict[int, _ControlGeometry],
    labels: dict[int, _LabelInfo],
    canvas_width: Any,
    canvas_height: Any,
    selection: tuple[int, ...],
) -> RefineResult:
    if len(actions) != 1 or actions[0].get("type") != "add_control":
        raise RefineInputError("添加控件必须独占一次请求，不能与其他动作混用")
    action = actions[0]
    if len(selection) != 1:
        raise RefineInputError("添加控件需要先单选一个锚点控件")
    anchor_i = selection[0]
    target_ids = action["target_ids"]
    if len(target_ids) != 1 or target_ids[0] != anchor_i:
        raise RefineInputError(
            "添加控件必须针对当前唯一选中的控件，不能通过文字点名其他控件"
        )
    attributes = json_data.get("a")
    snapshot = (
        attributes.get("layout.materials") if isinstance(attributes, dict) else None
    )
    if snapshot is None:
        raise RefineInputError("该画布缺少素材快照，无法添加控件")
    candidates = action.get("material_candidates")
    if not candidates:
        raise RefineInputError("缺少素材名称，请指定要添加的控件素材")
    seen = set()
    deduped = []
    for name in candidates:
        if name not in seen:
            seen.add(name)
            deduped.append(name)
    if len(deduped) > 1:
        raise RefineInputError(f"素材名称存在歧义，请重新指定：{'、'.join(deduped)}")
    candidate = deduped[0]
    material = next(
        (m for m in snapshot if m.get("displayName") == candidate), None
    )
    if material is None:
        raise RefineInputError(f"素材「{candidate}」不在该画布的素材快照中，无法添加")
    sides = action.get("sides")
    if isinstance(sides, str):
        sides = [sides]
    if not sides:
        raise RefineInputError("缺少放置方位，请指定左侧、右侧、上方或下方")
    ordered_sides = _normalize_sides(sides)

    anchor = controls[anchor_i]
    obstacles = [c for c in controls.values() if c.node_i != anchor_i]
    safe = content_rect_of_canvas(canvas_width, canvas_height)
    base_width, base_height, source_width, source_height = resolve_control_size(
        candidate, material
    )

    if len(ordered_sides) == 1:
        side = ordered_sides[0]
        fit = _max_fit_scale(
            anchor,
            side,
            base_width,
            base_height,
            safe,
            canvas_width,
            canvas_height,
            obstacles,
        )
        if fit is None:
            raise RefineInputError("没有足够的空间放置新控件，请尝试其他方位或缩小画布")
        placements = [(side, fit)]
    else:
        fits = []
        for side in ordered_sides:
            fit = _max_fit_scale(
                anchor,
                side,
                base_width,
                base_height,
                safe,
                canvas_width,
                canvas_height,
                obstacles,
            )
            if fit is None:
                raise RefineInputError(
                    "没有足够的空间放置新控件，请尝试其他方位或缩小画布"
                )
            fits.append((side, fit))
        percent = min(fit[0] for _, fit in fits)
        placements = []
        for side, _ in fits:
            width = base_width * percent / 100
            height = base_height * percent / 100
            x, y = _place_at(anchor, side, width, height)
            placements.append((side, (percent, x, y, width, height)))

    final_placements = []
    for side, (percent, x, y, width, height) in placements:
        rx = _round2(x)
        ry = _round2(y)
        rw = _round2(width)
        rh = _round2(height)
        if not _verify_placement(
            rx,
            ry,
            rw,
            rh,
            anchor,
            side,
            safe,
            canvas_width,
            canvas_height,
            obstacles,
        ):
            raise RefineInputError("没有足够的空间放置新控件，请尝试其他方位或缩小画布")
        final_placements.append((side, percent, rx, ry, rw, rh))

    entries = json_data.get("d")
    max_i = 0
    for item in entries if isinstance(entries, list) else []:
        node_i = item.get("i")
        if isinstance(node_i, int) and not isinstance(node_i, bool) and node_i > max_i:
            max_i = node_i
    used_names = {
        str(item.get("p", {}).get("displayName") or "")
        for item in entries
        if isinstance(item, dict) and isinstance(item.get("p"), dict)
    }
    anchor_item = next(
        (item for item in entries if item.get("i") == anchor_i),
        None,
    )
    anchor_a = (
        anchor_item.get("a")
        if anchor_item is not None and isinstance(anchor_item.get("a"), dict)
        else {}
    )
    group = anchor_a.get("layout.group") or f"refine_group_{anchor_i}"
    instance = anchor_a.get("layout.instance")
    if not isinstance(instance, int) or isinstance(instance, bool):
        instance = 1
    image = str(material.get("image") or "") or f"symbols/Agent/{candidate}.json"
    material_name = str(material.get("displayName") or candidate)

    nodes = []
    for index, (side, percent, x, y, width, height) in enumerate(final_placements):
        new_i = max_i + 1 + index
        display_name = _unique_add_name(candidate, used_names)
        nodes.append(
            {
                "c": "ht.Node",
                "i": new_i,
                "p": {
                    "displayName": display_name,
                    "image": image,
                    "position": {"x": x, "y": y},
                    "width": width,
                    "height": height,
                },
                "a": {
                    "layout.group": group,
                    "layout.node": f"refine_{new_i}",
                    "layout.instance": instance,
                    "layout.materialName": material_name,
                    "layout.sourceWidth": _round2(source_width),
                    "layout.sourceHeight": _round2(source_height),
                },
            }
        )

    flat = [
        {
            "x": control.x,
            "y": control.y,
            "width": control.width,
            "height": control.height,
        }
        for control in controls.values()
    ]
    for side, percent, x, y, width, height in final_placements:
        flat.append({"x": x, "y": y, "width": width, "height": height})
    new_rect = content_rect_of_nodes(flat)

    patch = [
        {"op": "add", "path": "/d/-", "value": node} for node in nodes
    ]
    rect_op = "replace" if "contentRect" in json_data else "add"
    patch.append({"op": rect_op, "path": "/contentRect", "value": new_rect})
    _validate_patch(patch, controls, labels, allow_content_rect=True)

    if len(final_placements) == 1:
        side_label = _SIDE_NAMES[final_placements[0][0]]
        message = (
            f"已在锚点控件{side_label}添加「{material_name}」"
            f"（{final_placements[0][4]}×{final_placements[0][5]}，"
            f"缩放 {final_placements[0][1]}%）"
        )
    else:
        side_pair = tuple(side for side, *_ in final_placements)
        if side_pair == ("left", "right"):
            sides_label = "左右两侧"
        else:
            sides_label = "上下两侧"
        message = (
            f"已在锚点控件{sides_label}各添加一个「{material_name}」"
            f"（{final_placements[0][4]}×{final_placements[0][5]}，"
            f"缩放 {final_placements[0][1]}%）"
        )
    return RefineResult(patch=patch, message=message)


def _apply_actions(
    actions: list[dict[str, Any]],
    controls: dict[int, _ControlGeometry],
    labels: dict[int, _LabelInfo],
    canvas_width: Any,
    canvas_height: Any,
    catalog: list[dict[str, Any]],
) -> None:
    for action in actions:
        target_ids = action["target_ids"]
        targets = [controls[node_i] for node_i in target_ids]
        action_type = action["type"]

        if action_type == "add_label":
            text_map = _make_label_map(action, controls, catalog)
            for node_i in target_ids:
                control = controls[node_i]
                control.label_value = text_map[node_i]
                existing = labels.get(node_i)
                if existing is not None:
                    existing.deleted = True
            continue

        if action_type == "move":
            for control in targets:
                if "x" in action:
                    control.x = action["x"]
                elif "dx" in action:
                    control.x += action["dx"]
                if "y" in action:
                    control.y = action["y"]
                elif "dy" in action:
                    control.y += action["dy"]
        elif action_type == "resize":
            for control in targets:
                if control.aspect is None:
                    raise RefineInputError(
                        f"control {control.node_i} has no material size metadata, cannot enforce ratio"
                    )
                if "scale" in action:
                    control.width *= action["scale"]
                    control.height *= action["scale"]
                elif "width" in action and "height" in action:
                    control.width, control.height = inscribe_ratio(
                        action["width"], action["height"], control.aspect
                    )
                elif "width" in action:
                    control.width = action["width"]
                    control.height = control.width / control.aspect
                else:
                    control.height = action["height"]
                    control.width = control.height * control.aspect
        elif action_type == "delete":
            for control in targets:
                control.deleted = True
                if control.node_i in labels:
                    labels[control.node_i].deleted = True
            continue
        elif action_type == "swap":
            first, second = targets
            first.x, second.x = second.x, first.x
            first.y, second.y = second.y, first.y
        elif action_type == "align":
            _align(targets, action["alignment"])
        else:
            _distribute(targets, action["axis"])

        for control in targets:
            control.touched = True
            if action_type == "resize":
                _clamp_ratio_geometry(control, canvas_width, canvas_height)
            else:
                _clamp_geometry(control, canvas_width, canvas_height)
            if control.node_i in labels:
                _update_label_from_control(
                    labels[control.node_i], control, canvas_width, canvas_height
                )


def _validate_patch(
    patch: list[dict[str, Any]],
    controls: dict[int, _ControlGeometry],
    labels: dict[int, _LabelInfo],
    allow_content_rect: bool = False,
) -> None:
    allowed_paths: set[str] = set()
    remove_paths: set[str] = set()
    if allow_content_rect:
        allowed_paths.add("/contentRect")
    for control in controls.values():
        prefix = f"/d/{control.index}/p"
        allowed_paths.update(
            {
                f"{prefix}/position/x",
                f"{prefix}/position/y",
                f"{prefix}/width",
                f"{prefix}/height",
            }
        )
        remove_paths.add(f"/d/{control.index}")
        if control.label_value is not None and not control.deleted:
            sprefix = f"/d/{control.index}/s"
            if not control.has_s:
                allowed_paths.add(sprefix)
            allowed_paths.update(
                {
                    f"{sprefix}/label",
                    f"{sprefix}/label.color",
                    f"{sprefix}/label.font",
                }
            )

    for label in labels.values():
        if label.index < 0:
            continue
        prefix = f"/d/{label.index}/p"
        allowed_paths.update(
            {
                f"{prefix}/position/x",
                f"{prefix}/position/y",
                f"{prefix}/width",
                f"{prefix}/height",
            }
        )
        allowed_paths.add(f"/d/{label.index}/s/text")
        remove_paths.add(f"/d/{label.index}")

    for operation in patch:
        op = operation.get("op")
        path = operation.get("path")
        if op == "remove":
            if set(operation) != {"op", "path"} or path not in remove_paths:
                raise RefineModelError("generated patch contains an invalid remove")
            continue
        if op == "add" and path == "/d/-":
            value = operation.get("value")
            if not isinstance(value, dict) or set(operation) != {"op", "path", "value"}:
                raise RefineModelError("generated /d/- add must have an object value")
            continue
        if path == "/contentRect":
            if (
                set(operation) != {"op", "path", "value"}
                or op not in {"add", "replace"}
                or not isinstance(operation["value"], dict)
            ):
                raise RefineModelError("generated contentRect patch must be an object")
            continue
        if (
            set(operation) != {"op", "path", "value"}
            or not isinstance(path, str)
            or path not in allowed_paths
            or op not in {"add", "replace"}
        ):
            raise RefineModelError("generated patch contains an invalid operation")
        if "/position/" in path and op != "replace":
            raise RefineModelError("generated position patch must use replace")
        if path != "/d/-" and not _is_finite_number(operation["value"]):
            if "/s" not in path:
                raise RefineModelError("generated patch contains an invalid number")
        if path.endswith("/s") and path != "/d/-":
            value = operation.get("value")
            if (
                op != "add"
                or not isinstance(value, dict)
                or set(value) != set(_LABEL_FIELD_KEYS)
                or value.get("label.color") != _LABEL_COLOR
                or value.get("label.font") != _LABEL_FONT
                or not isinstance(value.get("label"), str)
            ):
                raise RefineModelError(
                    "generated first-time style add must contain the three label fields"
                )


def _compile_patch(
    controls: dict[int, _ControlGeometry],
    labels: dict[int, _LabelInfo],
) -> list[dict[str, Any]]:
    patch: list[dict[str, Any]] = []
    ordered = sorted(controls.values(), key=lambda control: control.index)
    for control in ordered:
        if control.deleted:
            continue
        prefix = f"/d/{control.index}/p"
        if control.touched:
            if control.x != control.original_x:
                patch.append(
                    {
                        "op": "replace",
                        "path": f"{prefix}/position/x",
                        "value": control.x,
                    }
                )
            if control.y != control.original_y:
                patch.append(
                    {
                        "op": "replace",
                        "path": f"{prefix}/position/y",
                        "value": control.y,
                    }
                )
            size_changed = control.width != control.original_width or control.height != control.original_height
            if size_changed:
                patch.append(
                    {
                        "op": "replace" if control.has_width else "add",
                        "path": f"{prefix}/width",
                        "value": control.width,
                    }
                )
                patch.append(
                    {
                        "op": "replace" if control.has_height else "add",
                        "path": f"{prefix}/height",
                        "value": control.height,
                    }
                )
        if control.label_value is not None:
            sprefix = f"/d/{control.index}/s"
            if not control.has_s:
                patch.append(
                    {
                        "op": "add",
                        "path": sprefix,
                        "value": {
                            "label": control.label_value,
                            "label.color": _LABEL_COLOR,
                            "label.font": _LABEL_FONT,
                        },
                    }
                )
            else:
                s = control.s_value if isinstance(control.s_value, dict) else {}
                for key, value in (
                    ("label", control.label_value),
                    ("label.color", _LABEL_COLOR),
                    ("label.font", _LABEL_FONT),
                ):
                    if s.get(key) != value:
                        patch.append(
                            {
                                "op": "add" if key not in s else "replace",
                                "path": f"{sprefix}/{key}",
                                "value": value,
                            }
                        )

    for label in labels.values():
        if label.deleted or not label.touched or label.index < 0:
            continue
        prefix = f"/d/{label.index}"
        patch.append(
            {
                "op": "replace",
                "path": f"{prefix}/s/text",
                "value": label.text,
            }
        )
        pprefix = f"{prefix}/p"
        patch.append(
            {
                "op": "replace",
                "path": f"{pprefix}/position/x",
                "value": label.x,
            }
        )
        patch.append(
            {
                "op": "replace",
                "path": f"{pprefix}/position/y",
                "value": label.y,
            }
        )
        patch.append(
            {
                "op": "replace",
                "path": f"{pprefix}/width",
                "value": label.width,
            }
        )
        patch.append(
            {
                "op": "replace",
                "path": f"{pprefix}/height",
                "value": label.height,
            }
        )

    deleted_indexes: list[int] = sorted(
        (
            control.index
            for control in controls.values()
            if control.deleted
        ),
        reverse=True,
    )
    deleted_indexes.extend(
        sorted(
            (
                label.index
                for label in labels.values()
                if label.deleted and label.index >= 0
            ),
            reverse=True,
        )
    )
    deleted_indexes.sort(reverse=True)
    patch.extend(
        {"op": "remove", "path": f"/d/{index}"} for index in deleted_indexes
    )

    _validate_patch(patch, controls, labels)
    return patch


class RefineAgent:
    def __init__(self, client=None, model=None):
        self._client = client if client is not None else default_client
        self._model = model if model is not None else default_model

    async def refine(
        self,
        instruction: str,
        json_data: dict[str, Any],
        selected_node_i: Optional[int] = None,
        selected_node_ids: Optional[list[int]] = None,
    ) -> RefineResult:
        if not isinstance(instruction, str):
            raise RefineInputError("instruction must be a string")
        instruction = instruction.strip()
        if not instruction:
            raise RefineInputError("instruction must not be empty")
        canvas_width, canvas_height, controls, catalog, labels = _read_layout(
            json_data
        )
        if selected_node_i is not None and (
            isinstance(selected_node_i, bool)
            or not isinstance(selected_node_i, int)
            or selected_node_i not in controls
        ):
            raise RefineInputError("selected control must be editable")
        if selected_node_ids is not None:
            for nid in selected_node_ids:
                if nid not in controls:
                    raise RefineInputError(f"selected node {nid} is not editable")
        normalized_selection: tuple[int, ...]
        if selected_node_ids is not None:
            normalized_selection = tuple(selected_node_ids)
        elif selected_node_i is not None:
            normalized_selection = (selected_node_i,)
        else:
            normalized_selection = ()
        if self._client is None or not self._model:
            raise RefineUnavailableError("refine model is unavailable")

        attributes = json_data.get("a")
        materials = (
            attributes.get("layout.materials")
            if isinstance(attributes, dict)
            and isinstance(attributes.get("layout.materials"), list)
            else None
        )
        prompt = _build_prompt(
            canvas_width,
            canvas_height,
            catalog,
            normalized_selection,
            materials,
        )
        try:
            response = await call_llm(
                self._client,
                self._model,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": instruction},
                ],
                response_format={"type": "json_object"},
            )
        except Exception as exc:
            raise RefineModelError("refine model call failed") from exc

        data = _response_data(response)
        known_ids = set(controls)
        _validate_model_data(data, known_ids)
        actions = data["actions"]
        if not actions:
            return RefineResult(patch=[], message=data["message"])

        has_add_control = any(
            isinstance(action, dict) and action.get("type") == "add_control"
            for action in actions
        )
        if has_add_control:
            _validate_snapshot_structure(json_data)
            try:
                return _apply_add_control(
                    actions,
                    json_data,
                    controls,
                    labels,
                    canvas_width,
                    canvas_height,
                    normalized_selection,
                )
            except RefineInputError as exc:
                return RefineResult(patch=[], message=str(exc))

        try:
            _apply_actions(
                actions,
                controls,
                labels,
                canvas_width,
                canvas_height,
                catalog,
            )
        except RefineInputError as exc:
            return RefineResult(patch=[], message=str(exc))

        return RefineResult(
            patch=_compile_patch(controls, labels),
            message=data["message"],
        )
