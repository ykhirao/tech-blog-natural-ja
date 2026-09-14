#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""期間をまたいだ指標の推移を表と簡易グラフで出す。

「いつから変わり始めたか」を見るための道具。形態素解析を使わないので
軽く、何度回してもクラッシュしない。

使い方:
    ./scripts/timeline.py
    ./scripts/timeline.py --field kanji_ratio --chart
    ./scripts/timeline.py --md > docs/table.md
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
    ("kanji_ratio", "漢字率", "{:.3f}"),
    ("burstiness_mora", "burstiness", "{:.3f}"),
    ("nominal_ending_ratio", "体言止め", "{:.3f}"),
    ("bold_per_1k", "太字/千字", "{:.2f}"),
    ("list_ratio", "箇条書き", "{:.3f}"),
    ("ten_per_sentence", "読点/文", "{:.3f}"),
    ("mtld", "MTLD", "{:.2f}"),
    ("has_matome_heading", "まとめ見出し", "{:.3f}"),
]


def median_of(rows: list[dict], field: str) -> float | None:
    vals: list[float] = []
    for r in rows:
        v = r.get(field)
        if isinstance(v, bool):
            vals.append(1.0 if v else 0.0)
        elif isinstance(v, (int, float)):
            vals.append(float(v))
    return statistics.median(vals) if vals else None


def days_in(year: int, month: int) -> int:
    import calendar

    return calendar.monthrange(year, month)[1]


def coverage(label: str, rows: list[dict]) -> tuple[int, int]:
    """その月の何日分が入っているかを返す (収録日数, 月の日数)。

    パイロットで2日だけ取った月などが、月全体のデータと同じ顔で
    推移の表に並ぶと誤解を招く。実際 2024-12 は2日分しかない。
    """
    got = {r.get("created_at", "")[:10] for r in rows if r.get("created_at")}
    y, m = int(label[:4]), int(label[5:7])
    return len(got), days_in(y, m)


def load_months(pattern: str = "metrics_*.jsonl") -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for p in sorted(PROC.glob(pattern)):
        label = p.stem.replace("metrics_", "")
        # nonai_ などの派生は除く。素の年月だけを対象にする。
        if not (len(label) == 7 and label[4] == "-" and label[:4].isdigit()):
            continue
        out[label] = [json.loads(l) for l in p.open(encoding="utf-8") if l.strip()]
    return dict(sorted(out.items()))


def sparkline(values: list[float | None], width: int = 8) -> str:
    """値の推移を記号の並びで表す。欠測は空白。"""
    nums = [v for v in values if v is not None]
    if len(nums) < 2:
        return ""
    lo, hi = min(nums), max(nums)
    blocks = "▁▂▃▄▅▆▇█"
    out = []
    for v in values:
        if v is None:
            out.append(" ")
        elif hi == lo:
            out.append(blocks[0])
        else:
            out.append(blocks[min(len(blocks) - 1, int((v - lo) / (hi - lo) * (len(blocks) - 1)))])
    return "".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--field", help="この指標だけ詳しく出す")
    ap.add_argument("--md", action="store_true", help="Markdown 表で出力")
    ap.add_argument("--chart", action="store_true", help="推移を記号で表示")
    ap.add_argument("--min-articles", type=int, default=0,
                    help="この件数に満たない月を隠す(空の月が並ぶのを防ぐ)")
    ap.add_argument("--from", dest="since", help="この月以降だけ (例: 2015-01)")
    args = ap.parse_args()

    data = load_months()
    if not data:
        print("data/processed にデータがありません")
        return 1

    months = list(data)
    # 182か月あると 2011年の空の月が延々と並ぶので、絞り込めるようにする
    if args.since:
        months = [m for m in months if m >= args.since]
    if args.min_articles:
        months = [m for m in months if len(data[m]) >= args.min_articles]
    if not months:
        print("条件に合う月がありません")
        return 1

    stats = {m: {f: median_of(rows, f) for f, _, _ in FIELDS} for m, rows in data.items()}

    if args.field:
        f = args.field
        lbl = next((l for k, l, _ in FIELDS if k == f), f)
        print(f"## {lbl} ({f})\n")
        vals = [stats[m].get(f) for m in months]
        for m, v in zip(months, vals):
            bar = ""
            nums = [x for x in vals if x is not None]
            if v is not None and nums and max(nums) > min(nums):
                n = int((v - min(nums)) / (max(nums) - min(nums)) * 40)
                bar = "█" * max(1, n)
            shown = f"{v:.4f}" if v is not None else "—"
            print(f"  {m}  {shown:>10}  {bar}")
        return 0

    if args.md:
        print("| 月 | 記事数 | " + " | ".join(l for _, l, _ in FIELDS) + " |")
        print("|----|-------|" + "|".join(["------"] * len(FIELDS)) + "|")
        for m in months:
            cells = []
            for f, _, fmt in FIELDS:
                v = stats[m].get(f)
                cells.append(fmt.format(v) if v is not None else "—")
            print(f"| {m} | {len(data[m]):,} | " + " | ".join(cells) + " |")
        return 0

    w = max(len(m) for m in months) + 2
    hdr = f"{'月':<{w}}{'記事数':>8}" + "".join(f"{l:>13}" for _, l, _ in FIELDS)
    print(hdr)
    print("-" * len(hdr))
    partial: list[str] = []
    for m in months:
        got, total = coverage(m, data[m])
        mark = "" if got >= total else " *"
        if mark:
            partial.append(f"{m} ({got}/{total}日)")
        line = f"{m + mark:<{w}}{len(data[m]):>8,}"
        for f, _, fmt in FIELDS:
            v = stats[m].get(f)
            line += f"{fmt.format(v):>13}" if v is not None else f"{'—':>13}"
        print(line)
    if partial:
        print(f"\n* 月の一部しか取得していない: {', '.join(partial)}")
        print("  月全体のデータと同じようには比較できない。")

    if args.chart:
        print(f"\n{'指標':<14}{'推移':<{len(months)+2}}  最小 → 最大")
        print("-" * 52)
        for f, lbl, fmt in FIELDS:
            vals = [stats[m].get(f) for m in months]
            nums = [v for v in vals if v is not None]
            if len(nums) < 2:
                continue
            print(f"{lbl:<14}{sparkline(vals):<{len(months)+2}}  "
                  f"{fmt.format(min(nums))} → {fmt.format(max(nums))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
