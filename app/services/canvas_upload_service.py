from __future__ import annotations

import copy
import json
import math
import re
from pathlib import Path
from typing import Any, Optional

import httpx

from app.config import settings
from model.layout_agent import _schema_validate
from model.layout_tools.geometry import content_rect_of_nodes, inscribe_ratio, round2
from model.layout_tools.pipe_serializer import is_managed_pipe_edge, next_edge_i, serialize_pipes


class UploadBlockedError(ValueError):
    pass


class UploadUpstreamError(RuntimeError):
    pass


class UploadTimeoutError(RuntimeError):
    pass


class UploadResult:
    def __init__(self, json_data: dict, corrections: list[dict], warnings: list[str]) -> None:
        self.json_data = json_data
        self.corrections = corrections
        self.warnings = warnings


def _validate_file_name(file_name: str) -> None:
    if not isinstance(file_name, str) or not file_name:
        raise UploadBlockedError("file_name must be a non-empty string")
    if file_name != Path(file_name).name:
        raise UploadBlockedError("file_name must not contain path separators")
    if not file_name.lower().endswith(".json"):
        raise UploadBlockedError("file_name must end with .json")


def _positive_number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def _metadata_ratio(attrs: Any) -> Optional[float]:
    if not isinstance(attrs, dict):
        return None
    source_w = _positive_number(attrs.get("layout.sourceWidth"))
    source_h = _positive_number(attrs.get("layout.sourceHeight"))
    if source_w is None or source_h is None:
        return None
    return source_w / source_h


def _library_ratio_index(library: list[dict]) -> dict[tuple[str, str], set[float]]:
    index: dict[tuple[str, str], set[float]] = {}
    for entry in library:
        name = str(entry.get("displayName") or "")
        image = str(entry.get("image") or "")
        width = _positive_number(entry.get("width"))
        height = _positive_number(entry.get("height"))
        if not name or width is None or height is None:
            continue
        index.setdefault((name, image), set()).add(width / height)
    return index


def _resolve_ratio(attrs: Any, display_name: str, image: str, index: dict[tuple[str, str], set[float]]) -> Optional[float]:
    metadata_ratio = _metadata_ratio(attrs)
    if metadata_ratio is not None:
        return metadata_ratio
    ratios = index.get((display_name, image))
    if ratios is not None and len(ratios) == 1:
        return next(iter(ratios))
    match = re.match(r"^(.*?)(\d+)$", display_name)
    if match:
        ratios = index.get((match.group(1), image))
        if ratios is not None and len(ratios) == 1:
            return next(iter(ratios))
    return None


def _rects_overlap(a: dict, b: dict, eps: float = 1e-6) -> bool:
    ax0, ay0 = a["x"] - a["width"] / 2, a["y"] - a["height"] / 2
    ax1, ay1 = ax0 + a["width"], ay0 + a["height"]
    bx0, by0 = b["x"] - b["width"] / 2, b["y"] - b["height"] / 2
    bx1, by1 = bx0 + b["width"], by0 + b["height"]
    return ax0 < bx1 - eps and bx0 < ax1 - eps and ay0 < by1 - eps and by0 < ay1 - eps


def _overlap_area(a: dict, b: dict) -> float:
    ax0, ay0 = a["x"] - a["width"] / 2, a["y"] - a["height"] / 2
    ax1, ay1 = ax0 + a["width"], ay0 + a["height"]
    bx0, by0 = b["x"] - b["width"] / 2, b["y"] - b["height"] / 2
    bx1, by1 = bx0 + b["width"], by0 + b["height"]
    width = min(ax1, bx1) - max(ax0, bx0)
    height = min(ay1, by1) - max(ay0, by0)
    if width <= 0 or height <= 0:
        return 0.0
    return width * height


def _collect_controls(json_data: dict) -> list[dict]:
    controls: list[dict] = []
    for item in json_data.get("d") or []:
        if not isinstance(item, dict):
            continue
        attrs = item.get("a") or {}
        if attrs.get("layout.node") is None:
            continue
        props = item.get("p") or {}
        position = props.get("position") or {}
        controls.append(
            {
                "item": item,
                "node_i": item.get("i"),
                "display_name": str(props.get("displayName") or ""),
                "image": str(props.get("image") or ""),
                "x": position.get("x"),
                "y": position.get("y"),
                "width": props.get("width"),
                "height": props.get("height"),
                "attrs": attrs,
            }
        )
    return controls


def _collect_labels(json_data: dict) -> dict[int, dict]:
    labels: dict[int, dict] = {}
    for item in json_data.get("d") or []:
        if not isinstance(item, dict):
            continue
        attrs = item.get("a") or {}
        if attrs.get("layout.role") != "control-label":
            continue
        label_for = attrs.get("layout.labelFor")
        if not isinstance(label_for, int):
            continue
        labels[label_for] = item
    return labels


def _label_geometry(control: dict, text: str, canvas_w: float, canvas_h: float) -> Optional[dict]:
    label_height = 32.0
    text_width = len(text) * 20 + 16
    label_width = max(control["width"], float(text_width))
    if label_width > canvas_w:
        return None
    label_x = min(max(control["x"], label_width / 2), canvas_w - label_width / 2)
    gap = 8.0
    above_y = control["y"] - control["height"] / 2 - gap - label_height / 2
    if above_y - label_height / 2 >= 0:
        label_y = above_y
    else:
        below_y = control["y"] + control["height"] / 2 + gap + label_height / 2
        if below_y + label_height / 2 <= canvas_h:
            label_y = below_y
        else:
            return None
    return {"width": label_width, "height": label_height, "x": label_x, "y": label_y}


def _canvas_size(json_data: dict) -> tuple[float, float]:
    attrs = json_data.get("a") or {}
    width = _positive_number(attrs.get("width"))
    height = _positive_number(attrs.get("height"))
    if width is None or height is None:
        raise UploadBlockedError("json_data.a.width and json_data.a.height must be positive numbers")
    return width, height


class CanvasUploadService:
    def __init__(self, client: Optional[httpx.AsyncClient] = None) -> None:
        self._client = client

    async def _post(self, url: str, fields: dict, multipart: bool = False) -> httpx.Response:
        client = self._client
        owns_client = client is None
        if client is None:
            client = httpx.AsyncClient(timeout=settings.daoscada_upload_timeout)
        try:
            if multipart:
                return await client.post(url, files={name: (None, value) for name, value in fields.items()})
            return await client.post(url, data=fields)
        except httpx.TimeoutException as exc:
            raise UploadTimeoutError("DaoSCADA upload timed out") from exc
        except httpx.HTTPError as exc:
            raise UploadUpstreamError(f"DaoSCADA upload failed: {exc}") from exc
        finally:
            if owns_client and client is not None:
                await client.aclose()

    async def upload_canvas(self, file_name: str, json_data: dict, library: list[dict], pipe_data: Optional[dict] = None) -> UploadResult:
        _validate_file_name(file_name)
        out = copy.deepcopy(json_data)
        canvas_w, canvas_h = _canvas_size(out)
        controls = _collect_controls(out)
        labels = _collect_labels(out)
        index = _library_ratio_index(library)

        blocked: list[str] = []
        for control in controls:
            width = _positive_number(control["width"])
            height = _positive_number(control["height"])
            if width is None or height is None:
                blocked.append(
                    f"node {control['node_i']} {control['display_name']} {control['image']}: missing or non-positive size"
                )
                continue
            ratio = _resolve_ratio(control["attrs"], control["display_name"], control["image"], index)
            if ratio is None:
                blocked.append(
                    f"node {control['node_i']} {control['display_name']} {control['image']}: material ratio cannot be resolved"
                )
                continue
            control["width"] = width
            control["height"] = height
            control["_ratio"] = ratio
        if blocked:
            detail = "upload blocked, cannot determine material size/ratio: " + "; ".join(blocked)
            raise UploadBlockedError(detail)

        corrections: list[dict] = []
        for control in controls:
            item = control["item"]
            props = item["p"]
            before_w, before_h = control["width"], control["height"]
            new_w, new_h = inscribe_ratio(before_w, before_h, control["_ratio"])
            new_w, new_h = round2(new_w), round2(new_h)
            if new_w == before_w and new_h == before_h:
                continue
            control["width"] = new_w
            control["height"] = new_h
            props["width"] = new_w
            props["height"] = new_h
            corrections.append(
                {
                    "node_i": control["node_i"],
                    "display_name": control["display_name"],
                    "image": control["image"],
                    "before": {"width": before_w, "height": before_h},
                    "after": {"width": new_w, "height": new_h},
                }
            )
            label = labels.get(control["node_i"])
            if label is not None:
                text = str((label.get("s") or {}).get("text") or "")
                geometry = _label_geometry(control, text, canvas_w, canvas_h)
                if geometry is not None:
                    label["p"]["position"]["x"] = geometry["x"]
                    label["p"]["position"]["y"] = geometry["y"]
                    label["p"]["width"] = geometry["width"]
                    label["p"]["height"] = geometry["height"]

        corrected_controls = [
            {
                "x": control["x"],
                "y": control["y"],
                "width": control["width"],
                "height": control["height"],
            }
            for control in controls
        ]
        before_rects = [
            {"x": c["x"], "y": c["y"], "width": c["width"], "height": c["height"]}
            for c in controls
        ]
        warnings = self._collision_warnings(before_rects, corrected_controls)

        out["contentRect"] = content_rect_of_nodes(
            [{"x": c["x"], "y": c["y"], "width": c["width"], "height": c["height"]} for c in controls]
        )

        if pipe_data is not None:
            out["d"] = [item for item in out.get("d") or [] if not is_managed_pipe_edge(item)]
            edges = serialize_pipes(pipe_data, out["d"], next_edge_i(out["d"]))
            out["d"].extend(edges)

        schema_errors = await _schema_validate(out)
        if schema_errors:
            raise UploadBlockedError("json_data schema invalid: " + "; ".join(schema_errors))

        payload = json.dumps(out, ensure_ascii=False, indent=2)
        response = await self._post(
            settings.daoscada_upload_url,
            {
                "path": f"{settings.daoscada_target_dir}/{file_name}",
                "content": payload,
            },
            multipart=True,
        )
        if response.status_code >= 400:
            raise UploadUpstreamError(
                f"DaoSCADA rejected upload with status {response.status_code}: {response.text[:200]}"
            )
        return UploadResult(json_data=out, corrections=corrections, warnings=warnings)

    @staticmethod
    def _collision_warnings(before: list[dict], after: list[dict]) -> list[str]:
        before_pairs = set()
        before_areas: dict[tuple[int, int], float] = {}
        for i in range(len(before)):
            for j in range(i + 1, len(before)):
                if _rects_overlap(before[i], before[j]):
                    before_pairs.add((i, j))
                    before_areas[(i, j)] = _overlap_area(before[i], before[j])
        warnings: list[str] = []
        for i in range(len(after)):
            for j in range(i + 1, len(after)):
                if not _rects_overlap(after[i], after[j]):
                    continue
                pair = (i, j)
                area = _overlap_area(after[i], after[j])
                if pair not in before_pairs:
                    raise UploadBlockedError(
                        f"correction would create new overlap between controls {i} and {j}"
                    )
                if area > before_areas[pair] + 1e-6:
                    raise UploadBlockedError(
                        f"correction would enlarge overlap between controls {i} and {j}"
                    )
                warnings.append(f"controls {i} and {j} overlap")
        return warnings
