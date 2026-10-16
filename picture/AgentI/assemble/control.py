import argparse
import json
import sqlite3
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


ROOT = Path(__file__).resolve().parent
UNKNOWN_SUFFIX = "unknow"


def load_query_results(db_path: Path) -> List[Dict[str, Any]]:
    if not db_path.is_file():
        raise ValueError("query_results 数据库不存在: {}".format(db_path))
    connection = None
    try:
        connection = sqlite3.connect("{}?mode=ro".format(db_path.resolve().as_uri()), uri=True)
        rows = connection.execute(
            "SELECT displayName, image, width, height FROM query_results ORDER BY displayName"
        ).fetchall()
    except sqlite3.Error as error:
        raise ValueError("无法读取 query_results 表: {}".format(error)) from error
    finally:
        if connection is not None:
            connection.close()

    materials = []
    seen = set()
    for row in rows:
        name = row[0]
        image = row[1]
        if not isinstance(name, str) or not name.strip():
            continue
        name = " ".join(name.split())
        if name in seen:
            continue
        seen.add(name)
        materials.append({
            "displayName": name,
            "image": image if isinstance(image, str) else "",
            "width": row[2] or 0,
            "height": row[3] or 0,
        })
    if not materials:
        raise ValueError("query_results 表为空，控件素材不可用: {}".format(db_path))
    return materials


def _strip_unknown(value: str) -> str:
    suffix = "({})".format(UNKNOWN_SUFFIX)
    if value.endswith(suffix):
        return value[:-len(suffix)].strip()
    return value


def match_material(value: str, materials: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(value, str) or not value.strip():
        return None
    name = " ".join(value.split())
    exact = {material["displayName"]: material for material in materials}
    if name in exact:
        return exact[name]
    name = _strip_unknown(name)
    if name in exact:
        return exact[name]
    contained = [
        material for material in materials
        if name and (name in material["displayName"] or material["displayName"] in name)
    ]
    if not contained:
        return None
    prefixed = [material for material in contained if material["displayName"].startswith(name)]
    return max(prefixed or contained, key=lambda material: len(material["displayName"]))


def convert_control_nodes(
    detections: List[Dict[str, Any]],
    template: Dict[str, Any],
    materials: List[Dict[str, Any]],
    start_id: Optional[int] = None,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    nodes = []
    unmatched = []
    next_id = template["i"] if start_id is None else start_id
    for item in detections:
        if item.get("type") not in ("control", "controls"):
            continue
        material = match_material(item.get("value"), materials)
        if material is None:
            unmatched.append(item.get("value"))
            continue
        node = deepcopy(template)
        node["i"] = next_id
        node["p"].update({
            "displayName": material["displayName"],
            "image": material["image"],
            "position": deepcopy(item["position"]),
            "width": item["width"],
            "height": item["height"],
        })
        nodes.append(node)
        next_id += 1
    return nodes, unmatched


def main() -> None:
    parser = argparse.ArgumentParser(description="将控件检测结果转换为 ht.Node 节点")
    parser.add_argument("--input", type=Path, default=ROOT / "detections.json")
    parser.add_argument("--template", type=Path, default=ROOT.parent / "data" / "control_template.json")
    parser.add_argument("--output", type=Path, default=ROOT / "control_nodes.json")
    parser.add_argument("--db", type=Path, default=ROOT.parents[2] / "data" / "sqlite" / "material.db")
    parser.add_argument("--start-id", type=int, default=None)
    args = parser.parse_args()

    detections = json.loads(args.input.read_text(encoding="utf-8"))
    template = json.loads(args.template.read_text(encoding="utf-8"))
    materials = load_query_results(args.db)
    nodes, unmatched = convert_control_nodes(detections, template, materials, args.start_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(nodes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("已转换 {} 个控件节点，输出至 {}".format(len(nodes), args.output))
    if unmatched:
        print("未匹配 {} 个控件: {}".format(len(unmatched), "、".join(str(value) for value in unmatched)))


if __name__ == "__main__":
    main()
