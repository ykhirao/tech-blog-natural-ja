#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""記事タイトルの推移を測る。

本文の指標は189か月そろっているが、タイトルは測っていなかった。
本文とは別の時期に動いている可能性がある。

タイトルは本文と違って、**読まれるために書かれる**。検索やタイムラインで
目に入る部分なので、本文とは別の力がかかる。実際、別の時期に動いていた。

測るもの:
  文字数     長くなっているか
  漢字率     本文と同じ方向か
  記号       【】「」などの装飾を使うか
  数字       「3つの方法」のような数え上げか

使い方:
    ./scripts/title_trend.py
    ./scripts/title_trend.py --monthly --from 2024-01
    ./scripts/title_trend.py --md
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROC = ROOT / "data" / "processed"

KANJI = re.compile(r"[一-鿿]")
# タイトルの装飾に使われる記号。半角全角の両方を見る。
SYMBOL = re.compile(r"[【】「」『』\[\]（）()〜~！!？?#|｜]")
DIGIT = re.compile(r"\d")


def load(month: str) -> list[dict]:
    f = PROC / f"metrics_{month}.jsonl"
    if not f.exists():
        return []
    return [json.loads(l) for l in f.open(encoding="utf-8") if l.strip()]


def titles_of(rows: list[dict]) -> list[str]:
    return [t for t in (r.get("title") or "" for r in rows) if t]


def stats_of(titles: list[str]) -> dict:
    if not titles:
        return {}
    return {
        "n": len(titles),
        "chars": statistics.median(len(t) for t in titles),
        "kanji": statistics.median(
            len(KANJI.findall(t)) / max(1, len(t)) for t in titles),
        "symbol": sum(1 for t in titles if SYMBOL.search(t)) / len(titles) * 100,
        "digit": sum(1 for t in titles if DIGIT.search(t)) / len(titles) * 100,
    }


COLS = [("n", "記事数", "{:,}"), ("chars", "字数", "{:.0f}"),
        ("kanji", "漢字率", "{:.3f}"), ("symbol", "記号%", "{:.1f}"),
        ("digit", "数字%", "{:.1f}")]


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--monthly", action="store_true", help="月ごとに出す")
    ap.add_argument("--from", dest="since", help="この月以降 (例: 2024-01)")
    ap.add_argument("--min-articles", type=int, default=200)
    ap.add_argument("--md", action="store_true")
    args = ap.parse_args()

    months = sorted(p.stem[8:] for p in PROC.glob("metrics_????-??.jsonl"))
    if args.since:
        months = [m for m in months if m >= args.since]
    if not months:
        print("data/processed にデータがありません", file=sys.stderr)
        return 1

    rows: list[tuple[str, dict]] = []
    if args.monthly:
        for m in months:
            rs = load(m)
            if len(rs) < args.min_articles:
                continue
            rows.append((m, stats_of(titles_of(rs))))
    else:
        by: dict[str, list[str]] = defaultdict(list)
        for m in months:
            rs = load(m)
            if len(rs) < args.min_articles:
                continue
            by[m[:4]].extend(titles_of(rs))
        for y in sorted(by):
            rows.append((y, stats_of(by[y])))

    if not rows:
        print("条件に合う月がありません", file=sys.stderr)
        return 1

    if args.md:
        print("| 期間 | " + " | ".join(l for _, l, _ in COLS) + " |")
        print("|------|" + "|".join(["---"] * len(COLS)) + "|")
        for label, s in rows:
            print(f"| {label} | "
                  + " | ".join(fmt.format(s[k]) for k, _, fmt in COLS) + " |")
    else:
        w = max(len(l) for l, _ in rows) + 2
        print(f"\n{'期間':<{w}}" + "".join(f"{l:>10}" for _, l, _ in COLS))
        print("-" * (w + 10 * len(COLS)))
        for label, s in rows:
            print(f"{label:<{w}}"
                  + "".join(f"{fmt.format(s[k]):>10}" for k, _, fmt in COLS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
