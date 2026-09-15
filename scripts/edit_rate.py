#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""公開したあと記事を直しているかを測る。

Qiita API は `created_at` と `updated_at` を返す。これまで使っていなかったが、
**推敲したかどうか**の代理指標になる。

一度も更新されていない記事は、書いて出してそれきりということ。
文体の指標とは別の角度から書き方の変化が見える。

判定:
  未更新       created_at == updated_at
  即時修正     更新まで1時間未満(誤字直しなど)
  後日更新     1時間以上あと

生データを直接読むので、build_dataset.py を通していない月でも使える。

使い方:
    ./scripts/edit_rate.py
    ./scripts/edit_rate.py --monthly --from 2024-01
    ./scripts/edit_rate.py --md
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"

# 誤字直しと、あとから書き足したものを分ける境目。
QUICK_SECONDS = 3600


def scan(pattern: str) -> dict:
    n = same = quick = later = 0
    for f in sorted(RAW.glob(pattern)):
        for line in f.open(encoding="utf-8"):
            d = json.loads(line)
            c, u = d.get("created_at"), d.get("updated_at")
            if not c or not u:
                continue
            n += 1
            if c == u:
                same += 1
                continue
            try:
                dt = (datetime.fromisoformat(u) - datetime.fromisoformat(c)).total_seconds()
            except ValueError:
                continue
            if dt < QUICK_SECONDS:
                quick += 1
            else:
                later += 1
    if not n:
        return {}
    return {
        "n": n,
        "same": same / n * 100,
        "quick": quick / n * 100,
        "later": later / n * 100,
    }


COLS = [("n", "記事数", "{:,}"), ("same", "未更新%", "{:.1f}"),
        ("quick", "即時修正%", "{:.1f}"), ("later", "後日更新%", "{:.1f}")]


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--monthly", action="store_true",
                    help="月ごとに出す(既定は各年8月)")
    ap.add_argument("--from", dest="since", help="この月以降 (例: 2024-01)")
    ap.add_argument("--min-articles", type=int, default=200)
    ap.add_argument("--md", action="store_true")
    args = ap.parse_args()

    rows: list[tuple[str, dict]] = []
    if args.monthly:
        months = sorted({p.name[6:13] for p in RAW.glob("qiita_????-??-??.jsonl")})
        if args.since:
            months = [m for m in months if m >= args.since]
        for m in months:
            s = scan(f"qiita_{m}-*.jsonl")
            if s and s["n"] >= args.min_articles:
                rows.append((m, s))
    else:
        years = sorted({p.name[6:10] for p in RAW.glob("qiita_????-08-??.jsonl")})
        for y in years:
            s = scan(f"qiita_{y}-08-*.jsonl")
            if s and s["n"] >= args.min_articles:
                rows.append((y, s))

    if not rows:
        print("対象データがありません", file=sys.stderr)
        return 1

    if args.md:
        print("| 期間 | " + " | ".join(l for _, l, _ in COLS) + " |")
        print("|------|" + "|".join(["---"] * len(COLS)) + "|")
        for label, s in rows:
            print(f"| {label} | "
                  + " | ".join(fmt.format(s[k]) for k, _, fmt in COLS) + " |")
    else:
        w = max(len(l) for l, _ in rows) + 2
        print(f"\n{'期間':<{w}}" + "".join(f"{l:>11}" for _, l, _ in COLS))
        print("-" * (w + 11 * len(COLS)))
        for label, s in rows:
            print(f"{label:<{w}}"
                  + "".join(f"{fmt.format(s[k]):>11}" for k, _, fmt in COLS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
