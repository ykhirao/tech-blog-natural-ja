#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""12月のずれが「年末に向かう連続変化」なのか「12月だけの逸脱」なのかを分ける。

[docs/advent-calendar.md] は2022年の8月→11月→12月が単調に動くので
「年末に向けた連続的な変化」と書いた。ただし**翌1月を見ていない。**

12月だけの逸脱なら、1月に戻る。年末に向かう変化なら、戻らない。
地の文の英字は3年とも12月に下がって1月に戻っていた
([docs/english-in-prose.md])。他の指標でも同じことが起きているかを見る。

測り方: 各年について 12月 - (11月 + 翌1月)/2 を出す。これを**戻り幅**と呼ぶ。
12月だけの逸脱ならゼロから離れ、連続変化なら11月と1月の中間に来るのでゼロに近い。

大きさを比べられるよう、各指標の**12月以外の月のばらつき(SD)**で割る。
何年も同じ向きに出れば季節性と見てよい。

--all-months は同じ計算を12か月ぶん回す。12月だけが特別なのかを確かめる。

使い方:
    ./scripts/december_effect.py
    ./scripts/december_effect.py --regulars
    ./scripts/december_effect.py --all-months
    ./scripts/december_effect.py --years 2016-2025 --md
"""

from __future__ import annotations

import argparse
import functools
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROC = ROOT / "data" / "processed"

FIELDS = [
    ("chars_body", "地の文字数"),
    ("nominal_ending_ratio", "体言止め"),
    ("ten_per_sentence", "読点/文"),
    ("kanji_ratio", "漢字率"),
    ("mtld", "MTLD"),
    ("burstiness_mora", "メリハリ"),
    ("mean_sentence_chars", "平均文長"),
    ("bold_per_1k", "太字/千字"),
    ("list_ratio", "箇条書き"),
    ("desumasu_ratio", "ですます"),
    ("images_per_1k", "画像/千字"),
    ("n_headings", "見出し数"),
]


@functools.lru_cache(maxsize=None)
def authors(month: str) -> frozenset[str]:
    p = PROC / f"metrics_{month}.jsonl"
    if not p.exists():
        return frozenset()
    out = set()
    with p.open(encoding="utf-8") as f:
        for line in f:
            u = json.loads(line).get("user_id")
            if u:
                out.add(u)
    return frozenset(out)


@functools.lru_cache(maxsize=None)
def month_mean(month: str, only: frozenset[str] | None = None) -> dict[str, float]:
    p = PROC / f"metrics_{month}.jsonl"
    if not p.exists():
        return {}
    acc: dict[str, list[float]] = {k: [] for k, _ in FIELDS}
    with p.open(encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if only is not None and r.get("user_id") not in only:
                continue
            for k, _ in FIELDS:
                v = r.get(k)
                if v is not None:
                    acc[k].append(float(v))
    return {k: statistics.fmean(v) for k, v in acc.items() if v}


def gap_for(target: int, k: str, years: list[int],
            reg_month: str | None) -> list[float]:
    """その月と、前後の月の平均との差を年ごとに出す。"""
    out = []
    for y in years:
        py, pm = (y - 1, 12) if target == 1 else (y, target - 1)
        ny, nm = (y + 1, 1) if target == 12 else (y, target + 1)
        reg = authors(f"{y}-{reg_month}") if reg_month else None
        cur = month_mean(f"{y}-{target:02d}", reg).get(k)
        prev = month_mean(f"{py}-{pm:02d}", reg).get(k)
        nxt = month_mean(f"{ny}-{nm:02d}", reg).get(k)
        if cur is None or prev is None or nxt is None:
            continue
        out.append(cur - (prev + nxt) / 2)
    return out


def show_all_months(years: list[int], md: bool) -> None:
    """12か月ぶん。各指標について、前後の月から最も離れる月を探す。"""
    # 基準のばらつきは、その指標の全月平均の散らばりを使う
    base: dict[str, list[float]] = {k: [] for k, _ in FIELDS}
    for y in years:
        for m in range(1, 13):
            for k, v in month_mean(f"{y}-{m:02d}").items():
                base[k].append(v)
    sd = {k: statistics.pstdev(v) for k, v in base.items() if len(v) > 1}

    header = [f"{m}月" for m in range(1, 13)]
    if md:
        print("| 指標 | " + " | ".join(header) + " |")
        print("|---|" + "|".join(["---"] * 12) + "|")
    else:
        print(f"{'指標':<14}" + "".join(f"{h:>7}" for h in header))
        print("-" * (14 + 7 * 12))
    for k, label in FIELDS:
        if not sd.get(k):
            continue
        cells = []
        for m in range(1, 13):
            g = gap_for(m, k, years, None)
            cells.append(statistics.fmean(g) / sd[k] if g else None)
        if md:
            print(f"| {label} | " + " | ".join(
                f"{c:+.2f}" if c is not None else "-" for c in cells) + " |")
        else:
            print(f"{label:<14}" + "".join(
                f"{c:>+7.2f}" if c is not None else f"{'-':>7}" for c in cells))


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--years", default="2014-2025", help="例 2016-2025")
    ap.add_argument("--regulars", action="store_true",
                    help="その年の8月にも投稿した著者だけで測る")
    ap.add_argument("--all-months", action="store_true",
                    help="12か月ぶん回して、12月だけが特別かを見る")
    ap.add_argument("--md", action="store_true")
    args = ap.parse_args()

    lo, hi = (int(x) for x in args.years.split("-"))
    years = list(range(lo, hi + 1))

    if args.all_months:
        show_all_months(years, args.md)
        return 0

    # 12月以外の月のばらつき。基準にする
    base: dict[str, list[float]] = {k: [] for k, _ in FIELDS}
    for y in years:
        for m in range(1, 13):
            if m == 12:
                continue
            for k, v in month_mean(f"{y}-{m:02d}").items():
                base[k].append(v)
    sd = {k: statistics.pstdev(v) for k, v in base.items() if len(v) > 1}

    rows = []
    for k, label in FIELDS:
        gaps = []
        for y in years:
            reg = authors(f"{y}-08") if args.regulars else None
            dec = month_mean(f"{y}-12", reg).get(k)
            nov = month_mean(f"{y}-11", reg).get(k)
            jan = month_mean(f"{y + 1}-01", reg).get(k)
            if dec is None or nov is None or jan is None:
                continue
            gaps.append(dec - (nov + jan) / 2)
        if not gaps or not sd.get(k):
            continue
        z = [g / sd[k] for g in gaps]
        same = sum(1 for x in z if x > 0)
        rows.append((label, len(z), statistics.fmean(z), max(same, len(z) - same)))

    rows.sort(key=lambda r: -abs(r[2]))
    if args.md:
        print("| 指標 | 年数 | 戻り幅(SD) | 同じ向き |")
        print("|---|---|---|---|")
        for lb, n, m, same in rows:
            print(f"| {lb} | {n} | {m:+.2f} | {same}/{n} |")
    else:
        print(f"12月 - (11月 + 翌1月)/2 を、12月以外の月のばらつきで割った値\n")
        print(f"{'指標':<14}{'年数':>5}{'戻り幅(SD)':>12}{'同じ向き':>10}")
        print("-" * 43)
        for lb, n, m, same in rows:
            print(f"{lb:<14}{n:>5}{m:>+12.2f}{f'{same}/{n}':>10}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
