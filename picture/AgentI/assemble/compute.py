import argparse
import json
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parent


def convert_detections(detections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    converted = []
    for item in detections:
        x, y, width, height = item["bbox"]
        result = {key: value for key, value in item.items() if key != "bbox"}
        result.update({"position": {"x": x + width / 2, "y": y + height / 2}, "width": width, "height": height})
        converted.append(result)
    return converted


def main() -> None:
    parser = argparse.ArgumentParser(description="将检测结果的 bbox 转换为 position、width 和 height")
    parser.add_argument("--input", type=Path, default=ROOT.parent / "opencv_output" / "detections.json")
    parser.add_argument("--output", type=Path, default=ROOT / "detections.json")
    args = parser.parse_args()

    detections = json.loads(args.input.read_text(encoding="utf-8"))
    converted = convert_detections(detections)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(converted, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("已转换 {} 条检测结果，输出至 {}".format(len(converted), args.output))


if __name__ == "__main__":
    main()
