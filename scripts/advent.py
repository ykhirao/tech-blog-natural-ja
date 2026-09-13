#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""12月(アドベントカレンダー)の記事を、書き手の層で分けて分析する。

12月は6月の1.5〜2.2倍の記事数があり、普段書かない人が書く。
そのため文体の差が出ても「AIの影響」なのか「書き手の層が違うから」なのか
区別がつかない。これは交絡になる。

そこで同じ年の他の月にも投稿しているかで常連・非常連を分けて比べる。
非常連の文章は「普段書かない人の日本語」であり、既存のコーパスにない層。

使い方:
    ./scripts/advent.py --year 2022 --compare 2022-08,2022-11
    ./scripts/advent.py --year 2022 --md
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROC = ROOT / "data" / "processed"

FIELDS = [
    ("chars_body", "地の文字数", "{:.0f}"),
    ("burstiness_mora", "文長ばらつき", "{:.3f}"),
    ("kanji_ratio", "漢字率", "{:.3f}"),
    ("nominal_ending_ratio", "体言止め", "{:.3f}"),
    ("ten_per_sentence", "読点/文", "{:.3f}"),
    ("mtld", "MTLD", "{:.2f}"),
    ("n_headings", "見出し数", "{:.0f}"),
    ("bold_per_1k", "太字/千字", "{:.2f}"),
]


def load(label: str) -> list[dict]:
    p = PROC / f"metrics_{label}.jsonl"
    if not p.exists():
        return []
    return [json.loads(l) for l in p.open(encoding="utf-8") if l.strip()]


def med(rows: list[dict], field: str) -> float | None:
    vals: list[float] = []
    for r in rows:
        v = r.get(field)
        if isinstance(v, bool):
            vals.append(1.0 if v else 0.0)
        elif isinstance(v, (int, float)):
            vals.append(float(v))
    return statistics.median(vals) if vals else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", required=True, help="対象年 (例: 2022)")
    ap.add_argument("--compare", default="",
                    help="常連判定に使う他の月 (例: 2022-08,2022-11)")
    ap.add_argument("--md", action="store_true")
    args = ap.parse_args()

    dec = load(f"{args.year}-12")
    if not dec:
        print(f"{args.year}-12 のデータがありません。先に build_dataset.py を実行してください。")
        return 1

    # 常連の判定: 指定した他の月にも投稿している著者
    others: set[str] = set()
    other_months = [m.strip() for m in args.compare.split(",") if m.strip()]
    for m in other_months:
        for r in load(m):
            uid = r.get("user_id")
            if uid:
                others.add(uid)

    if not others:
        print("--compare で他の月を指定してください(常連の判定に要ります)")
        return 1

    regular = [r for r in dec if r.get("user_id") in others]
    spot = [r for r in dec if r.get("user_id") not in others]

    print(f"{args.year}年12月: {len(dec):,}本")
    print(f"  常連 ({'/'.join(other_months)} にも投稿): {len(regular):,}本 "
          f"({len(regular)/len(dec)*100:.1f}%)")
    print(f"  非常連 (12月のみ): {len(spot):,}本 ({len(spot)/len(dec)*100:.1f}%)\n")

    if args.md:
        print("| 指標 | 12月全体 | 常連 | 非常連 | 差 |")
        print("|------|---------|------|-------|-----|")
    else:
        print(f"{'指標':<14}{'12月全体':>10}{'常連':>10}{'非常連':>10}{'差':>10}")
        print("-" * 56)

    for f, lbl, fmt in FIELDS:
        a, b, c = med(dec, f), med(regular, f), med(spot, f)
        if a is None:
            continue
        diff = (c - b) if (b is not None and c is not None) else None
        if args.md:
            d = fmt.format(diff) if diff is not None else "—"
            print(f"| {lbl} | {fmt.format(a)} | "
                  f"{fmt.format(b) if b else '—'} | {fmt.format(c) if c else '—'} | {d} |")
        else:
            ds = fmt.format(diff) if diff is not None else "—"
            print(f"{lbl:<14}{fmt.format(a):>10}{fmt.format(b) if b else '—':>10}"
                  f"{fmt.format(c) if c else '—':>10}{ds:>10}")

    # 他の月との比較(季節性の確認)
    if other_months:
        print(f"\n## 他の月との比較(中央値)")
        hdr = f"{'指標':<14}" + "".join(f"{m:>12}" for m in other_months) + f"{args.year+'-12':>12}"
        print(hdr)
        print("-" * len(hdr))
        for f, lbl, fmt in FIELDS:
            line = f"{lbl:<14}"
            for m in other_months:
                v = med(load(m), f)
                line += f"{fmt.format(v) if v is not None else '—':>12}"
            v = med(dec, f)
            line += f"{fmt.format(v) if v is not None else '—':>12}"
            print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
