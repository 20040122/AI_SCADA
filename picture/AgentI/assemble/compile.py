import argparse
import json
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple


ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from control import convert_control_nodes, load_query_results
from text import convert_text_nodes


def compile_canvas(
    detections: List[Dict[str, Any]],
    canvas_template: Dict[str, Any],
    text_template: Dict[str, Any],
    control_template: Dict[str, Any],
    materials: List[Dict[str, Any]],
) -> Tuple[Dict[str, Any], List[str]]:
    control_nodes, unmatched = convert_control_nodes(detections, control_template, materials)
    text_nodes = convert_text_nodes(detections, text_template)
    canvas = deepcopy(canvas_template)
    canvas["d"] = control_nodes + text_nodes
    return canvas, unmatched


def main() -> None:
    parser = argparse.ArgumentParser(description="将文字节点和控件节点拼接到画布模板的 d 字段")
    parser.add_argument("--input", type=Path, default=ROOT / "detections.json")
    parser.add_argument("--canvas-template", type=Path, default=ROOT.parent / "data" / "canva_template.json")
    parser.add_argument("--text-template", type=Path, default=ROOT.parent / "data" / "text_template.json")
    parser.add_argument("--control-template", type=Path, default=ROOT.parent / "data" / "control_template.json")
    parser.add_argument("--db", type=Path, default=PROJECT / "data" / "sqlite" / "material.db")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    detections = json.loads(args.input.read_text(encoding="utf-8"))
    canvas_template = json.loads(args.canvas_template.read_text(encoding="utf-8"))
    text_template = json.loads(args.text_template.read_text(encoding="utf-8"))
    control_template = json.loads(args.control_template.read_text(encoding="utf-8"))
    materials = load_query_results(args.db)

    canvas, unmatched = compile_canvas(detections, canvas_template, text_template, control_template, materials)

    if args.output is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output = PROJECT / "output" / "canvas_{}.json".format(timestamp)
    else:
        output = args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(canvas, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    controls = sum(1 for node in canvas["d"] if node.get("c") == "ht.Node")
    texts = sum(1 for node in canvas["d"] if node.get("c") == "ht.Text")
    print("已生成画布 {}，控件节点 {} 个，文字节点 {} 个".format(output, controls, texts))
    if unmatched:
        print("未匹配 {} 个控件: {}".format(len(unmatched), "、".join(str(value) for value in unmatched)))


if __name__ == "__main__":
    main()
