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


def scan_year(year: str, tagger) -> tuple[Counter, int, Counter, int]:
    """その年8月の記事を数える。

    戻り値は (含む記事数, 記事数, 延べ出現数, 地の文の総文字数)。

    記事出現率(含む記事数 / 記事数)だけだと、記事が長くなるだけで上がる。
    実際 2022年1,061字 → 2026年2,036字 と1.92倍に伸びており、
    「置く」1.63倍のように記事長で説明できる見かけの増加が混ざっていた。
    そこで延べ出現数と総文字数も返し、千字あたりでも測れるようにする。
    """
    doc_freq: Counter = Counter()
    raw_freq: Counter = Counter()
    n = 0
    total_chars = 0
    for f in sorted(RAW.glob(f"qiita_{year}-08-*.jsonl")):
        for line in f.open(encoding="utf-8"):
            item = json.loads(line)
            if item.get("slide") or item.get("private"):
                continue
            body = item.get("body") or ""
            if not body.strip():
                continue
            text = clean_inline("\n".join(split_markdown(body)["body_lines"]))
            chars = len(re.sub(r"\s", "", text))
            if chars < 300:
                continue
            n += 1
            total_chars += chars
            seen: set[str] = set()
            for w in tagger(text):
                lemma = getattr(w.feature, "lemma", None) or w.surface
                if is_target(lemma, w.feature.pos1):
                    seen.add(lemma)
                    raw_freq[lemma] += 1
            for lemma in seen:
                doc_freq[lemma] += 1
    return doc_freq, n, raw_freq, total_chars


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
    ap.add_argument("--normalize", action="store_true",
                    help="千字あたりの出現数で測る(記事長の影響を除く)")
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
    raw: dict[str, Counter] = {}
    chars: dict[str, int] = {}
    for y in years:
        df, n, rf, tc = scan_year(y, tagger)
        data[y], counts[y], raw[y], chars[y] = df, n, rf, tc
        print(f"  {y}: {n:,}記事 / {len(df):,}語 / 平均{tc//max(1,n):,}字",
              file=sys.stderr)

    # 全年の合計頻度から上位N語を選ぶ
    total: Counter = Counter()
    for y in years:
        total.update(data[y])
    vocab = [w for w, _ in total.most_common(args.top * 3)]

    def value(w: str, y: str) -> float:
        """正規化の有無で測り方を切り替える。

        normalize=False: 記事出現率(%)。記事が長くなるだけで上がる
        normalize=True:  千字あたりの延べ出現数。長さの影響を受けない
        """
        if args.normalize:
            return raw[y].get(w, 0) / max(1, chars[y]) * 1000
        return data[y].get(w, 0) / counts[y] * 100

    rows = []
    for w in vocab:
        series = [value(w, y) for y in years]
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
    (OUT / ("word_timeline_norm.json" if args.normalize else "word_timeline.json")).write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n保存: {OUT.name}/ ({len(rows)}語)", file=sys.stderr)

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
