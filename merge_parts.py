#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 plan_parts/ 下的分片合并成一份完整 JSON(系统托管工具,不要自己重写)。

用法(在工程根跑,不要 cd,也不要加绝对路径):

    python merge_parts.py                                  # → modeling_plan.json
    python merge_parts.py --key tasks --out research_plan.json

读取规则:
  * `plan_parts/_meta.json`   顶层字段(title / assumptions / data_strategy …)
  * `plan_parts/_*.json`      其余顶层片段(如 `_scoring.json`),浅合并进顶层
  * `plan_parts/p*.json`      每个文件一条,按 p1、p2、…、p10 的自然序组成 --key 数组

分片里最常见的坏法是中文强调引号写成半角、又嵌在字符串值里没转义::

    "claim": "而非简单地"越大越好",这是因为…"

这会让 json 报 `Expecting ',' delimiter`,而报错只给行列号。本工具按确定性判据
(字符串收尾引号后面只可能是 , } ] : 或文件结束)把它改成全角引号并回写分片,
同时打印修了哪个文件、几处;判不定的照实报错并指出行号,不猜着改。

本文件与 backend/json_loose.py 是同一套规则的两份实现(工作区里跑不到后端代码),
tests/test_plan_parts_merge.py 会拿同一批坏样本比对两边行为,防止悄悄跑偏。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_AFTER_STRING = frozenset(",}]:")
_WS = " \t\r\n"
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")
_NUM_RE = re.compile(r"(\d+)")


def escape_inner_quotes(text: str) -> tuple[str, int]:
    """把字符串值内部落单的半角双引号改成全角引号,返回 (新文本, 处数)。"""
    out: list[str] = []
    i, n = 0, len(text)
    in_str = False
    want_open = True
    fixed = 0
    while i < n:
        ch = text[i]
        if not in_str:
            out.append(ch)
            if ch == '"':
                in_str = True
                want_open = True
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            out.append(text[i:i + 2])
            i += 2
            continue
        if ch == '"':
            j = i + 1
            while j < n and text[j] in _WS:
                j += 1
            if j >= n or text[j] in _AFTER_STRING:
                out.append(ch)
                in_str = False
            else:
                out.append("“" if want_open else "”")
                want_open = not want_open
                fixed += 1
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out), fixed


def loads(text: str) -> tuple[object, list[str]]:
    """严格解析优先,失败再按确定性规则修一遍;修不好抛原始错误。"""
    try:
        return json.loads(text), []
    except ValueError as exc:
        first = exc
    fixes: list[str] = []
    cand, n_quote = escape_inner_quotes(text)
    if n_quote:
        fixes.append(f"字符串内 {n_quote} 处半角双引号改为全角引号")
    cand, n_comma = _TRAILING_COMMA_RE.subn(r"\1", cand)
    if n_comma:
        fixes.append(f"{n_comma} 处数组/对象末尾多余的逗号")
    if not fixes:
        raise first
    try:
        return json.loads(cand), fixes
    except ValueError:
        raise first from None


def _describe(text: str, exc: ValueError) -> str:
    line_no = getattr(exc, "lineno", 0) or 0
    col_no = getattr(exc, "colno", 0) or 0
    lines = text.splitlines()
    raw = lines[line_no - 1] if 0 < line_no <= len(lines) else ""
    tip = ""
    if raw.count('"') > 2:
        tip = ("\n    这一行的半角双引号多于一对——中文强调引号写成半角了,"
               "改成全角“”或「」,不要用反斜杠转义。")
    return f"第 {line_no} 行第 {col_no} 列:{exc.msg}\n    {raw.strip()[:160]}{tip}"


def _natural_key(path: Path) -> tuple:
    """p2 排在 p10 前面:按文件名里的数字比,不是按字符串比。"""
    return tuple(int(s) if s.isdigit() else s.lower()
                 for s in _NUM_RE.split(path.name))


def _load_fragment(path: Path, repaired: list[str]) -> object:
    text = path.read_text(encoding="utf-8")
    try:
        obj, fixes = loads(text)
    except ValueError as exc:
        raise SystemExit(
            f"✗ {path.as_posix()} 不是合法 JSON\n  {_describe(text, exc)}\n"
            f"  改好这个文件后重新跑 python merge_parts.py 即可,"
            f"不必改别的分片、也不必重写本工具。")
    if fixes:
        path.write_text(
            json.dumps(obj, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        repaired.append(f"{path.as_posix()}:{'、'.join(fixes)}(已回写)")
    return obj


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="合并 plan_parts/ 分片")
    ap.add_argument("--dir", default="plan_parts", help="分片目录")
    ap.add_argument("--key", default="subproblems", help="分片数组的顶层键名")
    ap.add_argument("--out", default="modeling_plan.json", help="输出文件")
    args = ap.parse_args(argv)

    root = Path(__file__).resolve().parent
    parts = root / args.dir
    if not parts.is_dir():
        print(f"✗ 找不到分片目录 {args.dir}/,先把分片写进去再合并", file=sys.stderr)
        return 1

    repaired: list[str] = []
    top: dict = {}
    meta = parts / "_meta.json"
    if meta.is_file():
        obj = _load_fragment(meta, repaired)
        if not isinstance(obj, dict):
            print("✗ _meta.json 必须是一个 JSON 对象", file=sys.stderr)
            return 1
        top.update(obj)
    for extra in sorted(parts.glob("_*.json"), key=_natural_key):
        if extra.name == "_meta.json":
            continue
        obj = _load_fragment(extra, repaired)
        if isinstance(obj, dict):
            top.update(obj)
        else:
            print(f"✗ {extra.name} 必须是一个 JSON 对象(顶层片段)", file=sys.stderr)
            return 1

    items = [_load_fragment(p, repaired)
             for p in sorted(parts.glob("p*.json"), key=_natural_key)]
    for line in repaired:
        print(f"· 已修复 {line}")
    if not items:
        print(f"✗ {args.dir}/ 下没有 p*.json 分片,{args.key} 会是空数组;"
              f"每一条先写成 {args.dir}/p1.json、p2.json……再合并", file=sys.stderr)
        return 1

    top[args.key] = items
    out = root / args.out
    out.write_text(json.dumps(top, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    ids = [str(x.get("id") or "?") if isinstance(x, dict) else "?" for x in items]
    print(f"✓ 已合并 {len(items)} 条 {args.key} → {args.out}(id: {', '.join(ids)})")
    print(f"  顶层字段:{', '.join(k for k in top if k != args.key) or '(无)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
