from pathlib import Path

root = Path(__file__).resolve().parents[1]
print("=== 工程根目录文件 ===")
for f in sorted(root.iterdir()):
    if f.is_file():
        print(f"  {f.name}")

print("\n=== chapters/ 目录 ===")
chapters_dir = root / "chapters"
if chapters_dir.exists():
    for f in sorted(chapters_dir.iterdir()):
        print(f"  {f.name}")
