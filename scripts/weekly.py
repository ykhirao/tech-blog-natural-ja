#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""週ごとに指標を出す。月次では見えないものを見るため。

月の区切りは分析上の都合であって、変化がそこで起きる理由はない。
実際、引用と箇条書きの入れ子は月次だと「2026年3月に跳ねた」ように
見えたが、週次で測ると2月上旬から連続して動いていた。

**月次で何かを見つけたら、週次で確かめる。**

metrics_YYYY-MM.jsonl を読んで created_at で週にまとめる。
build_dataset.py を通した月だけが対象。

使い方:
    ./scripts/weekly.py --from 2026-01 --to 2026-06
    ./scripts/weekly.py --from 2025-10 --field ten_per_sentence
    ./scripts/weekly.py --from 2026-01 --to 2026-06 --md
"""

from __future__ import annotations

import argparse
import datetime
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROC = ROOT / "data" / "processed"

FIELDS = {
    "nominal_ending_ratio": ("体言止め", "{:.3f}"),
    "ten_per_sentence": ("読点/文", "{:.3f}"),
    "burstiness_mora": ("文長のばらつき", "{:.3f}"),
    "kanji_ratio": ("漢字率", "{:.3f}"),
    "chars_body": ("地の文字数", "{:,.0f}"),
    "mtld": ("MTLD", "{:.2f}"),
    "bold_per_1k": ("太字/千字", "{:.2f}"),
}

# この本数に満たない週は出さない。年末年始や取得の切れ目で薄い週ができる。
MIN_ARTICLES = 300


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--from", dest="since", required=True, help="開始月 (例: 2026-01)")
    ap.add_argument("--to", dest="until", help="終了月 (省略で最後まで)")
    ap.add_argument("--field", action="append", default=[],
                    choices=list(FIELDS), help="出す指標(複数可)")
    ap.add_argument("--min-articles", type=int, default=MIN_ARTICLES)
    ap.add_argument("--md", action="store_true")
    args = ap.parse_args()

    fields = args.field or ["nominal_ending_ratio", "ten_per_sentence",
                            "burstiness_mora", "chars_body"]

    months = sorted(p.stem[8:] for p in PROC.glob("metrics_????-??.jsonl"))
    months = [m for m in months if m >= args.since]
    if args.until:
        months = [m for m in months if m <= args.until]
    if not months:
        print("対象の月がありません。build_dataset.py を先に実行してください",
              file=sys.stderr)
        return 1

    weeks: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for m in months:
        for line in (PROC / f"metrics_{m}.jsonl").open(encoding="utf-8"):
            r = json.loads(line)
            c = r.get("created_at")
            if not c:
                continue
            try:
                d = datetime.date.fromisoformat(c[:10])
            except ValueError:
                continue
            weeks[d.isocalendar()[:2]].append(r)

    rows = []
    for key in sorted(weeks):
        rs = weeks[key]
        if len(rs) < args.min_articles:
            continue
        start = datetime.date.fromisocalendar(key[0], key[1], 1)
        label = f"{key[0]}-W{key[1]:02d}"
        vals = {}
        for f in fields:
            v = [r[f] for r in rs if isinstance(r.get(f), (int, float))]
            vals[f] = statistics.median(v) if v else None
        rows.append((label, start, len(rs), vals))

    if not rows:
        print("条件に合う週がありません", file=sys.stderr)
        return 1

    heads = [FIELDS[f][0] for f in fields]
    if args.md:
        print("| 週 | 開始日 | 記事数 | " + " | ".join(heads) + " |")
        print("|----|-------|-------|" + "|".join(["---"] * len(fields)) + "|")
        for label, start, n, vals in rows:
            cells = [FIELDS[f][1].format(vals[f]) if vals[f] is not None else "—"
                     for f in fields]
            print(f"| {label} | {start} | {n:,} | " + " | ".join(cells) + " |")
    else:
        print(f"\n{'週':<11}{'開始日':<12}{'記事数':>8}"
              + "".join(f"{h:>15}" for h in heads))
        print("-" * (31 + 15 * len(fields)))
        for label, start, n, vals in rows:
            line = f"{label:<11}{str(start):<12}{n:>8,}"
            for f in fields:
                line += (f"{FIELDS[f][1].format(vals[f]):>15}"
                         if vals[f] is not None else f"{'—':>15}")
            print(line)

    print(f"\n{len(rows)}週 / {args.min_articles}本未満の週は除外",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
