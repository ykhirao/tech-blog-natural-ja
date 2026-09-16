#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""同じ人が書き方を変えたのか、書き手が入れ替わったのかを分ける。

2時点の両方に投稿した著者だけを取り、**本人の中での変化**を見る。
全体の差が本人内にも残っていれば、同じ人が変えたと言える。
本人内で動いていなければ、書き手の構成が変わっただけになる。

実際これで指標が3つに分かれた(docs/within-author.md)。

  60〜67%  本人が変えた      地の文字数・読点・体言止め・文長のばらつき
  51〜53%  判定できない      漢字率・MTLD
  43〜49%  構成が変わった    太字・箇条書き・見出し数

「本人内で動いた割合」は、全体の変化と同じ向きに動いた著者の割合。
偶然なら50%になる。

使い方:
    ./scripts/within_author.py 2026-02 2026-08
    ./scripts/within_author.py 2021-08 2023-08 --md
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

FIELDS = [
    ("chars_body", "地の文字数", "{:,.0f}"),
    ("ten_per_sentence", "読点/文", "{:.3f}"),
    ("nominal_ending_ratio", "体言止め", "{:.3f}"),
    ("burstiness_mora", "文長のばらつき", "{:.3f}"),
    ("kanji_ratio", "漢字率", "{:.3f}"),
    ("mtld", "MTLD", "{:.2f}"),
    ("list_ratio", "箇条書き", "{:.3f}"),
    ("n_headings", "見出し数", "{:.0f}"),
    ("bold_per_1k", "太字/千字", "{:.3f}"),
]

# この人数に満たないと割合が安定しない
MIN_AUTHORS = 100


def load(month: str) -> list[dict]:
    f = PROC / f"metrics_{month}.jsonl"
    if not f.exists():
        print(f"{f} がありません。build_dataset.py を先に実行してください",
              file=sys.stderr)
        raise SystemExit(1)
    return [json.loads(l) for l in f.open(encoding="utf-8") if l.strip()]


def med(rows: list[dict], field: str) -> float | None:
    v = [r[field] for r in rows if isinstance(r.get(field), (int, float))]
    return statistics.median(v) if v else None


def by_author(rows: list[dict]) -> dict[str, list[dict]]:
    d: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        u = r.get("user_id")
        if u:
            d[u].append(r)
    return d


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("before", help="前の月 (例: 2026-02)")
    ap.add_argument("after", help="後の月 (例: 2026-08)")
    ap.add_argument("--md", action="store_true")
    args = ap.parse_args()

    A, B = load(args.before), load(args.after)
    ba, bb = by_author(A), by_author(B)
    common = set(ba) & set(bb)
    if len(common) < MIN_AUTHORS:
        print(f"両月に投稿した著者が {len(common)}人 しかいません "
              f"({MIN_AUTHORS}人未満だと割合が安定しません)", file=sys.stderr)
        return 1

    rows = []
    for k, lbl, fmt in FIELDS:
        x, y = med(A, k), med(B, k)
        if x is None or y is None:
            continue
        diffs = []
        for u in common:
            a, b = med(ba[u], k), med(bb[u], k)
            if a is not None and b is not None:
                diffs.append(b - a)
        if not diffs:
            continue
        overall = y - x
        # 全体が動いていない指標では向きを決められない
        direction = 1 if overall > 0 else (-1 if overall < 0 else 0)
        same = (sum(1 for v in diffs if v * direction > 0) / len(diffs) * 100
                if direction else None)
        rows.append((lbl, overall, statistics.median(diffs), same, len(diffs)))

    # 本人内で動いた割合が高い順
    rows.sort(key=lambda r: (r[3] is None, -(r[3] or 0)))

    print(f"両月に投稿した著者: {len(common):,}人\n")
    if args.md:
        print("| 指標 | 全体の差 | 本人内の差 | 本人内で動いた割合 |")
        print("|------|---------|----------|-----------------|")
        for lbl, o, m, same, n in rows:
            s = f"{same:.0f}%" if same is not None else "—"
            print(f"| {lbl} | {o:+.3f} | {m:+.3f} | {s} |")
    else:
        print(f"{'指標':16}{'全体の差':>12}{'本人内の差':>12}"
              f"{'本人内で動いた割合':>18}")
        print("-" * 58)
        for lbl, o, m, same, n in rows:
            s = f"{same:.0f}%" if same is not None else "—"
            print(f"{lbl:16}{o:>+12.3f}{m:>+12.3f}{s:>17}")

    print("\n偶然なら50%。60%以上なら本人が変えた、"
          "50%を下回れば書き手の構成が変わったと読む。", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
