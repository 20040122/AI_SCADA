from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from model.layout_tools.geometry import fit_size


class MissingMaterialError(ValueError):
    pass


@dataclass
class _Limits:
    min_w: float
    min_h: float
    max_w: float
    max_h: float
    preferred_w: float
    preferred_h: float


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


def load_layout_config() -> LayoutConfig:
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


def resolve_role(
    device_type: str,
    is_root: bool,
    explicit_role: Optional[str] = None,
    config: Optional[LayoutConfig] = None,
) -> str:
    if config is None:
        config = load_layout_config()
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


def resolve_control_size(
    device_type: str,
    material: dict,
    is_root: bool = False,
    explicit_role: Optional[str] = None,
) -> tuple[float, float, float, float]:
    config = load_layout_config()
    role = resolve_role(device_type, is_root, explicit_role, config)
    entry = config.roles.get(role)
    if entry is None:
        entry = _DEFAULT_LAYOUT_CONFIG.roles["default"]
    limits = entry.limits
    raw_w = _number(material.get("width"), limits.preferred_w)
    raw_h = _number(material.get("height"), limits.preferred_h)
    if raw_w <= 0 or raw_h <= 0:
        raw_w = limits.preferred_w
        raw_h = limits.preferred_h
    width, height = fit_size(
        raw_w, raw_h, limits.min_w, limits.min_h, limits.max_w, limits.max_h
    )
    return width, height, raw_w, raw_h


def is_canvas_json(data: dict) -> bool:
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


def is_canvas_json_path(image: str) -> bool:
    if not image.lower().endswith(".json"):
        return False
    path = Path(image)
    candidates = (
        [path]
        if path.is_absolute()
        else [Path.cwd() / path, Path(__file__).resolve().parents[2] / path]
    )
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return False
        return is_canvas_json(data)
    return False


def is_control_material(control: dict) -> bool:
    if not isinstance(control, dict):
        return False
    if is_canvas_json(control):
        return False
    name = str(control.get("displayName") or "")
    if not name:
        return False
    image = str(control.get("image") or "")
    if image and is_canvas_json_path(image):
        return False
    return True


def material_map(controls: list[dict]) -> dict[str, dict]:
    result = {}
    for control in controls:
        if not is_control_material(control):
            continue
        name = str(control.get("displayName") or "")
        if name and name not in result:
            result[name] = control
    return result


def find_material(device_type: str, materials: dict[str, dict]) -> Optional[dict]:
    if device_type in materials:
        return materials[device_type]
    for name, material in materials.items():
        if device_type in name or name in device_type:
            return material
    return None


def match_material(device_type: str, materials: dict[str, dict]) -> dict:
    material = find_material(device_type, materials)
    if material is None:
        raise MissingMaterialError("query_results 缺少控件素材：" + device_type)
    return material


def _number(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
