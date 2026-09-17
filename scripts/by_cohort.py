#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""著者を「デビュー期」で分けて、指標の推移を見る。

「装飾は書き始める時点の型で決まる」を確かめるために作った。
答えは「決まらない」(docs/decoration-entry.md)。古参も本人内で変えている。

デビュー月は**このデータで最初に現れた月**で、Qiita の登録日ではない。
除外基準を満たさない記事しか書いていない時期があれば、実際はもっと早い。

使い方:
    ./scripts/by_cohort.py --months 2024-08,2025-08,2026-08
    ./scripts/by_cohort.py --debut          # 初投稿の装飾量をデビュー年別に
    ./scripts/by_cohort.py --within 2024-08 2026-08   # 本人内の変化
"""

from __future__ import annotations

import argparse
import glob
import json
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROC = ROOT / "data" / "processed"

FIELDS = [
    ("bold_per_1k", "太字/千字", "{:.3f}"),
    ("list_ratio", "箇条書き", "{:.3f}"),
    ("n_headings", "見出し数", "{:.1f}"),
]

GROUPS = [("2011-2019", 2011, 2019), ("2020-2023", 2020, 2023),
          ("2024", 2024, 2024), ("2025", 2025, 2025), ("2026", 2026, 2026)]


def month_files() -> list[Path]:
    out = []
    for p in sorted(PROC.glob("metrics_*.jsonl")):
        lbl = p.stem.replace("metrics_", "")
        if len(lbl) == 7 and lbl[4] == "-" and lbl[:4].isdigit():
            out.append(p)
    return out


def debut_months() -> dict[str, str]:
    """著者ごとの初出月。全期間を1回なめる(数十秒かかる)。"""
    first: dict[str, str] = {}
    for p in month_files():
        with p.open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                r = json.loads(line)
                u = r.get("user_id")
                m = r.get("created_at", "")[:7]
                if u and m and (u not in first or m < first[u]):
                    first[u] = m
    return first


def load_month(month: str) -> dict[str, list[dict]]:
    d: dict[str, list[dict]] = defaultdict(list)
    p = PROC / f"metrics_{month}.jsonl"
    if not p.exists():
        return d
    with p.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                r = json.loads(line)
                d[r.get("user_id")].append(r)
    return d


def group_of(year: int) -> str | None:
    for g, lo, hi in GROUPS:
        if lo <= year <= hi:
            return g
    return None


def show_months(first: dict[str, str], months: list[str], md: bool) -> None:
    head = ["月", "デビュー期", "記事数", "太字ゼロ%", "太字中央値", "箇条書き中央値"]
    print(("| " + " | ".join(head) + " |\n|" + "|".join("---" for _ in head) + "|")
          if md else "  ".join(head))
    for month in months:
        by = defaultdict(list)
        for u, rs in load_month(month).items():
            if u not in first:
                continue
            g = group_of(int(first[u][:4]))
            if g:
                by[g] += rs
        for g, _, _ in GROUPS:
            rs = by.get(g, [])
            if len(rs) < 100:
                continue
            b = [r["bold_per_1k"] for r in rs
                 if isinstance(r.get("bold_per_1k"), (int, float))]
            li = [r["list_ratio"] for r in rs
                  if isinstance(r.get("list_ratio"), (int, float))]
            zero = sum(1 for x in b if x == 0) / len(b) * 100
            cells = [month, g, f"{len(rs):,}", f"{zero:.0f}",
                     f"{statistics.median(b):.3f}", f"{statistics.median(li):.3f}"]
            print(("| " + " | ".join(cells) + " |") if md else "  ".join(cells))


def show_debut(md: bool) -> None:
    """各著者の初投稿そのものの装飾量を、デビュー年ごとに。"""
    firsts: dict[str, dict] = {}
    for p in month_files():
        with p.open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                r = json.loads(line)
                u = r.get("user_id")
                if not u:
                    continue
                cur = firsts.get(u)
                if cur is None or r["created_at"] < cur["created_at"]:
                    firsts[u] = r
    by = defaultdict(list)
    for r in firsts.values():
        by[r["created_at"][:4]].append(r)
    head = ["デビュー年", "初投稿の太字/千字", "初投稿の箇条書き", "著者数"]
    print(("| " + " | ".join(head) + " |\n|" + "|".join("---" for _ in head) + "|")
          if md else "  ".join(head))
    for y in sorted(by):
        rs = by[y]
        if len(rs) < 200:
            continue
        b = [r["bold_per_1k"] for r in rs
             if isinstance(r.get("bold_per_1k"), (int, float))]
        li = [r["list_ratio"] for r in rs
              if isinstance(r.get("list_ratio"), (int, float))]
        cells = [y, f"{statistics.median(b):.3f}",
                 f"{statistics.median(li):.3f}", f"{len(rs):,}"]
        print(("| " + " | ".join(cells) + " |") if md else "  ".join(cells))


def show_within(first: dict[str, str], a_month: str, b_month: str) -> None:
    """デビュー期ごとに、本人内で上げた人の割合を出す。

    中央値の差は「もともとゼロの人」が多いと 0.000 のままなので、
    割合のほうを見る。
    """
    a, b = load_month(a_month), load_month(b_month)
    common = set(a) & set(b)
    print(f"{a_month} → {b_month}")
    for g, lo, hi in GROUPS:
        users = [u for u in common
                 if u in first and lo <= int(first[u][:4]) <= hi]
        for f, lbl, _ in FIELDS:
            ds = []
            for u in users:
                va = [x[f] for x in a[u] if isinstance(x.get(f), (int, float))]
                vb = [x[f] for x in b[u] if isinstance(x.get(f), (int, float))]
                if va and vb:
                    ds.append(statistics.median(vb) - statistics.median(va))
            if len(ds) < 30:
                continue
            up = sum(1 for x in ds if x > 0)
            dn = sum(1 for x in ds if x < 0)
            if not (up + dn):
                continue
            print(f"  デビュー{g:10s} {lbl:8s} 差 {statistics.median(ds):+.3f}  "
                  f"上げた人 {up / (up + dn) * 100:.0f}%  n={len(ds)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--months", default="2024-08,2025-08,2026-08")
    ap.add_argument("--debut", action="store_true", help="初投稿の装飾量を見る")
    ap.add_argument("--within", nargs=2, metavar=("BEFORE", "AFTER"),
                    help="本人内の変化をデビュー期ごとに")
    ap.add_argument("--md", action="store_true")
    args = ap.parse_args()

    if args.debut:
        show_debut(args.md)
        return 0
    first = debut_months()
    if args.within:
        show_within(first, *args.within)
    else:
        show_months(first, args.months.split(","), args.md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
