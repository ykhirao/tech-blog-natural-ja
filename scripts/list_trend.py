#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""箇条書きの入れ子とリンクの張り方を測る。

箇条書きの割合は metrics にあるが、**入れ子の深さ**は見ていなかった。
見出しの階層が2026年に浅くなったので、箇条書きも同じ方向か確かめる。

入れ子は「使う記事の割合」で測る。中央値だと半数以上が0で差が出ない
(体言止めと同じ形。docs/zero-users.md を参照)。

測るもの:
  入れ子あり%   1段でも字下げした箇条書きがある記事の割合
  深さ2以上%    2段以上のものがある記事の割合
  件数          記事あたりの箇条書きの数
  順序付き%     1. 2. 3. のように番号を振ったものの割合
  リンク        Qiita 内 / GitHub / 裸の URL

使い方:
    ./scripts/list_trend.py
    ./scripts/list_trend.py --links
    ./scripts/list_trend.py --monthly --from 2025-01
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

FENCE = re.compile(r"^\s{0,3}(?:```|~~~)")
# 箇条書きの行頭。字下げの幅と、記号か番号かを取る。
ITEM = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+")
LINK = re.compile(r"\[([^\]]*)\]\((https?://[^)\s]+)\)")
# Markdown のリンク記法に入っていない、裸の URL
BARE = re.compile(r"(?<![\(\]])https?://[^\s\)]+")

DEFAULT_DAYS = 8
# 字下げ何文字を1段とみなすか。実測ではインデントなしが8〜9割で、
# 残りは2か4スペースに割れる。2で割れば両方とも1段以上になる。
INDENT_UNIT = 2


def body_outside_code(body: str) -> list[str]:
    """コードブロックの外の行だけ返す。"""
    out = []
    inside = False
    for line in body.splitlines():
        if FENCE.match(line):
            inside = not inside
            continue
        if not inside:
            out.append(line)
    return out


def scan_lists(pattern: str, days: int) -> dict:
    n = nest = deep = 0
    counts: list[int] = []
    items = ordered = 0
    for f in sorted(RAW.glob(pattern))[:days]:
        for line in f.open(encoding="utf-8"):
            body = json.loads(line).get("body") or ""
            if len(body) < 1000:
                continue
            depths: list[int] = []
            num = 0
            for raw in body_outside_code(body):
                m = ITEM.match(raw)
                if m:
                    depths.append(len(m.group(1)) // INDENT_UNIT)
                    if m.group(2)[0].isdigit():
                        num += 1
            if not depths:
                continue
            n += 1
            counts.append(len(depths))
            items += len(depths)
            ordered += num
            if max(depths) >= 1:
                nest += 1
            if max(depths) >= 2:
                deep += 1
    if not n:
        return {}
    return {
        "n": n,
        "nest": nest / n * 100,
        "deep": deep / n * 100,
        "count": statistics.median(counts),
        "ordered": ordered / max(1, items) * 100,
    }


def scan_links(pattern: str, days: int) -> dict:
    n = total = qiita = github = bare = 0
    for f in sorted(RAW.glob(pattern))[:days]:
        for line in f.open(encoding="utf-8"):
            body = json.loads(line).get("body") or ""
            if len(body) < 1000:
                continue
            text = "\n".join(body_outside_code(body))
            links = LINK.findall(text)
            bares = BARE.findall(text)
            if not links and not bares:
                continue
            n += 1
            for _, url in links:
                total += 1
                if "qiita.com" in url:
                    qiita += 1
                if "github.com" in url:
                    github += 1
            bare += len(bares)
    if not n:
        return {}
    return {
        "n": n,
        "links": total,
        "qiita": qiita / max(1, total) * 100,
        "github": github / max(1, total) * 100,
        # 裸 URL はリンク記法の外なので、母数に足してから割合を出す
        "bare": bare / max(1, total + bare) * 100,
    }


LIST_COLS = [("n", "記事数", "{:,}"), ("nest", "入れ子あり%", "{:.1f}"),
             ("deep", "深さ2以上%", "{:.1f}"), ("count", "箇条書き数", "{:.0f}"),
             ("ordered", "順序付き%", "{:.1f}")]
LINK_COLS = [("n", "記事数", "{:,}"), ("links", "リンク", "{:,}"),
             ("qiita", "Qiita内%", "{:.1f}"), ("github", "GitHub%", "{:.1f}"),
             ("bare", "裸URL%", "{:.1f}")]


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--monthly", action="store_true")
    ap.add_argument("--from", dest="since")
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS)
    ap.add_argument("--min-articles", type=int, default=100)
    ap.add_argument("--links", action="store_true", help="リンクのほうを出す")
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

    fn = scan_links if args.links else scan_lists
    cols = LINK_COLS if args.links else LIST_COLS
    rows = []
    for label in labels:
        s = fn(pats[label], args.days)
        if s and s["n"] >= args.min_articles:
            rows.append((label, s))

    if not rows:
        print("対象データがありません", file=sys.stderr)
        return 1

    if args.md:
        print("| 期間 | " + " | ".join(l for _, l, _ in cols) + " |")
        print("|------|" + "|".join(["---"] * len(cols)) + "|")
        for label, s in rows:
            print(f"| {label} | "
                  + " | ".join(fmt.format(s[k]) for k, _, fmt in cols) + " |")
    else:
        w = max(len(l) for l, _ in rows) + 2
        print(f"\n{'期間':<{w}}" + "".join(f"{l:>13}" for _, l, _ in cols))
        print("-" * (w + 13 * len(cols)))
        for label, s in rows:
            print(f"{label:<{w}}"
                  + "".join(f"{fmt.format(s[k]):>13}" for k, _, fmt in cols))
    print(f"\n各月の先頭{args.days}日分で集計", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
