#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""p1ass さんの AI語彙辞書を、手元のコーパスで外部検証する。

[textlint-rule-preset-ai-words-ja](https://github.com/p1ass/textlint-rule-preset-ai-words-ja)
は「AI が書いた文章で多用される語」を集めた辞書。観察をもとに作られている。

こちらには 2011〜2026 年の Qiita 記事がある。**AI が存在しなかった時代の
日本語が丸ごと残っている**ので、辞書の語が本当に AI 以後に増えたのかを
後から検証できる。辞書の作者にはできなかった検証になる。

測り方を2つ出す。どちらか片方では判断を誤る:

  記事出現率   その語を含む記事の割合(%)。記事が長くなるだけで上がる
  千字あたり   延べ出現数を地の文の長さで割る。記事長の影響を受けない

実際、頻出500語の分析では正規化前の結論が誤りだった
(docs/word-trends-500.md)。同じ罠を踏まないよう両方を出す。

使い方:
    ./scripts/verify_ai_words.py
    ./scripts/verify_ai_words.py --years 2015,2018,2020,2022,2024,2026
    ./scripts/verify_ai_words.py --md > docs/verify-ai-words.md
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
DICT_JS = ROOT / "node_modules" / "textlint-rule-preset-ai-words-ja" / "lib" / "dictionary.js"

sys.path.insert(0, str(ROOT / "scripts"))
from metrics import clean_inline, split_markdown  # noqa: E402

# 辞書の語のうち、正規表現にするとき素直に書けないもの。
# 「〜に落ちる」のような形は、そのままでは語として検索できない。
SPECIAL = {
    "〜に落ちる": r"に落ち",
    "〜から引く": r"から引[くいかけ]",
    "〜した瞬間": r"した瞬間",
    "値を動かす": r"値を動か",
    "既定では": r"既定では",
    "配線する": r"配線",
    "黙って": r"黙って",
    "静かに": r"静かに",
}

# 活用する語。基本形だけで検索すると取りこぼす。
CONJUGATE = {
    "効く": r"効[くきかけい]",
    "壊れる": r"壊れ",
    "走る": r"走[るりらっ]",
    "焼く": r"焼[くきかけい]",
    "崩す": r"崩[すしさせ]",
    "太る": r"太[るりらっ]",
    "見張る": r"見張[るりらっ]",
    "疑う": r"疑[うわいっ]",
    "見落とす": r"見落と[すしさせ]",
    "突き合わせる": r"突き合わせ",
    "断定": r"断定",
    "混ざる": r"混ざ[るりらっ]",
    "破綻": r"破綻",
    "素通り": r"素通り",
    "切り分ける": r"切り分け",
    "潰す": r"潰[すしさせ]",
    "踏み込む": r"踏み込[むみまめん]",
    "溶かす": r"溶か[すしさせ]",
    "漏れ": r"漏れ",
}


# 対照群。辞書に入っておらず、AI とは関係のない一般的な技術語。
# 辞書語が全部増えたとき、「正規化が効いていないだけ」を疑う必要がある。
# 対照語が同じように増えていたら測り方の問題、減っていれば本物。
CONTROL = ["設定", "使用", "必要", "実装", "以下", "確認", "処理", "追加"]


def load_dictionary() -> list[str]:
    """辞書から語だけを取り出す。node が要る。"""
    if not DICT_JS.exists():
        print(f"辞書が見つかりません: {DICT_JS}\n"
              "  npm install を先に実行してください", file=sys.stderr)
        raise SystemExit(1)
    js = (
        f"const {{dictionary}} = require({str(DICT_JS)!r});"
        "console.log(JSON.stringify(dictionary.map("
        "e => (e.message.match(/^\"([^\"]+)\"/) || [])[1]).filter(Boolean)));"
    )
    out = subprocess.run(["node", "-e", js], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout
    # 辞書には同じ語が2回入っているものがある(「静かに」)。順序を保って重複を除く。
    return list(dict.fromkeys(json.loads(out)))


def to_pattern(word: str) -> str:
    if word in SPECIAL:
        return SPECIAL[word]
    if word in CONJUGATE:
        return CONJUGATE[word]
    return re.escape(word)


def scan_year(year: str, pats: dict[str, re.Pattern]) -> tuple[Counter, Counter, int, int]:
    """その年8月の記事を走査する。

    返すもの: (語を含む記事数, 延べ出現数, 記事数, 地の文の総字数)

    地の文だけを見る。コードブロックに出る「走る」「穴」を数えると
    語彙の話ではなくなる。
    """
    docs: Counter = Counter()
    hits: Counter = Counter()
    n = 0
    chars = 0
    for f in sorted(RAW.glob(f"qiita_{year}-08-*.jsonl")):
        for line in f.open(encoding="utf-8"):
            body = json.loads(line).get("body") or ""
            if len(body) < 1000:
                continue
            text = clean_inline("\n".join(split_markdown(body)["body_lines"]))
            if len(text) < 300:
                continue
            n += 1
            chars += len(text)
            for name, rx in pats.items():
                found = rx.findall(text)
                if found:
                    docs[name] += 1
                    hits[name] += len(found)
    return docs, hits, n, chars


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--years", default="2015,2017,2019,2020,2021,2022,2023,2024,2025,2026")
    ap.add_argument("--ai-year", default="2022",
                    help="この年までを AI 以前とする")
    ap.add_argument("--md", action="store_true", help="Markdown で出す")
    ap.add_argument("--min-docs", type=int, default=30,
                    help="どの年でもこの記事数に届かない語は除く")
    args = ap.parse_args()

    words = load_dictionary()
    controls = [c for c in CONTROL if c not in words]
    pats = {w: re.compile(to_pattern(w)) for w in words + controls}
    print(f"辞書の語: {len(words)} / 対照群: {len(controls)}", file=sys.stderr)

    years = [y.strip() for y in args.years.split(",")]
    years = [y for y in years if list(RAW.glob(f"qiita_{y}-08-*.jsonl"))]
    if len(years) < 3:
        print("3年分以上のデータが要ります", file=sys.stderr)
        return 1

    docs: dict[str, Counter] = {}
    hits: dict[str, Counter] = {}
    ns: dict[str, int] = {}
    chars: dict[str, int] = {}
    for y in years:
        d, h, n, c = scan_year(y, pats)
        docs[y], hits[y], ns[y], chars[y] = d, h, n, c
        print(f"  {y}: {n:,}記事 / 地の文{c//max(1,n):,}字", file=sys.stderr)

    pre = [y for y in years if y <= args.ai_year]
    post = [y for y in years if y > args.ai_year]
    if len(pre) < 2 or not post:
        print("AI 以前が2年分、以後が1年分以上必要です", file=sys.stderr)
        return 1

    rows = []
    ctrl_rows = []
    for w in words + controls:
        if max(docs[y].get(w, 0) for y in years) < args.min_docs:
            continue
        rate = [docs[y].get(w, 0) / ns[y] * 100 for y in years]
        norm = [hits[y].get(w, 0) / max(1, chars[y]) * 1000 for y in years]

        def slope(vals: list[float], ys: list[str]) -> float:
            i0, i1 = years.index(ys[0]), years.index(ys[-1])
            span = int(ys[-1]) - int(ys[0])
            return (vals[i1] - vals[i0]) / span if span else 0.0

        (ctrl_rows if w in controls else rows).append({
            "word": w,
            "rate": rate,
            "norm": norm,
            # AI 以後の傾きは、AI 以前の最後の年を起点にする。
            # post だけで測ると 2023→2026 になり、変化の始まりを跨がない。
            "rate_pre": slope(rate, pre),
            "rate_post": slope(rate, [pre[-1]] + post),
            "norm_pre": slope(norm, pre),
            "norm_post": slope(norm, [pre[-1]] + post),
            "norm_first": norm[0],
            "norm_last": norm[-1],
        })

    # AI 以後の伸び(正規化後)が大きい順
    rows.sort(key=lambda r: r["norm_post"], reverse=True)
    ctrl_rows.sort(key=lambda r: r["norm_post"], reverse=True)

    grew = [r for r in rows if r["norm_post"] > 0 and r["norm_last"] > r["norm_first"]]
    shrank = [r for r in rows if r["norm_last"] < r["norm_first"]]
    # AI 以前から増えていた語は、AI が原因とは言えない
    pre_grew = [r for r in rows if r["norm_pre"] > 0]

    if args.md:
        def table(rs: list[dict]) -> None:
            print("| 語 | " + " | ".join(years) + " | AI以前/年 | AI以後/年 |")
            print("|----|" + "|".join(["---"] * (len(years) + 2)) + "|")
            for r in rs:
                cells = " | ".join(f"{v:.3f}" for v in r["norm"])
                print(f"| {r['word']} | {cells} | "
                      f"{r['norm_pre']:+.4f} | {r['norm_post']:+.4f} |")

        print("## 辞書の語(千字あたり)\n")
        table(rows)
        print("\n## 対照群(辞書に無い一般語)\n")
        table(ctrl_rows)
    else:
        allr = rows + ctrl_rows
        w = max((len(r["word"]) for r in allr), default=4) + 2

        def show(rs: list[dict], title: str) -> None:
            print(f"\n{title}")
            print(f"{'語':<{w}}" + "".join(f"{y:>9}" for y in years)
                  + f"{'以前/年':>10}{'以後/年':>10}")
            print("-" * (w + 9 * len(years) + 20))
            for r in rs:
                line = f"{r['word']:<{w}}" + "".join(f"{v:>9.3f}" for v in r["norm"])
                print(line + f"{r['norm_pre']:>+10.4f}{r['norm_post']:>+10.4f}")

        show(rows, "## 辞書の語(千字あたり)")
        show(ctrl_rows, "## 対照群(辞書に無い一般語)")

    print(f"\n対象語 {len(rows)} / 辞書 {len(words)}", file=sys.stderr)
    print(f"  AI以後に増えた: {len(grew)}", file=sys.stderr)
    print(f"  AI以後に減った: {len(shrank)}", file=sys.stderr)
    print(f"  AI以前から増えていた: {len(pre_grew)}", file=sys.stderr)
    cg = [r for r in ctrl_rows if r["norm_last"] > r["norm_first"]]
    print(f"対照群 {len(ctrl_rows)} のうち増えた: {len(cg)}", file=sys.stderr)
    if ctrl_rows and len(cg) >= len(ctrl_rows) * 0.8:
        print("  警告: 対照語もほぼ全部増えている。正規化が効いていない疑い",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
