import json
import urllib.request
from pathlib import Path

URL = "http://daoscada.local/hmi-ui/explore/symbols"
OUTPUT = Path(__file__).resolve().parent / "symbols.json"


def collect_json_paths(data, prefix="", paths=None):
    if paths is None:
        paths = set()
    if isinstance(data, dict):
        for k, v in data.items():
            current = f"{prefix}/{k}" if prefix else k
            if k.endswith(".json"):
                paths.add(current)
            collect_json_paths(v, current, paths)
    elif isinstance(data, list):
        for i, item in enumerate(data):
            collect_json_paths(item, f"{prefix}/{i}", paths)
    return paths


def main():
    try:
        resp = urllib.request.urlopen(URL, timeout=30)
        data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"请求或解析失败: {e}")
        exit(1)

    paths = collect_json_paths(data, prefix="symbols")
    sorted_paths = sorted(paths)

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(sorted_paths, f, ensure_ascii=False, indent=2)

    print(f"共提取 {len(sorted_paths)} 个控件文件")
    print(f"已保存到 {OUTPUT}")


if __name__ == "__main__":
    main()
