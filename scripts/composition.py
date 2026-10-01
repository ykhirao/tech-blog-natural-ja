#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""全体の変化を「層の構成が変わった分」と「層の中で変わった分」に分ける。

2022年の変化は書き手の入れ替わりだった(docs/within-author-2022.md)。
ただし新規著者率は動いていない(docs/confounds-2026.md)ので、
単純な新規流入では説明できない。どの層が入れ替わったのかを見る。

層は**経験本数**で分ける。その月より前にこのデータで何本書いていたか。
`user_items_count` は取得時点の値で記事を書いた時点の値ではないので使わない。
自分のデータから数えれば、その月までの本数になる。

分解のしかた(標準的な要因分解):

    全体の差 = Σ(構成比の差 × 層の水準) + Σ(構成比 × 層の中の差)
               ~~~~~~~~~~~~~~~~~~~~~~~~     ~~~~~~~~~~~~~~~~~~~~~~
               構成の変化で説明できる分       層の中の変化で説明できる分

水準は各層の平均を使う。構成比は後の月、水準は前の月を基準に取る
(基準の取り方で内訳は少し変わるので、両方向を出す)。

--debut は別の見方。デビュー年ごとに、その人の**初投稿**だけを集める。
入ってきた人が最初から違う書き方をしていたかが分かる。

使い方:
    ./scripts/composition.py --debut
    ./scripts/composition.py 2021-08 2022-11
    ./scripts/composition.py 2020-02 2026-08 --field ten_per_sentence
    ./scripts/composition.py 2021-08 2022-11 --md
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROC = ROOT / "data" / "processed"

# 経験本数の層。(名前, 下限, 上限) 上限は含む。None は無限
LAYERS = [("初投稿", 0, 0), ("1-2本", 1, 2), ("3-9本", 3, 9), ("10本以上", 10, None)]


def months() -> list[str]:
    return sorted(p.stem.replace("metrics_", "")
                  for p in PROC.glob("metrics_*.jsonl"))


def prior_counts(upto: str) -> dict[str, int]:
    """upto より前の月までに、各著者が何本書いたか。"""
    n: dict[str, int] = defaultdict(int)
    for m in months():
        if m >= upto:
            break
        with (PROC / f"metrics_{m}.jsonl").open(encoding="utf-8") as f:
            for line in f:
                u = json.loads(line).get("user_id")
                if u:
                    n[u] += 1
    return n


def load(month: str, field: str) -> list[tuple[str, float]]:
    out = []
    p = PROC / f"metrics_{month}.jsonl"
    if not p.exists():
        print(f"{month} のデータがありません", file=sys.stderr)
        raise SystemExit(1)
    with p.open(encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            v, u = r.get(field), r.get("user_id")
            if v is not None and u:
                out.append((u, float(v)))
    return out


def layer_of(k: int) -> str:
    for name, lo, hi in LAYERS:
        if k >= lo and (hi is None or k <= hi):
            return name
    return LAYERS[-1][0]


def summarize(month: str, field: str) -> dict[str, list[float]]:
    prior = prior_counts(month)
    by: dict[str, list[float]] = defaultdict(list)
    for u, v in load(month, field):
        by[layer_of(prior.get(u, 0))].append(v)
    return by


DEBUT_FIELDS = [
    ("nominal_ending_ratio", "体言止め", "{:.4f}"),
    ("ten_per_sentence", "読点/文", "{:.3f}"),
    ("bold_per_1k", "太字/千字", "{:.3f}"),
]


def show_debut(md: bool, min_n: int) -> None:
    """デビュー年ごとに初投稿の指標を見る。

    デビュー月はこのデータで最初に現れた月。2011年より前は見えないので、
    最初の数年は本当の初投稿でない著者が混じる。
    """
    first: dict[str, str] = {}
    rows: dict[tuple[str, str], list[float]] = defaultdict(list)
    for m in months():
        with (PROC / f"metrics_{m}.jsonl").open(encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                u = r.get("user_id")
                if not u or u in first:
                    continue
                first[u] = m
                for key, _, _ in DEBUT_FIELDS:
                    v = r.get(key)
                    if v is not None:
                        rows[(m[:4], key)].append(float(v))
    years = sorted({y for y, _ in rows})
    labels = [lab for _, lab, _ in DEBUT_FIELDS]
    if md:
        print("| デビュー年 | 人数 | " + " | ".join(labels) + " |")
        print("|---|---|" + "|".join(["---"] * len(labels)) + "|")
    else:
        print(f"{'デビュー年':<12}{'人数':>7}" + "".join(f"{l:>12}" for l in labels))
        print("-" * (19 + 12 * len(labels)))
    for y in years:
        n = rows.get((y, DEBUT_FIELDS[0][0]), [])
        if len(n) < min_n:
            continue
        cells = []
        for key, _, fmt in DEBUT_FIELDS:
            vs = rows.get((y, key), [])
            cells.append(fmt.format(statistics.fmean(vs)) if vs else "-")
        if md:
            print(f"| {y} | {len(n):,} | " + " | ".join(cells) + " |")
        else:
            print(f"{y:<12}{len(n):>7}" + "".join(f"{c:>12}" for c in cells))


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("before", nargs="?")
    ap.add_argument("after", nargs="?")
    ap.add_argument("--debut", action="store_true",
                    help="デビュー年ごとに初投稿の指標を見る")
    ap.add_argument("--min-n", type=int, default=50)
    ap.add_argument("--field", default="nominal_ending_ratio")
    ap.add_argument("--md", action="store_true")
    args = ap.parse_args()

    if args.debut:
        show_debut(args.md, args.min_n)
        return 0
    if not args.before or not args.after:
        ap.print_help()
        return 1

    a = summarize(args.before, args.field)
    b = summarize(args.after, args.field)
    na = sum(len(v) for v in a.values())
    nb = sum(len(v) for v in b.values())
    names = [n for n, _, _ in LAYERS]

    sa = {n: len(a.get(n, [])) / na for n in names}
    sb = {n: len(b.get(n, [])) / nb for n in names}
    ma = {n: statistics.fmean(a[n]) if a.get(n) else None for n in names}
    mb = {n: statistics.fmean(b[n]) if b.get(n) else None for n in names}

    all_a = [v for n in names for v in a.get(n, [])]
    all_b = [v for n in names for v in b.get(n, [])]
    total = statistics.fmean(all_b) - statistics.fmean(all_a)

    comp = sum((sb[n] - sa[n]) * ma[n] for n in names if ma[n] is not None)
    within = sum(sa[n] * (mb[n] - ma[n]) for n in names
                 if ma[n] is not None and mb[n] is not None)
    comp2 = sum((sb[n] - sa[n]) * mb[n] for n in names if mb[n] is not None)
    within2 = sum(sb[n] * (mb[n] - ma[n]) for n in names
                  if ma[n] is not None and mb[n] is not None)

    hdr = (f"| 層 | {args.before} 構成 | {args.after} 構成 | "
           f"{args.before} 水準 | {args.after} 水準 | 層の中の差 |")
    if args.md:
        print(f"指標: `{args.field}` / 記事数 {na:,} -> {nb:,}\n")
        print(hdr)
        print("|---|---|---|---|---|---|")
        for n in names:
            d = (f"{mb[n] - ma[n]:+.4f}" if ma[n] is not None and mb[n] is not None
                 else "-")
            print(f"| {n} | {sa[n] * 100:.1f}% | {sb[n] * 100:.1f}% | "
                  f"{ma[n]:.4f} | {mb[n]:.4f} | {d} |")
        print(f"\n全体の差 {total:+.4f}\n")
        print("| 内訳 | 構成の変化 | 層の中の変化 |")
        print("|---|---|---|")
        print(f"| 前の月の水準を基準 | {comp:+.4f} | {within:+.4f} |")
        print(f"| 後の月の水準を基準 | {comp2:+.4f} | {within2:+.4f} |")
    else:
        print(f"指標: {args.field} / 記事数 {na:,} -> {nb:,}\n")
        print(f"{'層':<10}{'構成前':>8}{'構成後':>8}{'水準前':>10}{'水準後':>10}{'層内差':>10}")
        print("-" * 58)
        for n in names:
            d = (f"{mb[n] - ma[n]:+.4f}" if ma[n] is not None and mb[n] is not None
                 else "-")
            print(f"{n:<10}{sa[n] * 100:>7.1f}%{sb[n] * 100:>7.1f}%"
                  f"{ma[n]:>10.4f}{mb[n]:>10.4f}{d:>10}")
        print(f"\n全体の差 {total:+.4f}")
        print(f"  構成の変化で説明  {comp:+.4f} (後の水準を基準なら {comp2:+.4f})")
        print(f"  層の中の変化      {within:+.4f} (後の構成を基準なら {within2:+.4f})")
        if abs(total) > 1e-9:
            print(f"  構成で説明できる割合  {comp / total * 100:.0f}%"
                  f" 〜 {comp2 / total * 100:.0f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
