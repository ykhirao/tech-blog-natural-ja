#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""コードブロックの量と言語指定の推移を測る。

地の文が2倍になったことは測ったが、**コードのほうがどうなったか**は
測っていなかった。技術記事なので、ここが変われば記事の性格が変わる。

測るもの:
  ブロック数   記事あたりいくつあるか
  コード行数   1記事あたり何行か
  言語指定     ```python のように言語を書いているか
  言語の内訳   何が書かれているか

生データを直接読むので、build_dataset.py を通していない月でも使える。

使い方:
    ./scripts/code_trend.py
    ./scripts/code_trend.py --langs          # 言語の内訳
    ./scripts/code_trend.py --monthly --from 2025-01
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"

# ```python や ~~~js の開始行。言語名は省略できる。
FENCE = re.compile(r"^\s{0,3}(?:```|~~~)\s*([A-Za-z0-9_+#.-]*)")

DEFAULT_DAYS = 8

# --langs で出す言語。上位に来るものと、変化が大きいものを選んだ。
WATCH = ["text", "bash", "python", "javascript", "typescript",
         "json", "yaml", "mermaid", "sh"]


def scan(pattern: str, days: int) -> tuple[dict, Counter, int]:
    n = 0
    blocks: list[int] = []
    code_lines: list[int] = []
    langs: Counter = Counter()
    nolang = 0
    total = 0
    for f in sorted(RAW.glob(pattern))[:days]:
        for line in f.open(encoding="utf-8"):
            body = json.loads(line).get("body") or ""
            if len(body) < 1000:
                continue
            n += 1
            cnt = 0
            cl = 0
            inside = False
            for raw in body.splitlines():
                m = FENCE.match(raw)
                if m:
                    if not inside:
                        cnt += 1
                        total += 1
                        lang = (m.group(1) or "").lower()
                        if lang:
                            langs[lang] += 1
                        else:
                            nolang += 1
                    inside = not inside
                elif inside:
                    cl += 1
            blocks.append(cnt)
            code_lines.append(cl)
    if not n:
        return {}, langs, total
    return {
        "n": n,
        "blocks": statistics.median(blocks),
        "lines": statistics.median(code_lines),
        "nolang": nolang / max(1, total) * 100,
        "total": total,
    }, langs, total


COLS = [("n", "記事数", "{:,}"), ("blocks", "ブロック数", "{:.0f}"),
        ("lines", "コード行数", "{:.0f}"), ("nolang", "言語指定なし%", "{:.1f}")]


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--monthly", action="store_true")
    ap.add_argument("--from", dest="since")
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS)
    ap.add_argument("--min-articles", type=int, default=100)
    ap.add_argument("--langs", action="store_true", help="言語の内訳を出す")
    ap.add_argument("--md", action="store_true")
    args = ap.parse_args()

    if args.monthly:
        labels = sorted({p.name[6:13] for p in RAW.glob("qiita_????-??-??.jsonl")})
        if args.since:
            labels = [m for m in labels if m >= args.since]
        pats = {m: f"qiita_{m}-*.jsonl" for m in labels}
    else:
        labels = sorted({p.name[6:10] for p in RAW.glob("qiita_????-08-??.jsonl")})
        pats = {y: f"qiita_{y}-08-*.jsonl" for y in labels}

    rows = []
    for label in labels:
        s, langs, total = scan(pats[label], args.days)
        if s and s["n"] >= args.min_articles:
            rows.append((label, s, langs, total))

    if not rows:
        print("対象データがありません", file=sys.stderr)
        return 1

    if args.langs:
        cols = ["指定なし"] + WATCH
        if args.md:
            print("| 期間 | ブロック | " + " | ".join(cols) + " |")
            print("|------|---------|" + "|".join(["---"] * len(cols)) + "|")
            for label, s, langs, total in rows:
                vals = [f"{s['nolang']:.1f}"] + [
                    f"{langs[k] / max(1, total) * 100:.1f}" for k in WATCH]
                print(f"| {label} | {total:,} | " + " | ".join(vals) + " |")
        else:
            w = max(len(l) for l, _, _, _ in rows) + 2
            print(f"\n{'期間':<{w}}{'ブロック':>10}" + "".join(f"{c:>12}" for c in cols))
            print("-" * (w + 10 + 12 * len(cols)))
            for label, s, langs, total in rows:
                line = f"{label:<{w}}{total:>10,}{s['nolang']:>11.1f}%"
                for k in WATCH:
                    line += f"{langs[k] / max(1, total) * 100:>11.1f}%"
                print(line)
    elif args.md:
        print("| 期間 | " + " | ".join(l for _, l, _ in COLS) + " |")
        print("|------|" + "|".join(["---"] * len(COLS)) + "|")
        for label, s, _, _ in rows:
            print(f"| {label} | "
                  + " | ".join(fmt.format(s[k]) for k, _, fmt in COLS) + " |")
    else:
        w = max(len(l) for l, _, _, _ in rows) + 2
        print(f"\n{'期間':<{w}}" + "".join(f"{l:>14}" for _, l, _ in COLS))
        print("-" * (w + 14 * len(COLS)))
        for label, s, _, _ in rows:
            print(f"{label:<{w}}"
                  + "".join(f"{fmt.format(s[k]):>14}" for k, _, fmt in COLS))

    print(f"\n各月の先頭{args.days}日分で集計", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
