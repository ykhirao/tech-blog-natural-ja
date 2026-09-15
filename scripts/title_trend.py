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

# タイトルに出る数字の用法。上から順に当て、最初に当たったものを採る。
# 順序に意味がある(「2026-08-06」は日付であってバージョンではない)。
DIGIT_KINDS: list[tuple[str, re.Pattern]] = [
    ("日付", re.compile(r"20\d{2}[-/年]\d{1,2}[-/月]|\d{1,2}月\d{1,2}日")),
    ("連載回", re.compile(r"第\s*\d+\s*[回話章部]|[(（]\s*\d+\s*[)）]\s*$|\d+\s*回目")),
    ("版番号", re.compile(r"v\.?\d|\d+\.\d+(\.\d+)?|[A-Za-z]\s*\d{1,2}\b(?!つ)")),
    # 「N個の◯◯」のように、その数が記事の構成を表すものだけを採る。
    # 「98個溜まった」のような文中の数量は数え上げではない。
    ("数え上げ", re.compile(
        r"\d+\s*(?:つ|個|種類|パターン|ステップ|ポイント)の\S|"
        r"\d+\s*選|"
        r"\d+\s*(?:つ|個)\s*[のを]?\s*(?:方法|理由|コツ|技|Tips|ルール|観点|ポイント)")),
    ("所要時間", re.compile(r"\d+\s*(?:分|秒|時間|日)で")),
]


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
        **{k: sum(1 for t in titles if kind_of(t) == k) / len(titles) * 100
           for k, _ in DIGIT_KINDS},
    }


def kind_of(title: str) -> str | None:
    """タイトルの数字の用法。数字がなければ None、どれにも当たらなければ「その他」。"""
    if not DIGIT.search(title):
        return None
    for name, rx in DIGIT_KINDS:
        if rx.search(title):
            return name
    return "その他"


COLS = [("n", "記事数", "{:,}"), ("chars", "題の字数", "{:.0f}"),
        ("kanji", "題の漢字率", "{:.3f}"), ("symbol", "記号%", "{:.1f}"),
        ("digit", "数字%", "{:.1f}")]

# --kinds で出す列。数字の用法の内訳。
KIND_COLS = [("digit", "数字%", "{:.1f}")] + [
    (k, k, "{:.2f}") for k, _ in DIGIT_KINDS]


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--monthly", action="store_true", help="月ごとに出す")
    ap.add_argument("--from", dest="since", help="この月以降 (例: 2024-01)")
    ap.add_argument("--min-articles", type=int, default=200)
    ap.add_argument("--kinds", action="store_true",
                    help="数字の用法の内訳を出す")
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

    cols = KIND_COLS if args.kinds else COLS
    if args.md:
        print("| 期間 | " + " | ".join(l for _, l, _ in cols) + " |")
        print("|------|" + "|".join(["---"] * len(cols)) + "|")
        for label, st in rows:
            print(f"| {label} | "
                  + " | ".join(fmt.format(st[k]) for k, _, fmt in cols) + " |")
    else:
        w = max(len(l) for l, _ in rows) + 2
        print(f"\n{'期間':<{w}}" + "".join(f"{l:>10}" for _, l, _ in cols))
        print("-" * (w + 10 * len(cols)))
        for label, st in rows:
            print(f"{label:<{w}}"
                  + "".join(f"{fmt.format(st[k]):>10}" for k, _, fmt in cols))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
