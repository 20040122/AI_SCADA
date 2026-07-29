from dataclasses import dataclass
import re
from typing import Optional


@dataclass
class RuleLayoutResult:
    data: Optional[dict]
    fallback_reason: Optional[str]


def _region(text: str, device_type: str) -> Optional[str]:
    start = text.find(device_type)
    if start < 0:
        return None
    fragment = re.split(r"[；。]", text[start:], maxsplit=1)[0]
    if "左侧" in fragment:
        return "left"
    if "右侧" in fragment:
        return "right"
    if "中部" in fragment or "中央" in fragment:
        return "center"
    return None


def _arrangement(text: str, device_type: str) -> Optional[str]:
    start = text.find(device_type)
    if start < 0:
        return None
    fragment = re.split(r"[；。]", text[start:], maxsplit=1)[0]
    if "纵向" in fragment:
        return "vertical"
    if "横向" in fragment:
        return "horizontal"
    if "网格" in fragment or "矩阵" in fragment:
        return "grid"
    return None


def _has_complex_topology(structure: str) -> bool:
    strong = ["泵1", "泵2", "从上和下", "连接同一个"]
    if any(kw in structure for kw in strong):
        return True
    numbered = len(re.findall(r"\d+号", structure))
    if numbered >= 2 and "分别" in structure:
        return True
    return False


def _build_complex_groups(source) -> Optional[dict]:
    groups = []
    previous_id = None
    flow_paths = source.flowPaths
    if not flow_paths:
        return None
    flat_order = flow_paths[0]
    device_map = {}
    for item in source.inventory:
        device_map[item.deviceType] = item
    ordered_devices = []
    for device_type in flat_order:
        if device_type in device_map and device_type not in ordered_devices:
            ordered_devices.append(device_type)
    remaining = [d for d in device_map if d not in ordered_devices]
    for device_type in remaining:
        if device_type not in ordered_devices:
            ordered_devices.append(device_type)
    for index, device_type in enumerate(ordered_devices, start=1):
        item = device_map[device_type]
        group = {
            "id": "group-%d" % index,
            "region": "center",
            "count": item.count,
            "unit": {"root": {"id": "root", "deviceType": item.deviceType}},
        }
        if previous_id is not None:
            group["relativeTo"] = previous_id
            group["side"] = "right"
        groups.append(group)
        previous_id = group["id"]
    return {"layoutIntent": {"groups": groups}}


def _has_region_or_arrangement(text: str, device_type: str) -> bool:
    start = text.find(device_type)
    if start < 0:
        return False
    fragment = re.split(r"[；。]", text[start:], maxsplit=1)[0]
    return any(kw in fragment for kw in ("左侧", "右侧", "中部", "中央", "纵向", "横向"))


def build_rule_layout(source) -> RuleLayoutResult:
    structure = source.structure
    if _has_complex_topology(structure):
        data = _build_complex_groups(source)
        if data is not None:
            return RuleLayoutResult(data, None)
        return RuleLayoutResult(None, "complex_topology_no_flow")
    if not any(_has_region_or_arrangement(structure, item.deviceType) for item in source.inventory):
        return RuleLayoutResult(None, "unsupported_structure")
    groups = []
    group_by_device = {}
    previous_id = None
    previous_region = None
    region_rank = {"left": 0, "center": 1, "right": 2}
    for index, item in enumerate(source.inventory, start=1):
        region = _region(structure, item.deviceType)
        if region is None:
            return RuleLayoutResult(None, "unsupported_structure")
        if previous_region is not None and region_rank[region] < region_rank[previous_region]:
            return RuleLayoutResult(None, "conflicting_region_order")
        arrangement = _arrangement(structure, item.deviceType)
        group = {
            "id": "group-%d" % index,
            "region": region,
            "count": item.count,
            "topology": "parallel" if item.deviceType in source.parallelDevices else "single",
            "unit": {"root": {"id": "root", "deviceType": item.deviceType}},
        }
        if arrangement is not None:
            group["arrangement"] = arrangement
        if previous_id is not None:
            group["relativeTo"] = previous_id
            group["side"] = "right"
        groups.append(group)
        group_by_device[item.deviceType] = group["id"]
        previous_id = group["id"]
        previous_region = region
    return RuleLayoutResult({"layoutIntent": {"groups": groups}}, None)
