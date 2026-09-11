#!/usr/bin/env python3
"""依次运行 src/ 下的求解脚本,校验 figures/ 与 results/ 有实际产出。

用法:
    python run_all.py            # 人类可读
    python run_all.py --json     # 机器可读
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def find_root() -> Path:
    env = os.environ.get("PROJECT_ROOT")
    if env:
        return Path(env).resolve()
    cur = Path(__file__).resolve().parent
    for d in [cur, *cur.parents]:
        if (d / "src").is_dir():
            return d
    return cur


def solve_scripts(src: Path):
    if not src.is_dir():
        return []
    prefixes = ("problem", "solve", "q", "task", "main")
    files = [p for p in src.glob("*.py")
             if p.name.lower().startswith(prefixes) and p.name != "__init__.py"]
    if not files:
        files = [p for p in src.glob("*.py") if p.name != "__init__.py"]
    return sorted(files, key=lambda p: p.name)


def count_files(d: Path):
    return len([p for p in d.rglob("*") if p.is_file()]) if d.is_dir() else 0


def no_window_kwargs():
    """Windows 上隐藏逐个脚本子进程新弹的黑色终端窗口。

    本脚本被数模工坊(无控制台的窗口程序)静默拉起时自己也没有控制台,再去拉
    python.exe 跑每个 problemN.py,Windows 就会挨个新开终端并抢前台焦点。
    输出全部走管道回传界面,窗口纯属打扰。
    """
    if sys.platform.startswith("win"):
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = find_root()
    src = root / "src"
    figures = root / "figures"
    results = root / "results"
    figures.mkdir(exist_ok=True)
    results.mkdir(exist_ok=True)

    scripts = solve_scripts(src)
    run_results = []
    overall_ok = bool(scripts)

    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(root), str(src), env.get("PYTHONPATH", "")])
    env["MPLBACKEND"] = "Agg"

    for s in scripts:
        t0 = time.time()
        try:
            p = subprocess.run([sys.executable, s.name], cwd=str(src),
                               capture_output=True, text=True, env=env,
                               timeout=600, **no_window_kwargs())
            code, out, err = p.returncode, p.stdout, p.stderr
        except subprocess.TimeoutExpired:
            code, out, err = 124, "", "超时(>600s)"
        except Exception as e:  # noqa: BLE001
            code, out, err = 1, "", str(e)
        ok = code == 0
        if not ok:
            overall_ok = False
        run_results.append({
            "script": s.name,
            "ok": ok,
            "code": code,
            "seconds": round(time.time() - t0, 1),
            "stdout_tail": (out or "")[-1000:],
            "stderr_tail": (err or "")[-5000:],
        })

    fig_after = count_files(figures)
    res_after = count_files(results)
    if not scripts:
        overall_ok = False
    if overall_ok and fig_after == 0 and res_after == 0:
        overall_ok = False

    payload = {
        "root": str(root),
        "ok": overall_ok,
        "scripts_run": len(scripts),
        "figures_total": fig_after,
        "results_total": res_after,
        "results": run_results,
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"root: {root}")
        if not scripts:
            print("结果: src/ 下未找到求解脚本")
        for r in run_results:
            mark = "OK " if r["ok"] else "FAIL"
            print(f"[{mark}] {r['script']}  ({r['seconds']}s)")
            if not r["ok"]:
                for line in r["stderr_tail"].splitlines()[-20:]:
                    print("  " + line)
        print(f"figures: {fig_after} | results: {res_after}")
        print("总体: " + ("达标 ✅" if overall_ok else "未达标 ❌"))

    sys.exit(0 if overall_ok else 1)


if __name__ == "__main__":
    main()
