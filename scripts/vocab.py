#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["fugashi[unidic-lite]>=1.3"]
# ///
"""2群の語彙差を出す。どの語が増えてどの語が減ったかを統計的に測る。

対数オッズ比(informative Dirichlet prior)を使う。単純な頻度差だと低頻度語が
ノイズで上位に来るが、この方法は事前分布で平滑化するのでそれを抑えられる。
Monroe et al. (2008) の fightin' words 法。

「記事出現率」も併せて出す。ある語が特定の1記事で100回使われても、
それは1人の癖でしかない。何割の記事に現れるかの方が広がりを表す。

使い方:
    ./scripts/vocab.py data/raw/qiita_2020-08-*.jsonl --vs data/raw/qiita_2026-08-*.jsonl
    ./scripts/vocab.py A/*.jsonl --vs B/*.jsonl --top 40 --md
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from metrics import clean_inline, split_markdown  # noqa: E402

# 内容語だけを見る。助詞・助動詞は文体指標(pos_*_ratio)の担当。
CONTENT_POS = {"名詞", "動詞", "形容詞", "副詞", "接続詞"}

# 技術用語・固有名詞は「日本語の書き方」の話ではないので落とす。
# 製品名やバージョン番号が上位を占めると語彙の変化が見えなくなる。
STOP = {
    "する", "ある", "なる", "いる", "できる", "こと", "もの", "ため", "よう",
    "これ", "それ", "あれ", "ここ", "そこ", "私", "僕", "自分", "方",
    "的", "性", "化", "上", "下", "中", "内", "外", "時", "際", "際に",
}
ASCII_ONLY = re.compile(r"^[\x00-\x7f]+$")
NUM_ONLY = re.compile(r"^[\d\W_]+$")


def is_target(lemma: str, pos: str) -> bool:
    if pos not in CONTENT_POS:
        return False
    if lemma in STOP or len(lemma) < 2:
        return False
    # 英数字のみの語(API, Docker, v2 など)は技術用語なので除外
    if ASCII_ONLY.match(lemma) or NUM_ONLY.match(lemma):
        return False
    return True


def collect(paths: list[Path], tagger) -> tuple[Counter, Counter, int]:
    """(語の総出現数, 語を含む記事数, 記事数) を返す。"""
    freq: Counter = Counter()
    doc_freq: Counter = Counter()
    n_docs = 0
    for p in paths:
        for line in p.open(encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            if item.get("slide") or item.get("private"):
                continue
            body = item.get("body") or ""
            if not body.strip():
                continue
            text = clean_inline("\n".join(split_markdown(body)["body_lines"]))
            if len(re.sub(r"\s", "", text)) < 300:
                continue
            n_docs += 1
            seen: set[str] = set()
            for w in tagger(text):
                lemma = getattr(w.feature, "lemma", None) or w.surface
                if not is_target(lemma, w.feature.pos1):
                    continue
                freq[lemma] += 1
                seen.add(lemma)
            for lemma in seen:
                doc_freq[lemma] += 1
    return freq, doc_freq, n_docs


def log_odds(a: Counter, b: Counter, prior_scale: float = 0.01) -> dict[str, float]:
    """対数オッズ比(informative Dirichlet prior)の z 値を返す。

    正なら b 側、負なら a 側に偏っている語。
    事前分布は両群の合算頻度から作る(Monroe et al. 2008)。
    """
    vocab = set(a) | set(b)
    na, nb = sum(a.values()), sum(b.values())
    total = na + nb
    a0_scale = prior_scale * total

    out: dict[str, float] = {}
    for w in vocab:
        ca, cb = a.get(w, 0), b.get(w, 0)
        prior = a0_scale * (ca + cb) / total
        if prior <= 0:
            continue
        la = math.log((ca + prior) / (na + a0_scale - ca - prior))
        lb = math.log((cb + prior) / (nb + a0_scale - cb - prior))
        var = 1.0 / (ca + prior) + 1.0 / (cb + prior)
        out[w] = (lb - la) / math.sqrt(var)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("a", nargs="+", help="比較元の JSONL (グロブ可)")
    ap.add_argument("--vs", nargs="+", required=True, help="比較先の JSONL")
    ap.add_argument("--top", type=int, default=30)
    ap.add_argument("--min-docs", type=int, default=30, help="両群でこの記事数未満の語は無視")
    ap.add_argument("--md", action="store_true")
    ap.add_argument("--out", help="全語のスコアを JSON で保存")
    args = ap.parse_args()

    import fugashi
    tagger = fugashi.Tagger()

    pa = [Path(x) for x in args.a]
    pb = [Path(x) for x in args.vs]
    print(f"A: {len(pa)} ファイル / B: {len(pb)} ファイル", file=sys.stderr)

    fa, da, na_docs = collect(pa, tagger)
    fb, db, nb_docs = collect(pb, tagger)
    print(f"A: {na_docs:,}記事 {len(fa):,}語 / B: {nb_docs:,}記事 {len(fb):,}語\n", file=sys.stderr)

    z = log_odds(fa, fb)
    rows = []
    for w, score in z.items():
        # どちらかで最低限の記事数に現れる語だけ見る
        if da.get(w, 0) + db.get(w, 0) < args.min_docs:
            continue
        ra = da.get(w, 0) / na_docs if na_docs else 0
        rb = db.get(w, 0) / nb_docs if nb_docs else 0
        rows.append((score, w, ra, rb, fa.get(w, 0), fb.get(w, 0)))
    rows.sort()

    if args.out:
        Path(args.out).write_text(json.dumps([
            {"word": w, "z": round(s, 3), "doc_ratio_a": round(ra, 5),
             "doc_ratio_b": round(rb, 5), "freq_a": ca, "freq_b": cb}
            for s, w, ra, rb, ca, cb in rows
        ], ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"保存: {args.out} ({len(rows):,}語)", file=sys.stderr)

    def render(title: str, subset: list) -> None:
        print(f"\n## {title}\n")
        if args.md:
            print("| 語 | z | A出現率 | B出現率 | 倍率 |")
            print("|----|---|---------|---------|------|")
            for s, w, ra, rb, _, _ in subset:
                r = f"{rb/ra:.1f}x" if ra > 0 else "新規"
                print(f"| {w} | {s:+.1f} | {ra*100:.1f}% | {rb*100:.1f}% | {r} |")
        else:
            print(f"{'語':<14} {'z':>7} {'A出現率':>9} {'B出現率':>9}  倍率")
            for s, w, ra, rb, _, _ in subset:
                r = f"{rb/ra:.1f}x" if ra > 0 else "新規"
                print(f"{w:<14} {s:>+7.1f} {ra*100:>8.1f}% {rb*100:>8.1f}%  {r}")

    render(f"B で増えた語 (上位{args.top})", rows[-args.top:][::-1])
    render(f"A に多かった語 (上位{args.top})", rows[: args.top])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
