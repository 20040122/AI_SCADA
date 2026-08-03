from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Optional

from model.layout_tools.geometry import inscribe_ratio
from model.llm_client import default_client, default_model, call_llm


_DEFAULT_WIDTH = 60
_DEFAULT_HEIGHT = 40
_ALIGNMENTS = {"left", "right", "top", "bottom", "center_x", "center_y"}
_DISTRIBUTION_AXES = {"horizontal", "vertical"}
_ACTION_FIELDS = {
    "move": {"type", "target_ids", "dx", "dy", "x", "y"},
    "resize": {"type", "target_ids", "scale", "width", "height"},
    "delete": {"type", "target_ids"},
    "align": {"type", "target_ids", "alignment"},
    "distribute": {"type", "target_ids", "axis"},
    "add_label": {"type", "target_ids", "text", "names"},
}


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
    int,
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
    all_node_is: set[int] = set()
    control_node_is: set[int] = set()

    for item in entries:
        if isinstance(item, dict):
            node_i = item.get("i")
            if isinstance(node_i, int) and not isinstance(node_i, bool):
                all_node_is.add(node_i)

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

    max_node_i = max(all_node_is) if all_node_is else -1

    return canvas_width, canvas_height, controls, catalog, labels, max_node_i


def _build_prompt(
    canvas_width: Any,
    canvas_height: Any,
    catalog: list[dict[str, Any]],
    selected_node_ids: tuple[int, ...],
) -> str:
    selected = "none" if not selected_node_ids else ",".join(str(i) for i in selected_node_ids)
    catalog_json = json.dumps(catalog, ensure_ascii=False, indent=2)
    return f"""You refine an interactive SCADA canvas by returning semantic actions.
Canvas width: {canvas_width}
Canvas height: {canvas_height}
Selected control ID(s): {selected}
Control catalog with stable IDs and current geometry:
{catalog_json}

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
{{"type":"add_label","target_ids":[12]}}
{{"type":"add_label","target_ids":[12],"text":"入口阀"}}
{{"type":"add_label","target_ids":[12,13],"text":"阀门"}}
{{"type":"add_label","target_ids":[12,13],"names":{{12:"入口阀",13:"出口阀"}}}}
Allowed alignments: left, right, top, bottom, center_x, center_y.
Allowed distribution axes: horizontal, vertical.
For naming: text and names are mutually exclusive; without either, each control uses its own displayName.
Do not add fields outside the selected action schema."""


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
    elif action_type == "add_label":
        known_set = set(known_ids)
        if "text" in action and "names" in action:
            raise RefineModelError("add_label cannot have both text and names")
        if "names" in action:
            names = action["names"]
            if not isinstance(names, dict):
                raise RefineModelError("add_label names must be an object")
            for name_key, name_value in names.items():
                if isinstance(name_key, bool) or not isinstance(name_key, int):
                    raise RefineModelError("add_label names keys must be integers")
                if not isinstance(name_value, str):
                    raise RefineModelError("add_label names values must be strings")
                if name_key not in known_set:
                    raise RefineModelError(
                        f"add_label names references unknown ID {name_key}"
                    )


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


def _build_label_json(label: _LabelInfo) -> dict[str, Any]:
    return {
        "c": "ht.Text",
        "i": label.node_i,
        "p": {
            "position": {"x": label.x, "y": label.y},
            "width": label.width,
            "height": label.height,
            "tall": 20,
        },
        "s": {
            "text": label.text,
            "text.font": "bold 20px Arial",
            "text.color": "white",
            "text.align": "center",
            "opacity": 1,
            "layout.v": "top",
        },
        "a": {
            "layout.role": "control-label",
            "layout.labelFor": label.label_for,
        },
    }


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

    if "names" in action:
        names = action["names"]
        result: dict[int, str] = {}
        for node_i in target_ids:
            if node_i not in names:
                raise RefineInputError(
                    f"add_label names missing entry for control {node_i}"
                )
            result[node_i] = _validate_label_text(names[node_i])
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


def _apply_actions(
    actions: list[dict[str, Any]],
    controls: dict[int, _ControlGeometry],
    labels: dict[int, _LabelInfo],
    new_labels: list[_LabelInfo],
    max_node_i: int,
    canvas_width: Any,
    canvas_height: Any,
    catalog: list[dict[str, Any]],
) -> int:
    next_node_i = max_node_i + 1

    for action in actions:
        target_ids = action["target_ids"]
        targets = [controls[node_i] for node_i in target_ids]
        action_type = action["type"]

        if action_type == "add_label":
            text_map = _make_label_map(action, controls, catalog)
            for node_i in target_ids:
                text = text_map[node_i]
                control = controls[node_i]
                _validate_label_text(text)

                existing = labels.get(node_i)
                if existing is not None:
                    existing.text = text
                    _update_label_from_control(
                        existing, control, canvas_width, canvas_height
                    )
                else:
                    width, height, x, y = _compute_label_geometry(
                        control, text, canvas_width, canvas_height
                    )
                    new_label = _LabelInfo(
                        node_i=next_node_i,
                        index=-1,
                        label_for=node_i,
                        x=x,
                        y=y,
                        width=width,
                        height=height,
                        text=text,
                        touched=True,
                    )
                    labels[node_i] = new_label
                    new_labels.append(new_label)
                    next_node_i += 1
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

    return next_node_i


def _validate_patch(
    patch: list[dict[str, Any]],
    controls: dict[int, _ControlGeometry],
    labels: dict[int, _LabelInfo],
) -> None:
    allowed_paths: set[str] = set()
    remove_paths: set[str] = set()
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
            if "s/text" not in path:
                raise RefineModelError("generated patch contains an invalid number")


def _compile_patch(
    controls: dict[int, _ControlGeometry],
    labels: dict[int, _LabelInfo],
    new_labels: list[_LabelInfo],
) -> list[dict[str, Any]]:
    patch: list[dict[str, Any]] = []
    ordered = sorted(controls.values(), key=lambda control: control.index)
    for control in ordered:
        if control.deleted or not control.touched:
            continue
        prefix = f"/d/{control.index}/p"
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

    for label in new_labels:
        if not label.touched:
            continue
        patch.append(
            {
                "op": "add",
                "path": "/d/-",
                "value": _build_label_json(label),
            }
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
        canvas_width, canvas_height, controls, catalog, labels, max_node_i = _read_layout(
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

        prompt = _build_prompt(
            canvas_width,
            canvas_height,
            catalog,
            normalized_selection,
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

        new_labels: list[_LabelInfo] = []
        try:
            _apply_actions(
                actions,
                controls,
                labels,
                new_labels,
                max_node_i,
                canvas_width,
                canvas_height,
                catalog,
            )
        except RefineInputError as exc:
            return RefineResult(patch=[], message=str(exc))

        return RefineResult(
            patch=_compile_patch(controls, labels, new_labels),
            message=data["message"],
        )
