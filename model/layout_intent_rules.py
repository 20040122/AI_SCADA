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


def build_rule_layout(source) -> RuleLayoutResult:
    structure = source.structure
    requirements = source.requirements
    if not any(word in structure or word in requirements for word in ("左侧", "右侧", "中部", "纵向", "横向", "正交")):
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
        group = {"id": "group-%d" % index, "region": region, "count": item.count, "topology": "parallel" if item.deviceType in source.parallelDevices else "single", "unit": {"root": {"id": "root", "deviceType": item.deviceType}}}
        if previous_id is not None:
            group["relativeTo"] = previous_id
            group["side"] = "right"
        groups.append(group)
        group_by_device[item.deviceType] = group["id"]
        previous_id = group["id"]
        previous_region = region
    connections = []
    seen = set()
    for path in source.flowPaths:
        for source_type, target_type in zip(path, path[1:]):
            if (source_type, target_type) not in seen:
                seen.add((source_type, target_type))
                connections.append({"id": "flow-%d" % len(connections), "source": {"group": group_by_device[source_type], "node": "root"}, "target": {"group": group_by_device[target_type], "node": "root"}})
    return RuleLayoutResult({"layoutIntent": {"groups": groups, "connections": connections, "constraints": {"routeStyle": "orthogonal" if "正交" in requirements else None, "allowedDirections": ["horizontal", "vertical"] if "垂直" in requirements or "水平" in requirements else [], "equalSpacing": "等间距" in requirements, "alignRepeated": "对齐" in requirements, "consistentBranches": "结构一致" in requirements or "相同模板" in structure}}}, None)
