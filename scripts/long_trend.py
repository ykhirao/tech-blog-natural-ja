#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""表現の長期推移を見て、AI以前からの傾向とAI以後の急増を切り分ける。

「英語文化の流入で以前から増えていた」のか「AI以後に急に増えた」のかは、
2点の比較では区別できない。AI以前の傾きが分かれば判定できる。

生データを直接読むので、build_dataset.py を通していない年でも使える
(形態素解析も不要なので速い)。

使い方:
    ./scripts/long_trend.py --years 2015,2016,2017,2018,2019,2020,2021,2022,2023,2026
    ./scripts/long_trend.py --preset conclusion    # 結論を示す表現
    ./scripts/long_trend.py --preset ai-words      # AI語彙の一部
    ./scripts/long_trend.py --pattern "つまり:つまり" --pattern "要約:要約すると"
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"

PRESETS = {
    # 結論・要約を示す表現。英語圏の慣習(TL;DR)やPREP法の影響を見る
    "conclusion": {
        "TL;DR": r"(?:TL;?DR|tl;?dr)",
        "結論から": r"結論(?:から|を先に)",
        "まとめ(見出し)": r"^#+ *まとめ",
        "まとめると": r"まとめると",
        "つまり": r"つまり",
        "一言で言うと": r"(?:一言|ひとこと)で(?:言う|いう)と",
        "結果として": r"結果として",
        "帰結": r"帰結",
        "最後に": r"^最後に",
        "すなわち": r"すなわち",
        "要するに": r"要するに",
        "端的に言えば": r"端的に(?:言|い)",
    },
    # p1ass さんの辞書から、特徴的な語を抜粋
    "ai-words": {
        "実測": r"実測",
        "経路": r"経路",
        "土台": r"土台",
        "核心": r"核心",
        "照合": r"照合",
        "切り分ける": r"切り分け",
        "正本": r"正本",
        "落とし穴": r"落とし穴",
    },
    # 英語構文の直訳
    "translationese": {
        "重要なのは": r"重要なのは",
        "という点です": r"という点です",
        "の観点": r"(?:の|という)観点",
        "我々は/私たちは": r"(?:我々|私たち)[はが]",
        "したがって": r"^(?:したがって|従って)",
        "しかしながら": r"しかしながら",
        "〜されている": r"されている",
    },
}


def scan_year(year: str, pats: dict[str, str]) -> tuple[Counter, int]:
    """その年8月の記事で、各パターンを含む記事数を数える。"""
    counts: Counter = Counter()
    n = 0
    for f in sorted(RAW.glob(f"qiita_{year}-08-*.jsonl")):
        for line in f.open(encoding="utf-8"):
            body = json.loads(line).get("body") or ""
            if len(body) < 1000:  # 短すぎる記事は除く
                continue
            n += 1
            for name, rx in pats.items():
                if re.search(rx, body, re.M | re.I):
                    counts[name] += 1
    return counts, n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--years", default="2015,2016,2017,2018,2019,2020,2021,2022,2023,2026")
    ap.add_argument("--preset", choices=list(PRESETS), default="conclusion")
    ap.add_argument("--pattern", action="append", default=[],
                    help="名前:正規表現 の形で個別指定")
    ap.add_argument("--ai-year", default="2022",
                    help="AI以前/以後の境目(この年までを以前とする)")
    ap.add_argument("--md", action="store_true")
    args = ap.parse_args()

    pats = dict(PRESETS[args.preset])
    for spec in args.pattern:
        if ":" in spec:
            k, v = spec.split(":", 1)
            pats[k] = v

    years = [y.strip() for y in args.years.split(",")]
    res: dict[str, dict] = {}
    for y in years:
        if not list(RAW.glob(f"qiita_{y}-08-*.jsonl")):
            continue
        c, n = scan_year(y, pats)
        res[y] = {k: c[k] / n * 100 for k in pats}
        res[y]["_n"] = n

    got = [y for y in years if y in res]
    if len(got) < 2:
        print("2年分以上のデータが要ります")
        return 1

    # AI以前の年だけで傾きを出す
    pre_years = [y for y in got if y <= args.ai_year]
    post_years = [y for y in got if y > args.ai_year]

    def slope(ys: list[str], key: str) -> float | None:
        if len(ys) < 2:
            return None
        a, b = ys[0], ys[-1]
        span = int(b) - int(a)
        return (res[b][key] - res[a][key]) / span if span else None

    print(f"記事出現率(%)の推移  ※AI以前 = {args.ai_year}年まで\n")
    hdr = f"{'表現':<16}" + "".join(f"{y:>8}" for y in got)
    hdr += f"{'AI前/年':>10}{'AI後/年':>10}{'判定':>12}"
    print(hdr)
    print("-" * len(hdr))

    for k in pats:
        pre = slope(pre_years, k)
        post = slope(post_years, k)
        line = f"{k:<16}" + "".join(f"{res[y][k]:>8.2f}" for y in got)
        line += f"{pre:>+10.3f}" if pre is not None else f"{'—':>10}"
        line += f"{post:>+10.3f}" if post is not None else f"{'—':>10}"
        # AI以前から増えていたか、AI以後に急増したか
        if pre is not None and post is not None:
            if pre > 0.05 and post > pre * 2:
                verdict = "以前から+加速"
            elif pre > 0.05:
                verdict = "以前から"
            elif post > 0.05:
                verdict = "AI以後のみ"
            elif post < -0.05:
                verdict = "減少"
            else:
                verdict = "変化なし"
            line += f"{verdict:>12}"
        print(line)

    print(f"\n記事数: " + " ".join(f"{y}:{res[y]['_n']:,}" for y in got))
    print("\n判定の読み方:")
    print("  以前から      = 英語文化の流入など、AI以外の理由で増えていた")
    print("  以前から+加速 = 元からの傾向が AI 以後に増幅された")
    print("  AI以後のみ    = AI 以前は動いておらず、以後に急増した")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
