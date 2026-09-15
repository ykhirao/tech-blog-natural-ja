#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""ある特徴で記事を2つに分けて、全指標を比べる。

「日本語ブロックを使う記事は太字も多いのか」のような問いに答えるための道具。
交絡を潰すのとは逆で、**指標どうしの関係**を見る。

実際これで「装飾を多用する記事という型が2026年に生まれた」が出た
(docs/code-trend.md)。2020年と2024年には差がなかった。

分け方:
  ja-block    中身が日本語のコードブロックを使うか
  bold        太字を使うか
  image       画像を使うか
  quote       引用を使うか
  mermaid     mermaid ブロックを使うか

使い方:
    ./scripts/split_by.py --by ja-block --months 2020-08,2024-08,2026-08
    ./scripts/split_by.py --by bold --months 2026-08 --md
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
PROC = ROOT / "data" / "processed"

FENCE = re.compile(r"^\s{0,3}(?:```|~~~)\s*([A-Za-z0-9_+#.-]*)")
JA = re.compile(r"[぀-ヿ一-鿿]")
BOLD = re.compile(r"\*\*[^*\n]+\*\*|__[^_\n]+__")
IMG = re.compile(r"!\[[^\]]*\]\(|<img\s", re.I)
QUOTE = re.compile(r"^\s{0,3}>\s", re.M)

JA_THRESHOLD = 0.30
MIN_BLOCK_CHARS = 20

FIELDS = [
    ("bold_per_1k", "太字/千字", "{:.3f}"),
    ("n_headings", "見出し数", "{:.0f}"),
    ("chars_body", "地の文字数", "{:,.0f}"),
    ("list_ratio", "箇条書き", "{:.3f}"),
    ("nominal_ending_ratio", "体言止め", "{:.3f}"),
    ("ten_per_sentence", "読点/文", "{:.3f}"),
    ("burstiness_mora", "文長のばらつき", "{:.3f}"),
    ("kanji_ratio", "漢字率", "{:.3f}"),
]


def blocks_of(body: str):
    """コードブロックを (言語, 中身) で返す。"""
    inside = False
    lang = ""
    buf: list[str] = []
    for line in body.splitlines():
        m = FENCE.match(line)
        if m:
            if not inside:
                lang = (m.group(1) or "").lower()
                buf = []
            else:
                yield lang, "".join(buf)
            inside = not inside
        elif inside:
            buf.append(line)


def has_ja_block(body: str) -> bool:
    for _, text in blocks_of(body):
        if len(text) >= MIN_BLOCK_CHARS and \
                len(JA.findall(text)) / len(text) >= JA_THRESHOLD:
            return True
    return False


def has_mermaid(body: str) -> bool:
    return any(lang == "mermaid" for lang, _ in blocks_of(body))


TESTS = {
    "ja-block": has_ja_block,
    "bold": lambda b: bool(BOLD.search(b)),
    "image": lambda b: bool(IMG.search(b)),
    "quote": lambda b: bool(QUOTE.search(b)),
    "mermaid": has_mermaid,
}


def ids_matching(month: str, test) -> set:
    out = set()
    for f in sorted(RAW.glob(f"qiita_{month}-*.jsonl")):
        for line in f.open(encoding="utf-8"):
            d = json.loads(line)
            body = d.get("body") or ""
            if len(body) < 1000:
                continue
            if test(body):
                out.add(d.get("id"))
    return out


def med(rows: list[dict], field: str):
    v = [r[field] for r in rows if isinstance(r.get(field), (int, float))]
    return statistics.median(v) if v else None


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--by", required=True, choices=list(TESTS),
                    help="何で分けるか")
    ap.add_argument("--months", default="2020-08,2024-08,2026-08")
    ap.add_argument("--md", action="store_true")
    args = ap.parse_args()

    test = TESTS[args.by]
    months = [m.strip() for m in args.months.split(",")]

    for month in months:
        f = PROC / f"metrics_{month}.jsonl"
        if not f.exists():
            print(f"{f} がありません。build_dataset.py を先に実行してください",
                  file=sys.stderr)
            continue
        rows = [json.loads(l) for l in f.open(encoding="utf-8") if l.strip()]
        ids = ids_matching(month, test)
        A = [r for r in rows if r.get("id") in ids]
        B = [r for r in rows if r.get("id") not in ids]
        if not A or not B:
            print(f"{month}: 片方が空なので比べられません", file=sys.stderr)
            continue

        share = len(A) / (len(A) + len(B)) * 100
        if args.md:
            print(f"\n### {month} — {args.by} で分ける"
                  f"(あり {len(A):,}本 / {share:.1f}%、なし {len(B):,}本)\n")
            print("| 指標 | あり | なし | 差 |")
            print("|------|-----|-----|-----|")
            for k, lbl, fmt in FIELDS:
                x, y = med(A, k), med(B, k)
                if x is None or y is None:
                    continue
                print(f"| {lbl} | {fmt.format(x)} | {fmt.format(y)} | "
                      f"{x - y:+.3f} |")
        else:
            print(f"\n{month}  {args.by}: あり {len(A):,}本 ({share:.1f}%) / "
                  f"なし {len(B):,}本")
            print(f"  {'指標':16}{'あり':>12}{'なし':>12}{'差':>12}")
            for k, lbl, fmt in FIELDS:
                x, y = med(A, k), med(B, k)
                if x is None or y is None:
                    continue
                print(f"  {lbl:16}{fmt.format(x):>12}{fmt.format(y):>12}"
                      f"{x - y:>+12.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
