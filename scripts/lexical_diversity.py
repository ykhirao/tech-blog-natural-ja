#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["fugashi[unidic-lite]>=1.3"]
# ///
"""MTLD が上がった仕組みを見る。何が起きて語彙が多様になったのか。

MTLD は 43.2(2020) → 53.5(2026) に上がっている(docs/2020-08-vs-2026-08.md)。
「AI は語彙を単調にする」という通説と逆向きなので、中身を見る。

長さの扱いに注意が要る。TTR(異なり比)は長い文章ほど下がるので、
素のまま年を並べると MTLD と逆を向く。ここでは2段構えで消す。

  1. 内容語(名詞・動詞・形容詞)の**先頭400語だけ**で測る
  2. そもそも内容語が400〜700語の記事だけを対象にする

2 を入れないと、短い記事が多い年ほど「400語ある記事」が長い側に偏る。
2020年は541本中159本しか残らず、残ったのは長い記事だけになっていた。

測るもの:

  最頻語占有  いちばん多く出る内容語が全体に占める割合。繰り返しの指標
  1回だけ語   1回しか出てこない語の割合
  異なり比    異なり語数 / 延べ語数(固定窓なので長さの影響は無い)
  カタカナ    カタカナだけの語の割合
  英字        英字で始まる語の割合(識別子、コマンド名など)

使い方:
    ./scripts/lexical_diversity.py 2015-08 2020-08 2024-08 2026-08
    ./scripts/lexical_diversity.py 2020-08 2026-08 --md
"""

from __future__ import annotations

import argparse
import json
import random
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
sys.path.insert(0, str(ROOT / "scripts"))
from metrics import clean_inline, split_markdown, tagger  # noqa: E402

KATAKANA = re.compile(r"^[ァ-ヶー]+$")
ALPHA = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")
WINDOW = 400
BAND = (400, 700)
COLS = ["最頻語占有", "1回だけ語", "異なり比", "カタカナ", "英字"]


def profile(text: str, tg) -> tuple[float, ...] | None:
    words = list(tg(text))
    lemmas = [getattr(w.feature, "lemma", None) or w.surface for w in words]
    content = [(l, w) for l, w in zip(lemmas, words)
               if w.feature.pos1 in ("名詞", "動詞", "形容詞")]
    if not (BAND[0] <= len(content) <= BAND[1]):
        return None
    content = content[:WINDOW]
    ls = [l for l, _ in content]
    c = Counter(ls)
    return (
        c.most_common(1)[0][1] / len(ls),
        sum(1 for v in c.values() if v == 1) / len(c),
        len(c) / len(ls),
        sum(1 for l in ls if KATAKANA.match(l)) / len(ls),
        sum(1 for l in ls if ALPHA.match(l)) / len(ls),
    )


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("months", nargs="+", help="YYYY-MM を並べる")
    ap.add_argument("-n", type=int, default=4000, help="1か月あたり何本まで見るか")
    ap.add_argument("--md", action="store_true")
    args = ap.parse_args()

    tg = tagger()
    rows = []
    for month in args.months:
        texts = []
        for f in sorted(RAW.glob(f"qiita_{month}-*.jsonl")):
            for line in f.open(encoding="utf-8"):
                body = json.loads(line).get("body") or ""
                if len(body) < 1000:
                    continue
                t = clean_inline("\n".join(split_markdown(body)["body_lines"]))
                if len(t) >= 300:
                    texts.append(t[:6000])
        if not texts:
            print(f"{month} のデータがありません", file=sys.stderr)
            continue
        random.seed(42)
        random.shuffle(texts)
        rs = [r for r in (profile(t, tg) for t in texts[:args.n]) if r]
        if not rs:
            continue
        rows.append((month, len(rs),
                     *[statistics.fmean(x[i] for x in rs) for i in range(len(COLS))]))

    if args.md:
        print("| 月 | 記事 | " + " | ".join(COLS) + " |")
        print("|---|---|" + "|".join(["---"] * len(COLS)) + "|")
        for m, n, *v in rows:
            print(f"| {m} | {n:,} | " + " | ".join(f"{x:.4f}" for x in v) + " |")
    else:
        print(f"{'月':<10}{'記事':>7}" + "".join(f"{c:>12}" for c in COLS))
        print("-" * (17 + 12 * len(COLS)))
        for m, n, *v in rows:
            print(f"{m:<10}{n:>7,}" + "".join(f"{x:>12.4f}" for x in v))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
