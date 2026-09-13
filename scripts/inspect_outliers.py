#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""指標の分布と外れ値を眺めるための道具。

指標スクリプトを直すための診断用。ある指標が極端な値を取る記事を実際に
目視して、前処理のバグなのか本当にそういう記事なのかを切り分ける。

使い方:
    ./scripts/inspect_outliers.py metrics.jsonl --dist
    ./scripts/inspect_outliers.py metrics.jsonl --field burstiness_mora --low 10
    ./scripts/inspect_outliers.py metrics.jsonl --field chars_body --low 20 --show-url
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path

SKIP = {"id", "user_id", "created_at", "title", "url"}


def quantile(xs: list[float], q: float) -> float:
    if not xs:
        return float("nan")
    s = sorted(xs)
    i = q * (len(s) - 1)
    lo, hi = math.floor(i), math.ceil(i)
    if lo == hi:
        return s[lo]
    return s[lo] + (s[hi] - s[lo]) * (i - lo)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("metrics", help="metrics.py が出した JSONL")
    ap.add_argument("--dist", action="store_true", help="全指標の分布を出す")
    ap.add_argument("--field", help="この指標の外れ値を見る")
    ap.add_argument("--low", type=int, default=0, help="下位N件を表示")
    ap.add_argument("--high", type=int, default=0, help="上位N件を表示")
    ap.add_argument("--null", action="store_true", help="null になった記事を数える")
    ap.add_argument("--show-url", action="store_true", help="記事URLを出す")
    args = ap.parse_args()

    rows = [json.loads(l) for l in Path(args.metrics).open(encoding="utf-8") if l.strip()]
    if not rows:
        print("データが空です")
        return 1
    print(f"記事数: {len(rows):,}\n")

    if args.dist or args.null:
        fields = [k for k in rows[0] if k not in SKIP]
        print(f"{'指標':<28} {'有効':>7} {'null':>6} {'p05':>9} {'p50':>9} {'p95':>9}")
        print("-" * 76)
        for f in fields:
            vals = [r.get(f) for r in rows]
            nums = [v for v in vals if isinstance(v, (int, float)) and not isinstance(v, bool)]
            nulls = sum(1 for v in vals if v is None)
            if not nums:
                bools = [v for v in vals if isinstance(v, bool)]
                if bools:
                    print(f"{f:<28} {len(bools):>7} {nulls:>6} {'':>9} {sum(bools)/len(bools):>9.3f} {'(真の割合)':>9}")
                continue
            print(f"{f:<28} {len(nums):>7} {nulls:>6} "
                  f"{quantile(nums, .05):>9.3f} {quantile(nums, .50):>9.3f} {quantile(nums, .95):>9.3f}")
        print()

    if args.field:
        f = args.field
        have = [r for r in rows if isinstance(r.get(f), (int, float)) and not isinstance(r.get(f), bool)]
        have.sort(key=lambda r: r[f])
        nulls = [r for r in rows if r.get(f) is None]
        print(f"[{f}] 有効 {len(have):,} / null {len(nulls):,}")
        if have:
            vals = [r[f] for r in have]
            print(f"  平均 {statistics.fmean(vals):.3f} / 中央 {quantile(vals, .5):.3f} "
                  f"/ 最小 {vals[0]:.3f} / 最大 {vals[-1]:.3f}\n")

        def show(label: str, subset: list[dict]) -> None:
            if not subset:
                return
            print(f"--- {label} ---")
            for r in subset:
                url = r.get("url") or f"https://qiita.com/{r.get('user_id')}/items/{r.get('id')}"
                extra = f"  chars={r.get('chars_body')} sent={r.get('n_sentences')}"
                print(f"  {r[f]:>10.3f}{extra}")
                if args.show_url:
                    print(f"             {url}")

        if args.low:
            show(f"下位 {args.low}", have[: args.low])
        if args.high:
            show(f"上位 {args.high}", have[-args.high:][::-1])
        if nulls and not (args.low or args.high):
            print(f"  null の例: {[r.get('id') for r in nulls[:5]]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
