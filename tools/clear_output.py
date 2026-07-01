from pathlib import Path

output_dir = Path(__file__).resolve().parent.parent / "output"

if not output_dir.exists():
    print(f"目录不存在: {output_dir}")
    exit(1)

deleted = 0
for f in output_dir.iterdir():
    if f.is_file():
        f.unlink()
        deleted += 1
        print(f"已删除: {f.name}")

print(f"共删除 {deleted} 个文件")
