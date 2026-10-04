#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""地の文の文字種の割合と、インラインコードの量。

地の文の英字が2026年に減った(docs/lexical-diversity.md)。
減った分がどこへ行ったのかを見る。考えられるのは2つ。

  1. バッククォートで囲むようになった。`clean_inline` はインラインコードを
     削除するので、囲めば地の文の英字は自動的に減る。書き方は変わっていない
  2. 英語を使うのをやめて日本語で書くようになった。こちらは本物の変化

1 を切り分けるため、囲まれた英字も数えて合計を出す。
合計が減っていれば、囲んだだけでは説明できない。

月次で何かを見つけたら週次で確かめる(../AGENTS.md)。--weekly を使う。
weekly.py は data/processed を読むので文字種の指標を持っていない。

使い方:
    ./scripts/char_classes.py --months 2015-08,2020-08,2024-08,2026-08
    ./scripts/char_classes.py --weekly 2025-06 2026-09
    ./scripts/char_classes.py --within 2024-08 2026-08
    ./scripts/char_classes.py --months 2020-08,2026-08 --md
"""

from __future__ import annotations

import argparse
import datetime
import json
import random
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
sys.path.insert(0, str(ROOT / "scripts"))
from metrics import clean_inline, split_markdown  # noqa: E402

CLASSES = {
    "英字": re.compile(r"[A-Za-z]"),
    "カタカナ": re.compile(r"[ァ-ヶー]"),
    "ひらがな": re.compile(r"[ぁ-ん]"),
    "漢字": re.compile(r"[一-龥]"),
}
INLINE_CODE = re.compile(r"`[^`\n]+`")
EN_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_.-]*")


def articles(month: str, with_date: bool = False):
    """(著者, 地の文, 装飾を残した本文) を返す。コードブロックは除いてある。"""
    for f in sorted(RAW.glob(f"qiita_{month}-*.jsonl")):
        for line in f.open(encoding="utf-8"):
            it = json.loads(line)
            body = it.get("body") or ""
            if len(body) < 1000:
                continue
            raw = "\n".join(split_markdown(body)["body_lines"])
            plain = clean_inline(raw)
            if len(plain) < 300:
                continue
            if with_date:
                yield it.get("created_at") or "", plain, raw
            else:
                yield it.get("user_id") or "", plain, raw


COLS = list(CLASSES) + ["code/千字", "囲まれた英字", "地の文の英字", "合計英字"]


def one(plain: str, raw: str) -> list[float]:
    """記事1本ぶんの値。"""
    n = len(plain)
    codes = INLINE_CODE.findall(raw)
    inside = sum(len(EN_TOKEN.findall(c)) for c in codes)
    outside = len(EN_TOKEN.findall(plain))
    k = n / 1000
    return ([len(rx.findall(plain)) / n for rx in CLASSES.values()]
            + [len(codes) / (len(raw) / 1000), inside / k, outside / k,
               (inside + outside) / k])


def profile(items) -> list[float]:
    """記事ごとに出してから平均する。長い記事に引っ張られないようにする。"""
    vals = [one(p, r) for p, r in items]
    return [statistics.fmean(v[i] for v in vals) for i in range(len(COLS))]


def run_months(months: list[str], n: int, md: bool) -> None:
    rows = []
    for m in months:
        items = [(p, r) for _, p, r in articles(m)]
        if not items:
            print(f"{m} のデータがありません", file=sys.stderr)
            continue
        random.seed(42)
        random.shuffle(items)
        items = items[:n]
        rows.append((m, len(items), profile(items)))
    if md:
        print("| 月 | 記事 | " + " | ".join(COLS) + " |")
        print("|---|---|" + "|".join(["---"] * len(COLS)) + "|")
        for m, c, v in rows:
            cells = [f"{x:.4f}" if i < len(CLASSES) else f"{x:.2f}"
                     for i, x in enumerate(v)]
            print(f"| {m} | {c:,} | " + " | ".join(cells) + " |")
    else:
        print(f"{'月':<10}{'記事':>7}" + "".join(f"{c:>13}" for c in COLS))
        print("-" * (17 + 13 * len(COLS)))
        for m, c, v in rows:
            cells = "".join(f"{x:>13.4f}" if i < len(CLASSES) else f"{x:>13.2f}"
                            for i, x in enumerate(v))
            print(f"{m:<10}{c:>7,}" + cells)


def run_weekly(since: str, until: str, min_articles: int, md: bool) -> None:
    """ISO 週ごとにまとめる。薄い週は落とす(年末年始や取得の切れ目で跳ねる)。"""
    buckets: dict[str, list[tuple[str, str]]] = defaultdict(list)
    y, m = (int(x) for x in since.split("-"))
    ey, em = (int(x) for x in until.split("-"))
    while (y, m) <= (ey, em):
        for created, plain, raw in articles(f"{y:04d}-{m:02d}", with_date=True):
            if not created:
                continue
            try:
                d = datetime.date.fromisoformat(created[:10])
            except ValueError:
                continue
            iso = d.isocalendar()
            buckets[f"{iso[0]}-W{iso[1]:02d}"].append((plain, raw))
        m += 1
        if m > 12:
            y, m = y + 1, 1

    rows = [(w, len(v), profile(v)) for w, v in sorted(buckets.items())
            if len(v) >= min_articles]
    if not rows:
        print(f"{min_articles}本に届く週がありません", file=sys.stderr)
        return
    show = ["英字", "カタカナ", "漢字", "code/千字", "合計英字"]
    idx = [COLS.index(c) for c in show]
    if md:
        print("| 週 | 記事 | " + " | ".join(show) + " |")
        print("|---|---|" + "|".join(["---"] * len(show)) + "|")
        for w, c, v in rows:
            cells = [f"{v[i]:.4f}" if i < len(CLASSES) else f"{v[i]:.2f}" for i in idx]
            print(f"| {w} | {c:,} | " + " | ".join(cells) + " |")
    else:
        print(f"{'週':<11}{'記事':>7}" + "".join(f"{c:>13}" for c in show))
        print("-" * (18 + 13 * len(show)))
        for w, c, v in rows:
            cells = "".join(f"{v[i]:>13.4f}" if i < len(CLASSES) else f"{v[i]:>13.2f}"
                            for i in idx)
            print(f"{w:<11}{c:>7,}" + cells)


def run_within(a: str, b: str) -> None:
    groups = {}
    for month in (a, b):
        by = defaultdict(list)
        for user, plain, raw in articles(month):
            if user:
                by[user].append((plain, raw))
        groups[month] = by
    both = sorted(set(groups[a]) & set(groups[b]))
    rows = [(profile(groups[a][u]), profile(groups[b][u])) for u in both]
    if not rows:
        print("両方の月に投稿した著者が見つかりません", file=sys.stderr)
        return
    print(f"両方の月に投稿した著者: {len(rows)}人\n")
    for i, name in enumerate(COLS):
        xs = [r[0][i] for r in rows]
        ys = [r[1][i] for r in rows]
        up = sum(1 for x, y in zip(xs, ys) if y > x)
        print(f"{name:<14}{a} {statistics.fmean(xs):>9.4f} -> {b} "
              f"{statistics.fmean(ys):>9.4f}  差 {statistics.fmean(ys) - statistics.fmean(xs):>+9.4f}"
              f"  上げた人 {up / len(rows) * 100:.0f}%")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--months", help="YYYY-MM をカンマ区切りで")
    ap.add_argument("--within", nargs=2, metavar=("A", "B"))
    ap.add_argument("--weekly", nargs=2, metavar=("FROM", "TO"),
                    help="週ごとに出す(YYYY-MM YYYY-MM)")
    ap.add_argument("--min-articles", type=int, default=300)
    ap.add_argument("-n", type=int, default=3000)
    ap.add_argument("--md", action="store_true")
    args = ap.parse_args()
    if args.weekly:
        run_weekly(*args.weekly, args.min_articles, args.md)
    elif args.within:
        run_within(*args.within)
    elif args.months:
        run_months([m.strip() for m in args.months.split(",")], args.n, args.md)
    else:
        ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
