import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional


ROOT = Path(__file__).resolve().parent


def convert_text_nodes(
    detections: List[Dict[str, Any]],
    template: Dict[str, Any],
    start_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    nodes = []
    next_id = template["i"] if start_id is None else start_id
    for item in detections:
        if item.get("type") != "text":
            continue
        node = deepcopy(template)
        node["i"] = next_id
        node["p"].update({
            "position": deepcopy(item["position"]),
            "width": item["width"],
            "height": item["height"],
        })
        node["s"]["text"] = item["value"]
        nodes.append(node)
        next_id += 1
    return nodes


def main() -> None:
    parser = argparse.ArgumentParser(description="将文字检测结果转换为 ht.Text 节点")
    parser.add_argument("--input", type=Path, default=ROOT / "detections.json")
    parser.add_argument("--template", type=Path, default=ROOT.parent / "data" / "text_template.json")
    parser.add_argument("--output", type=Path, default=ROOT / "text_nodes.json")
    parser.add_argument("--start-id", type=int, default=None)
    args = parser.parse_args()

    detections = json.loads(args.input.read_text(encoding="utf-8"))
    template = json.loads(args.template.read_text(encoding="utf-8"))
    nodes = convert_text_nodes(detections, template, args.start_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(nodes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("已转换 {} 个文字节点，输出至 {}".format(len(nodes), args.output))


if __name__ == "__main__":
    main()
