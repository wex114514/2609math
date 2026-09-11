from pathlib import Path

path = Path(__file__).resolve().with_name("problem1.py")
lines = path.read_text(encoding="utf-8").splitlines()
for number, line in enumerate(lines, 1):
    if number >= 380:
        print(f"{number}: {line}")
