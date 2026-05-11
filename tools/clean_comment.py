#python tools/clean.py
from pathlib import Path

data_dir = Path(__file__).resolve().parent.parent / "data"

for filepath in sorted(data_dir.glob("*.jsonl")):
    lines = filepath.read_text(encoding="utf-8").splitlines()
    kept = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("//"):
            continue
        kept.append(line)

    filepath.write_text("\n".join(kept) + "\n", encoding="utf-8")
    print(f"{filepath.name}: {len(lines)} -> {len(kept)} lines")
