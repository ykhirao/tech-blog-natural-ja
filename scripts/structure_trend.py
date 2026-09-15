#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""引用・段落・画像の推移を測る。

どれも metrics に材料はあるのに分析していなかったもの。
記事の組み立て方が変わっているかを、文体とは別の角度から見る。

測るもの:
  引用       `>` で始まる行を使う記事の割合と行数
  段落       1段落あたりの文数
  画像       使う記事の割合、1記事あたりの数、Qiita 添付か外部か

画像の外部ホストは、1記事で大量に貼る人がいると割合が跳ねる。
実際2026年8月は2人の著者が623件を占めていた。既定では1記事10件で
打ち切る(`--no-cap` で打ち切らない)。

使い方:
    ./scripts/structure_trend.py
    ./scripts/structure_trend.py --monthly --from 2025-01
    ./scripts/structure_trend.py --hosts       # 外部画像のホスト内訳
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

sys.path.insert(0, str(ROOT / "scripts"))
from metrics import split_markdown  # noqa: E402

IMG = re.compile(r"!\[[^\]]*\]\(([^)\s]+)")
HTML_IMG = re.compile(r"<img\s[^>]*src=[\"']([^\"']+)", re.I)
HOST = re.compile(r"https?://([^/]+)")
# Qiita に直接アップロードされた画像のホスト
QIITA_HOSTS = ("qiita-image-store", "qiita-user-contents")

DEFAULT_DAYS = 8
# 1記事あたり何件まで外部画像を数えるか。単一記事の大量掲載を抑える。
DEFAULT_CAP = 10


def is_qiita(url: str) -> bool:
    return any(h in url for h in QIITA_HOSTS)


def scan(pattern: str, days: int, cap: int | None) -> tuple[dict, Counter]:
    n = 0
    quoted = 0
    quote_lines: list[int] = []
    para_sentences: list[float] = []
    img_articles = 0
    img_counts: list[int] = []
    img_total = img_qiita = 0
    hosts: Counter = Counter()

    for f in sorted(RAW.glob(pattern))[:days]:
        for line in f.open(encoding="utf-8"):
            body = json.loads(line).get("body") or ""
            if len(body) < 1000:
                continue
            parts = split_markdown(body)
            if not parts["body_lines"]:
                continue
            n += 1

            q = parts["quote_lines"]
            if q:
                quoted += 1
                quote_lines.append(q)

            if parts["paragraphs"]:
                para_sentences.append(
                    statistics.mean(len(p) for p in parts["paragraphs"]))

            urls = IMG.findall(body) + HTML_IMG.findall(body)
            if urls:
                img_articles += 1
                img_counts.append(len(urls))
                ext = [u for u in urls if not is_qiita(u)]
                qi = len(urls) - len(ext)
                if cap is not None:
                    ext = ext[:cap]
                img_qiita += qi
                img_total += qi + len(ext)
                for u in ext:
                    m = HOST.match(u)
                    hosts[m.group(1) if m else "(相対パス)"] += 1

    if not n:
        return {}, hosts
    return {
        "n": n,
        "quote": quoted / n * 100,
        "qlines": statistics.median(quote_lines) if quote_lines else 0,
        "para": statistics.median(para_sentences) if para_sentences else 0,
        "img": img_articles / n * 100,
        "imgs": statistics.median(img_counts) if img_counts else 0,
        "ext": (img_total - img_qiita) / max(1, img_total) * 100,
    }, hosts


COLS = [("n", "記事数", "{:,}"), ("quote", "引用あり%", "{:.1f}"),
        ("qlines", "引用行数", "{:.0f}"), ("para", "段落の文数", "{:.2f}"),
        ("img", "画像あり%", "{:.1f}"), ("imgs", "画像数", "{:.0f}"),
        ("ext", "外部画像%", "{:.1f}")]


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--monthly", action="store_true")
    ap.add_argument("--from", dest="since")
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS)
    ap.add_argument("--min-articles", type=int, default=100)
    ap.add_argument("--cap", type=int, default=DEFAULT_CAP,
                    help="1記事あたりの外部画像の上限")
    ap.add_argument("--no-cap", action="store_true", help="打ち切らない")
    ap.add_argument("--hosts", action="store_true",
                    help="外部画像のホスト内訳を出す")
    ap.add_argument("--md", action="store_true")
    args = ap.parse_args()

    cap = None if args.no_cap else args.cap

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
        s, hosts = scan(pats[label], args.days, cap)
        if s and s["n"] >= args.min_articles:
            rows.append((label, s, hosts))

    if not rows:
        print("対象データがありません", file=sys.stderr)
        return 1

    if args.hosts:
        for label, _, hosts in rows[-3:]:
            print(f"\n{label} 外部画像の上位:")
            for h, c in hosts.most_common(6):
                print(f"   {h}: {c:,}")
        return 0

    if args.md:
        print("| 期間 | " + " | ".join(l for _, l, _ in COLS) + " |")
        print("|------|" + "|".join(["---"] * len(COLS)) + "|")
        for label, s, _ in rows:
            print(f"| {label} | "
                  + " | ".join(fmt.format(s[k]) for k, _, fmt in COLS) + " |")
    else:
        w = max(len(l) for l, _, _ in rows) + 2
        print(f"\n{'期間':<{w}}" + "".join(f"{l:>12}" for _, l, _ in COLS))
        print("-" * (w + 12 * len(COLS)))
        for label, s, _ in rows:
            print(f"{label:<{w}}"
                  + "".join(f"{fmt.format(s[k]):>12}" for k, _, fmt in COLS))

    note = "打ち切りなし" if cap is None else f"外部画像は1記事{cap}件で打ち切り"
    print(f"\n各月の先頭{args.days}日分で集計。{note}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
