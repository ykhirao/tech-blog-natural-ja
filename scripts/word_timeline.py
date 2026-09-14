#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["fugashi[unidic-lite]>=1.3"]
# ///
"""頻出語の年次推移をまとめて出す。上位N語を機械的に選んで追跡する。

long_trend.py は指定した正規表現しか追えないので、こちらは
「頻度上位から自動で語を選び、全年の出現率を出す」ことをやる。

AI前後の傾きを比べて、急に増えた語・減った語を選り分ける。

出力:
  data/processed/word_timeline.json  全語の年次データ
  docs/word-trends.md                上位・下位のグラフ付きレポート

使い方:
    ./scripts/word_timeline.py --years 2015,2017,2019,2021,2022,2023,2026 --top 500
    ./scripts/word_timeline.py --top 300 --min-docs 50
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from metrics import clean_inline, split_markdown  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed"

CONTENT_POS = {"名詞", "動詞", "形容詞", "副詞", "接続詞"}
ASCII_ONLY = re.compile(r"^[\x00-\x7f]+$")
STOP = {
    "する", "ある", "なる", "いる", "できる", "こと", "もの", "ため", "よう",
    "これ", "それ", "あれ", "ここ", "そこ", "私", "僕", "自分", "方",
    "的", "性", "化", "上", "下", "中", "内", "外", "時", "際", "場合",
    "以下", "以上", "そう", "どう", "何", "人", "者", "等", "他",
}


def is_target(lemma: str, pos: str) -> bool:
    if pos not in CONTENT_POS:
        return False
    if lemma in STOP or len(lemma) < 2:
        return False
    if ASCII_ONLY.match(lemma):
        return False
    return True


def scan_year(year: str, tagger) -> tuple[Counter, int]:
    """その年8月の記事で、語ごとの「含む記事数」を数える。"""
    doc_freq: Counter = Counter()
    n = 0
    for f in sorted(RAW.glob(f"qiita_{year}-08-*.jsonl")):
        for line in f.open(encoding="utf-8"):
            item = json.loads(line)
            if item.get("slide") or item.get("private"):
                continue
            body = item.get("body") or ""
            if not body.strip():
                continue
            text = clean_inline("\n".join(split_markdown(body)["body_lines"]))
            if len(re.sub(r"\s", "", text)) < 300:
                continue
            n += 1
            seen: set[str] = set()
            for w in tagger(text):
                lemma = getattr(w.feature, "lemma", None) or w.surface
                if is_target(lemma, w.feature.pos1):
                    seen.add(lemma)
            for lemma in seen:
                doc_freq[lemma] += 1
    return doc_freq, n


def sparkline(vals: list[float]) -> str:
    blocks = "▁▂▃▄▅▆▇█"
    lo, hi = min(vals), max(vals)
    if hi == lo:
        return blocks[0] * len(vals)
    return "".join(blocks[min(7, int((v - lo) / (hi - lo) * 7))] for v in vals)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--years", default="2015,2016,2017,2018,2019,2020,2021,2022,2023,2024,2025,2026")
    ap.add_argument("--top", type=int, default=500, help="追跡する語数")
    ap.add_argument("--min-docs", type=int, default=30,
                    help="どの年かでこの記事数に達しない語は除く")
    ap.add_argument("--ai-year", default="2022", help="この年までをAI以前とする")
    args = ap.parse_args()

    import fugashi
    tagger = fugashi.Tagger()

    years = [y.strip() for y in args.years.split(",")]
    years = [y for y in years if list(RAW.glob(f"qiita_{y}-08-*.jsonl"))]
    if len(years) < 3:
        print("3年分以上のデータが要ります")
        return 1

    print(f"対象年: {', '.join(years)}", file=sys.stderr)
    data: dict[str, Counter] = {}
    counts: dict[str, int] = {}
    for y in years:
        df, n = scan_year(y, tagger)
        data[y], counts[y] = df, n
        print(f"  {y}: {n:,}記事 / {len(df):,}語", file=sys.stderr)

    # 全年の合計頻度から上位N語を選ぶ
    total: Counter = Counter()
    for y in years:
        total.update(data[y])
    vocab = [w for w, _ in total.most_common(args.top * 3)]

    rows = []
    for w in vocab:
        series = [data[y].get(w, 0) / counts[y] * 100 for y in years]
        if max(data[y].get(w, 0) for y in years) < args.min_docs:
            continue
        pre = [y for y in years if y <= args.ai_year]
        post = [y for y in years if y > args.ai_year]
        if len(pre) < 2 or not post:
            continue
        i0, i1 = years.index(pre[0]), years.index(pre[-1])
        pre_slope = (series[i1] - series[i0]) / max(1, int(pre[-1]) - int(pre[0]))
        j0, j1 = years.index(pre[-1]), years.index(post[-1])
        post_slope = (series[j1] - series[j0]) / max(1, int(post[-1]) - int(pre[-1]))
        rows.append({
            "word": w, "series": [round(v, 3) for v in series],
            "pre_slope": round(pre_slope, 4), "post_slope": round(post_slope, 4),
            "first": round(series[0], 3), "last": round(series[-1], 3),
            "ratio": round(series[-1] / series[0], 2) if series[0] > 0 else None,
        })
        if len(rows) >= args.top:
            break

    OUT.mkdir(parents=True, exist_ok=True)
    payload = {"years": years, "article_counts": counts, "words": rows}
    (OUT / "word_timeline.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n保存: data/processed/word_timeline.json ({len(rows)}語)", file=sys.stderr)

    # AI以後に急増した語 / 急減した語
    surge = sorted(rows, key=lambda r: -(r["post_slope"] - r["pre_slope"]))[:25]
    drop = sorted(rows, key=lambda r: (r["post_slope"] - r["pre_slope"]))[:15]

    print(f"\n## AI以後に急増した語(上位25)  年: {' '.join(years)}\n")
    print(f"{'語':<12}{'推移':<14}{years[0]:>7}{years[-1]:>8}{'AI前/年':>9}{'AI後/年':>9}")
    print("-" * 62)
    for r in surge:
        print(f"{r['word']:<12}{sparkline(r['series']):<14}"
              f"{r['first']:>7.2f}{r['last']:>8.2f}{r['pre_slope']:>+9.3f}{r['post_slope']:>+9.3f}")

    print(f"\n## AI以後に減った語(上位15)\n")
    print(f"{'語':<12}{'推移':<14}{years[0]:>7}{years[-1]:>8}{'AI前/年':>9}{'AI後/年':>9}")
    print("-" * 62)
    for r in drop:
        print(f"{r['word']:<12}{sparkline(r['series']):<14}"
              f"{r['first']:>7.2f}{r['last']:>8.2f}{r['pre_slope']:>+9.3f}{r['post_slope']:>+9.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
