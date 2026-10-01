#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["fugashi[unidic-lite]>=1.3"]
# ///
"""漢語とサ変名詞の密度を測る。

「AIっぽさを直す」と称する書き換えが、かわりに漢語サ変名詞の密度を上げて
読みにくくしているという指摘がある。「二重送信の発生を検知し」のように
事象を名詞で並べると、1語ごとに意味を取る必要が出て文として途切れる。

指摘の当否はさておき、この軸自体はこちらで測っていなかった。
体言止め(nominal_ending_ratio)は文末だけを見るので、文中の名詞密度は拾えない。

  サ変名詞率  UniDic の pos3 == "サ変可能"(送信、発生、検知、実装…)
  漢語率      UniDic の goshu == "漢" / 語彙的な語(漢・和・外・混)
  数珠つなぎ  サ変名詞が助詞を挟まず直接続く箇所(「影響範囲特定」)

形態素解析が重いので記事を間引く。既定は各月500本、本文は先頭6,000字。

使い方:
    ./scripts/kango_density.py --years 2015,2020,2022,2024,2026
    ./scripts/kango_density.py --within 2020-08 2026-08
    ./scripts/kango_density.py --years 2015,2020,2026 --md
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
sys.path.insert(0, str(ROOT / "scripts"))
from metrics import clean_inline, split_markdown, tagger  # noqa: E402

MAX_CHARS = 6000
MIN_TOKENS = 100


def bodies(glob: str, min_body: int = 1000) -> list[tuple[str, str]]:
    """(著者, 地の文) を返す。"""
    out = []
    for f in sorted(RAW.glob(glob)):
        for line in f.open(encoding="utf-8"):
            it = json.loads(line)
            body = it.get("body") or ""
            if len(body) < min_body:
                continue
            text = clean_inline("\n".join(split_markdown(body)["body_lines"]))
            if len(text) >= 300:
                out.append((it.get("user_id") or "", text[:MAX_CHARS]))
    return out


def measure(texts: list[str], tg) -> tuple[float, float, float, float] | None:
    """まとめて1つの値にする。著者単位で使うので記事をつなげて数える。"""
    sahen = verbs = total = 0
    lex: list[str] = []
    chains = 0
    for t in texts:
        ws = list(tg(t))
        if len(ws) < MIN_TOKENS:
            continue
        flags = [getattr(w.feature, "pos3", None) == "サ変可能" for w in ws]
        sahen += sum(flags)
        chains += sum(1 for i in range(1, len(flags)) if flags[i] and flags[i - 1])
        verbs += sum(1 for w in ws if w.feature.pos1 == "動詞")
        total += len(ws)
        lex += [g for g in (getattr(w.feature, "goshu", None) for w in ws)
                if g in ("漢", "和", "外", "混")]
    if not total or not lex:
        return None
    return sahen / total, lex.count("漢") / len(lex), chains / total * 1000, verbs / total


def run_years(years: list[str], n: int, md: bool) -> None:
    tg = tagger()
    rows = []
    for y in years:
        texts = [t for _, t in bodies(f"qiita_{y}-08-*.jsonl")]
        random.seed(42)
        random.shuffle(texts)
        texts = texts[:n]
        rs = [r for r in (measure([t], tg) for t in texts) if r]
        rows.append((y, len(rs), *[statistics.fmean(x[i] for x in rs) for i in range(4)]))
    if md:
        print("| 年 | 記事 | サ変名詞率 | 漢語率 | 数珠つなぎ/千語 | 動詞率 |")
        print("|---|---|---|---|---|---|")
        for y, c, s, k, ch, v in rows:
            print(f"| {y} | {c} | {s:.4f} | {k:.4f} | {ch:.2f} | {v:.4f} |")
    else:
        print(f"{'年':<6}{'記事':>7}{'サ変名詞率':>12}{'漢語率':>10}"
              f"{'数珠/千語':>12}{'動詞率':>10}")
        print("-" * 57)
        for y, c, s, k, ch, v in rows:
            print(f"{y:<6}{c:>7}{s:>12.4f}{k:>10.4f}{ch:>12.2f}{v:>10.4f}")


def run_within(a: str, b: str) -> None:
    """本人内の変化。書き手の入れ替わりと区別する(within_author.py と同じ考え)。"""
    tg = tagger()
    groups = {}
    for month in (a, b):
        by: dict[str, list[str]] = defaultdict(list)
        for user, text in bodies(f"qiita_{month}-*.jsonl"):
            if user:
                by[user].append(text)
        groups[month] = by
    both = sorted(set(groups[a]) & set(groups[b]))
    rows = []
    for u in both:
        x, y = measure(groups[a][u], tg), measure(groups[b][u], tg)
        if x and y:
            rows.append((x, y))
    if not rows:
        print("両方の月に投稿した著者が見つかりません", file=sys.stderr)
        return
    print(f"{a} と {b} の両方に投稿した著者: {len(both)}人 / 測れた: {len(rows)}人\n")
    for i, name in enumerate(["サ変名詞率", "漢語率", "数珠つなぎ", "動詞率"]):
        xs = [r[0][i] for r in rows]
        ys = [r[1][i] for r in rows]
        up = sum(1 for x, y in zip(xs, ys) if y > x)
        print(f"{name:<12}{a} {statistics.fmean(xs):.4f} -> {b} {statistics.fmean(ys):.4f}"
              f"  差 {statistics.fmean(ys) - statistics.fmean(xs):+.4f}"
              f"  上げた人 {up / len(rows) * 100:.0f}%  n={len(rows)}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--years", help="各年8月を比べる(カンマ区切り)")
    ap.add_argument("--within", nargs=2, metavar=("A", "B"),
                    help="2つの月(YYYY-MM)で本人内の変化を見る")
    ap.add_argument("-n", type=int, default=500, help="1か月あたりの記事数")
    ap.add_argument("--md", action="store_true", help="Markdown で出す")
    args = ap.parse_args()

    if args.within:
        run_within(*args.within)
    elif args.years:
        years = [y.strip() for y in args.years.split(",")]
        years = [y for y in years if list(RAW.glob(f"qiita_{y}-08-*.jsonl"))]
        if not years:
            print("データがありません", file=sys.stderr)
            return 1
        run_years(years, args.n, args.md)
    else:
        ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
