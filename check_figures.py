"""结果图闸门:汇总 figures/ 的图面自检结果,有硬伤就退出码 1。

智能体看不见自己画出来的图,压字、空面板、平线、双轴柱这类毛病靠「打开看一眼」
是拦不住的。plot_style 在 savefig 时已就地体检并把结果写进
``figures/_figure_lint.json``;本脚本把它汇总成一道可执行的闸门:

    python check_figures.py          # 退出码 0 = 无硬伤
    python check_figures.py --json   # 机器可读

AI 生成的机理图/流程图(image2 出图,非 matplotlib)不参与体检。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
FIGDIR = os.path.join(ROOT, "figures")
LINT = os.path.join(FIGDIR, "_figure_lint.json")
EXTS = (".png", ".svg", ".pdf")
# image2 生成或系统托管的图:不由 matplotlib 产出,自然没有体检记录
SKIP_PREFIX = ("algo_", "schematic_", "flowchart", "_")
SKIP_SUFFIX = ("_mechanism",)


# 两张图的数据取值重合到这个比例,就判定它们画的是同一批数。
# 留 0.9 的余量:同一批数换个图型画,坐标/误差棒会带进几个额外取值。
DUP_OVERLAP = 0.9
DUP_MIN_VALUES = 5      # 五个 Sobol/权重指标已足以判重;两三个值仍不参与


def _skip(stem: str) -> bool:
    return (stem.startswith(SKIP_PREFIX) or stem.endswith(SKIP_SUFFIX)
            or ".old" in stem)


def _overlap(a: dict, b: dict) -> float:
    """包含率(交集 / 较小那一方);与 plot_style.data_overlap 同口径。"""
    va = set((a or {}).get("values") or [])
    vb = set((b or {}).get("values") or [])
    if not va or not vb:
        return 0.0
    return len(va & vb) / min(len(va), len(vb))


def duplicates(figs: dict) -> list:
    """找出画的是同一批数据的图对。

    一道题往往只有一组核心结果,而「把角色配齐」的要求会诱使人把同一组数换个
    图型再画一遍(实测 problemN.png 是分组柱、problemN_comparison.png 是误差点,
    数一模一样),两张都插进论文,评委一眼看出是凑数。文件名与字节哈希都认不出
    这种重复,只有比对图里画进去的数值才认得出。
    """
    items = [(stem, it["data"]) for stem, it in figs.items()
             if (it.get("data") or {}).get("values")
             and len(it["data"]["values"]) >= DUP_MIN_VALUES]
    out = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            ov = _overlap(items[i][1], items[j][1])
            if ov >= DUP_OVERLAP:
                out.append({"a": items[i][0], "b": items[j][0],
                            "overlap": round(ov, 3)})
    return out


def color_conflicts(figs: dict) -> list:
    """同一个量在不同图里用了不同颜色。

    实测:「光伏出力」在 problem1_data 里是红色、在 problem3_data 里是绿色,
    两张图各自体检都通过——**单张图怎么看都看不出来**,只有攒齐全套图才判得了。
    读者翻到第二张时会以为这是另一个量。根因是按 `PALETTE[i]` 下标取色:
    各脚本各排各的序,同一个量的下标自然对不上。
    """
    seen: dict[str, dict[str, list]] = {}
    for stem, item in figs.items():
        for label, color in (item.get("series") or {}).items():
            seen.setdefault(label, {}).setdefault(color, []).append(stem)
    out = []
    for label, by_color in sorted(seen.items()):
        if len(by_color) < 2:
            continue
        where = [(c, sorted(s)) for c, s in by_color.items()]
        out.append({"label": label, "where": sorted(where)})
    return out


def collect() -> dict:
    """按图名(stem)汇总:每张图的问题清单与是否做过自检。"""
    records = {}
    if os.path.isfile(LINT):
        try:
            with open(LINT, encoding="utf-8") as f:
                records = (json.load(f) or {}).get("figures") or {}
        except (OSError, ValueError):
            records = {}

    out: dict[str, dict] = {}
    selected: dict[str, tuple[float, int]] = {}
    if not os.path.isdir(FIGDIR):
        return out
    for name in sorted(os.listdir(FIGDIR)):
        stem, ext = os.path.splitext(name)
        if ext.lower() not in EXTS or _skip(stem):
            continue
        rec = records.get(name)
        out.setdefault(stem, {"issues": [], "checked": False,
                              "data": {}, "series": {}})
        if not isinstance(rec, dict):
            continue
        # 同一张图常同时存 PNG/PDF/SVG。旧实现把各后缀 issues 做并集:
        # 只重存 PNG 后,旧 PDF 的历史硬伤仍会阴魂不散。按 checked_at 选最新记录,
        # 时间相同则优先用户实际预览的 PNG,整条记录一起替换。
        priority = (
            float(rec.get("checked_at") or 0.0),
            {".png": 3, ".svg": 2, ".pdf": 1}.get(ext.lower(), 0))
        if priority < selected.get(stem, (-1.0, -1)):
            continue
        selected[stem] = priority
        out[stem] = {
            "issues": list(rec.get("issues") or []),
            "checked": True,
            "data": dict(rec.get("data") or {}),
            "series": dict(rec.get("series") or {}),
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="结果图闸门")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    figs = collect()
    errors = warns = 0
    unchecked = []
    for stem, item in figs.items():
        errors += sum(1 for i in item["issues"] if i.get("level") == "error")
        warns += sum(1 for i in item["issues"] if i.get("level") != "error")
        if not item["checked"]:
            unchecked.append(stem)
    dups = duplicates(figs)
    errors += len(dups)
    clashes = color_conflicts(figs)
    errors += len(clashes)

    if args.json:
        print(json.dumps({"ok": errors == 0 and not unchecked,
                          "errors": errors, "warns": warns,
                          "unchecked": unchecked, "duplicates": dups,
                          "color_conflicts": clashes, "figures": figs},
                         ensure_ascii=False, indent=1))
        return 0 if (errors == 0 and not unchecked) else 1

    if not figs:
        print("figures/ 下没有需要体检的结果图。")
        return 0
    # 标记只用 GBK 也能编码的字符:控制台不是 UTF-8 时,✓/✗ 会让整个脚本崩在 print 上
    for stem, item in figs.items():
        if not item["checked"]:
            print(f"[未自检] {stem}:请用 plot_style.apply() 后重新出图")
            continue
        if not item["issues"]:
            print(f"[通过] {stem}")
            continue
        worst = ("硬伤" if any(i.get("level") == "error" for i in item["issues"])
                 else "提醒")
        print(f"[{worst}] {stem}")
        for i in item["issues"]:
            mark = "硬伤" if i.get("level") == "error" else "提醒"
            print(f"    [{mark}] {i.get('panel', '')}{i.get('msg', '')}")

    for d in dups:
        print(f"[硬伤] {d['a']} 与 {d['b']} 画的是同一批数据"
              f"(取值重合 {d['overlap']:.0%})")
        print("    [硬伤] 同一组数换个图型再画一遍算重复,不算两张图:"
              "合成一张 (a)(b) 多面板并删掉多余那张,或只留信息量大的那张")

    for c in clashes:
        where = "；".join(
            f"{col} 用在 {'、'.join(stems)}" for col, stems in c["where"])
        print(f"[硬伤] 「{c['label']}」在不同图里换了颜色:{where}")
        print("    [硬伤] 同一个量全篇必须同一种颜色,读者翻到第二张会以为是另一个量:"
              "改成 `ax.plot(x, y, label=名, **plot_style.series_style(名))`"
              "(只要颜色用 `plot_style.series_color(名)`),别写 PALETTE[下标]——"
              "各脚本各排各的序,同一个量的下标对不上")

    print(f"\n合计:{len(figs)} 张图 · 硬伤 {errors} · 提醒 {warns}"
          + (f" · 重复 {len(dups)} 对" if dups else "")
          + (f" · 换色 {len(clashes)} 个量" if clashes else "")
          + (f" · 未自检 {len(unchecked)}" if unchecked else ""))
    if errors or unchecked:
        print("硬伤必须改到 0 才算完成:按上面每条的建议改绘图代码并重跑脚本。")
        return 1
    print("图面自检通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
