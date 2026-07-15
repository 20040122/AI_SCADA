from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Optional

from model.canva_agent import _client, _MODEL, _call_llm


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


def _read_layout(
    json_data: dict[str, Any],
) -> tuple[Any, Any, dict[int, _ControlGeometry], list[dict[str, Any]]]:
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
    return canvas_width, canvas_height, controls, catalog


def _build_prompt(
    canvas_width: Any,
    canvas_height: Any,
    catalog: list[dict[str, Any]],
    selected_node_i: Optional[int],
) -> str:
    selected = "none" if selected_node_i is None else str(selected_node_i)
    catalog_json = json.dumps(catalog, ensure_ascii=False, indent=2)
    return f"""You refine an interactive SCADA canvas by returning semantic actions.
Canvas width: {canvas_width}
Canvas height: {canvas_height}
Selected control ID: {selected}
Control catalog with stable IDs and current geometry:
{catalog_json}

Use the selected ID for local commands that refer to the current selection.
Resolve explicitly named controls from the catalog.
Include all intended IDs for global commands.
Never guess an ambiguous target.
When a local command has no selected or explicit target, return empty actions and a clarifying message.
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
Allowed alignments: left, right, top, bottom, center_x, center_y.
Allowed distribution axes: horizontal, vertical.
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


def _apply_actions(
    actions: list[dict[str, Any]],
    controls: dict[int, _ControlGeometry],
    canvas_width: Any,
    canvas_height: Any,
) -> None:
    for action in actions:
        targets = [controls[node_i] for node_i in action["target_ids"]]
        action_type = action["type"]
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
                if "scale" in action:
                    control.width *= action["scale"]
                    control.height *= action["scale"]
                else:
                    if "width" in action:
                        control.width = action["width"]
                    if "height" in action:
                        control.height = action["height"]
        elif action_type == "delete":
            for control in targets:
                control.deleted = True
            continue
        elif action_type == "align":
            _align(targets, action["alignment"])
        else:
            _distribute(targets, action["axis"])

        for control in targets:
            control.touched = True
            _clamp_geometry(control, canvas_width, canvas_height)


def _validate_patch(
    patch: list[dict[str, Any]], controls: dict[int, _ControlGeometry]
) -> None:
    geometry_paths = set()
    remove_paths = set()
    for control in controls.values():
        prefix = f"/d/{control.index}/p"
        geometry_paths.update(
            {
                f"{prefix}/position/x",
                f"{prefix}/position/y",
                f"{prefix}/width",
                f"{prefix}/height",
            }
        )
        remove_paths.add(f"/d/{control.index}")

    for operation in patch:
        op = operation.get("op")
        path = operation.get("path")
        if op == "remove":
            if set(operation) != {"op", "path"} or path not in remove_paths:
                raise RefineModelError("generated patch contains an invalid remove")
            continue
        if (
            set(operation) != {"op", "path", "value"}
            or not isinstance(path, str)
            or path not in geometry_paths
            or op not in {"add", "replace"}
        ):
            raise RefineModelError("generated patch contains an invalid operation")
        if "/position/" in path and op != "replace":
            raise RefineModelError("generated position patch must use replace")
        if not _is_finite_number(operation["value"]):
            raise RefineModelError("generated patch contains an invalid number")


def _compile_patch(
    controls: dict[int, _ControlGeometry],
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
        if control.width != control.original_width:
            patch.append(
                {
                    "op": "replace" if control.has_width else "add",
                    "path": f"{prefix}/width",
                    "value": control.width,
                }
            )
        if control.height != control.original_height:
            patch.append(
                {
                    "op": "replace" if control.has_height else "add",
                    "path": f"{prefix}/height",
                    "value": control.height,
                }
            )
    deleted_indexes = sorted(
        (control.index for control in controls.values() if control.deleted),
        reverse=True,
    )
    patch.extend(
        {"op": "remove", "path": f"/d/{index}"} for index in deleted_indexes
    )
    _validate_patch(patch, controls)
    return patch


class RefineAgent:
    def __init__(self, client=None, model=None):
        self._client = client if client is not None else _client
        self._model = model if model is not None else _MODEL

    async def refine(
        self,
        instruction: str,
        json_data: dict[str, Any],
        selected_node_i: Optional[int] = None,
    ) -> RefineResult:
        if not isinstance(instruction, str):
            raise RefineInputError("instruction must be a string")
        instruction = instruction.strip()
        if not instruction:
            raise RefineInputError("instruction must not be empty")
        canvas_width, canvas_height, controls, catalog = _read_layout(json_data)
        if selected_node_i is not None and (
            isinstance(selected_node_i, bool)
            or not isinstance(selected_node_i, int)
            or selected_node_i not in controls
        ):
            raise RefineInputError("selected control must be editable")
        if self._client is None or not self._model:
            raise RefineUnavailableError("refine model is unavailable")

        prompt = _build_prompt(
            canvas_width,
            canvas_height,
            catalog,
            selected_node_i,
        )
        try:
            response = await _call_llm(
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
        _validate_model_data(data, set(controls))
        actions = data["actions"]
        if not actions:
            return RefineResult(patch=[], message=data["message"])
        _apply_actions(actions, controls, canvas_width, canvas_height)
        return RefineResult(
            patch=_compile_patch(controls),
            message=data["message"],
        )
