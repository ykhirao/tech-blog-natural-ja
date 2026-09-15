#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""見出しの推移を測る。

本文とタイトルは測ったが、見出しは測っていなかった。
`split_markdown()` が `headings` として分けているので、そのまま使える。

見出しは本文とも タイトルとも違う。目次になり、読み飛ばす人の道しるべになる。
実際、本文とは別の時期に動いていた。

測るもの:
  個数       記事あたりいくつあるか
  長さ       1つあたりの文字数
  漢字率     本文と同じ方向か
  疑問形     「〜とは?」のような問いかけ
  階層       ## と ### のどちらを使うか

生データを直接読むので、build_dataset.py を通していない月でも使える。

使い方:
    ./scripts/heading_trend.py
    ./scripts/heading_trend.py --monthly --from 2024-01
    ./scripts/heading_trend.py --md
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"

sys.path.insert(0, str(ROOT / "scripts"))
from metrics import clean_inline, split_markdown  # noqa: E402

KANJI = re.compile(r"[一-鿿]")
QUESTION = re.compile(r"[?？]\s*$")
# 見出しの階層。split_markdown は `#` の個数を残さないので自前で数える。
# 生の本文を正規表現でなめるとコードブロック内の `# コメント` を拾うため、
# フェンスの内側を飛ばしながら1行ずつ見る。
FENCE = re.compile(r"^\s{0,3}(```|~~~)")
HEADING_LEVEL = re.compile(r"^\s{0,3}(#{1,6})\s")


def heading_levels(body: str) -> list[int]:
    """見出しの深さ(# の個数)を、出てくる順に返す。"""
    out: list[int] = []
    in_fence = False
    for line in body.splitlines():
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = HEADING_LEVEL.match(line)
        if m:
            out.append(len(m.group(1)))
    return out

# 1ファイルずつ全部読むと重い。月の先頭から何日分を見るか。
DEFAULT_DAYS = 8


def scan(pattern: str, days: int) -> dict:
    n = 0
    counts: list[int] = []
    lengths: list[int] = []
    kanji: list[float] = []
    q = 0
    total = 0
    h2 = h3 = 0
    for f in sorted(RAW.glob(pattern))[:days]:
        for line in f.open(encoding="utf-8"):
            body = json.loads(line).get("body") or ""
            if len(body) < 1000:
                continue
            hs = [clean_inline(h) for h in split_markdown(body)["headings"]]
            hs = [h for h in hs if h.strip()]
            if not hs:
                continue
            n += 1
            counts.append(len(hs))
            total += len(hs)
            for lv in heading_levels(body):
                if lv <= 2:
                    h2 += 1
                else:
                    h3 += 1
            for h in hs:
                lengths.append(len(h))
                kanji.append(len(KANJI.findall(h)) / max(1, len(h)))
                if QUESTION.search(h):
                    q += 1
    if not n:
        return {}
    return {
        "n": n,
        "count": statistics.median(counts),
        "length": statistics.median(lengths),
        "kanji": statistics.median(kanji),
        "question": q / total * 100,
        # ### 以下が全体に占める割合。階層が深くなっているかを見る
        "deep": h3 / max(1, h2 + h3) * 100,
    }


COLS = [("n", "記事数", "{:,}"), ("count", "見出し数", "{:.0f}"),
        ("length", "見出しの長さ", "{:.0f}"), ("kanji", "見出しの漢字率", "{:.3f}"),
        ("question", "疑問形%", "{:.2f}"), ("deep", "###以下%", "{:.1f}")]


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--monthly", action="store_true",
                    help="月ごとに出す(既定は各年8月)")
    ap.add_argument("--from", dest="since", help="この月以降 (例: 2024-01)")
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS,
                    help=f"各月の先頭何日分を見るか(既定 {DEFAULT_DAYS})")
    ap.add_argument("--min-articles", type=int, default=100)
    ap.add_argument("--md", action="store_true")
    args = ap.parse_args()

    rows: list[tuple[str, dict]] = []
    if args.monthly:
        months = sorted({p.name[6:13] for p in RAW.glob("qiita_????-??-??.jsonl")})
        if args.since:
            months = [m for m in months if m >= args.since]
        for m in months:
            s = scan(f"qiita_{m}-*.jsonl", args.days)
            if s and s["n"] >= args.min_articles:
                rows.append((m, s))
    else:
        years = sorted({p.name[6:10] for p in RAW.glob("qiita_????-08-??.jsonl")})
        for y in years:
            s = scan(f"qiita_{y}-08-*.jsonl", args.days)
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
        print(f"\n{'期間':<{w}}" + "".join(f"{l:>15}" for _, l, _ in COLS))
        print("-" * (w + 15 * len(COLS)))
        for label, s in rows:
            print(f"{label:<{w}}"
                  + "".join(f"{fmt.format(s[k]):>15}" for k, _, fmt in COLS))
    print(f"\n各月の先頭{args.days}日分で集計", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
