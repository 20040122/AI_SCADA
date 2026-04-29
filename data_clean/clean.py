#python3 data_clean/clean.py 
import json
from pathlib import Path

data_dir = Path(__file__).resolve().parent.parent / "data"

for filepath in sorted(data_dir.glob("*.jsonl")):
    lines = filepath.read_text(encoding="utf-8").strip().splitlines()
    seen = {}
    kept = []
    for line in lines:
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        key = (obj.get("displayName"), obj.get("image"))
        if key not in seen:
            seen[key] = True
            kept.append(line)
    filepath.write_text("\n".join(kept) + "\n", encoding="utf-8")
    print(f"{filepath.name}: {len(lines)} -> {len(kept)} lines")
