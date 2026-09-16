#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""引用ブロックの「中身」を分類して推移を見る。

structure_trend.py は引用を**使う記事の割合**が2026年に2倍になったことまでを
出した。何を引用しているのかは見ていない。ここを埋める。

分類は本文の見た目だけで決める。外部の判定器は使わない
(記事単位の AI 判定はしないと決めてある。ここで見るのは
「引用という記法が何に使われているか」であって、書き手の判定ではない)。

使い方:
    ./scripts/quote_kinds.py --years 2015,2020,2022,2026
    ./scripts/quote_kinds.py --months 2026-01,2026-08 --samples 5
"""

from __future__ import annotations

import argparse
import glob
import json
import re
from collections import Counter

ROOT = __file__.rsplit("/scripts/", 1)[0]
RAW = f"{ROOT}/data/raw"

# 実データを見て決めた印。決め打ちの名前リストでは拾えなかったので、
# 「行の形」で拾う(絵文字だけの話者、**ラベル**: の囲み、など)。
EMOJI = (
    "\U0001F300-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF"
    "\u2139\u2194-\u21AA\uFE0F\u200D\u3030"
)
# 話者行: 行頭が「絵文字だけ」か「短い名前」で、直後にコロン。
# 会話の引用は、この形か「かぎ括弧」で始まる。
SPEAKER = re.compile(
    rf"^(?:[{EMOJI}]+\s*[:：]"                      # 🧑‍💻：
    rf"|[{EMOJI}]+\s*\*{{0,2}}[^\n:：]{{1,14}}\*{{0,2}}\s*\n\s*[「\"]"  # 🤔 名前\n「…
    rf"|(?:\*\*)?(?:ユーザー|User|あなた|私|筆者|AI|アシスタント|Assistant|"
    rf"ChatGPT|GPT|Claude|Gemini|Copilot|Cursor|Devin|エージェント|先輩|後輩)"
    rf"(?:\*\*)?\s*[:：])"
)
# 囲み: **注意**: のように、短いラベルを太字にして本文が続く形。
CALLOUT_WORDS = (
    "注意|注記|警告|注|補足|ポイント|メモ|まとめ|結論|前提|免責|用語|学び|"
    "観測したこと|受講メモ|検証日|収集日時|つまずきポイント|注意事項|セキュリティ注記|"
    "NOTE|Note|TIP|Tips?|WARNING|Warning|CAUTION|IMPORTANT"
)
CALLOUT = re.compile(
    # 語で拾う形 (注意: / **補足** / 【CC補足】)
    rf"^(?:[{EMOJI}]+\s*)?"
    rf"(?:\*\*|【)?(?:{CALLOUT_WORDS})[^\n]{{0,12}}?(?:\*\*|】)?\s*[:：]"
    rf"|^(?:[{EMOJI}]+\s*)?(?:\*\*|【)(?:{CALLOUT_WORDS})[^\n]{{0,12}}?(?:\*\*|】)"
    # 形で拾う形。語を列挙しきれないので、囲みの見た目そのものを条件にする:
    #   ※で始まる / 絵文字で始まる / 【…】で始まる / 短い太字ラベル+コロン
    rf"|^※"
    rf"|^[{EMOJI}]+\s*\S"
    rf"|^【[^】\n]{{1,16}}】"
    rf"|^\*\*[^*\n]{{1,20}}[:：]?\*\*\s*[:：]?\s*(?:\n|$)"
    rf"|^\*\*[^*\n]{{1,20}}\*\*\s*[:：]"
)
# 帰属表示。「— 出典」「出典:」「via」など。
ATTRIB = re.compile(r"(?:^|\n)\s*(?:[—–]{1,2}|出典|引用元|元記事|参考|via)\s*[:：]?\s*\S")
URL = re.compile(r"https?://")
CODEISH = re.compile(r"^[$#]\s|^\s*(?:\w+@|C:\\|/usr/|npm |pip |sudo |git )")
ERRORISH = re.compile(
    r"(?:Error|error|Exception|Traceback|warning:|WARN|FATAL|"
    r"Status Code:|\bE\d{3,}\b|CS\d{4}|\bexit code\b)"
)
JA = re.compile(r"[ぁ-んァ-ヶ一-龥]")


def classify(b: str) -> str:
    """引用ブロック1つを、見た目の特徴で1カテゴリに割り当てる。

    先に判定したものが勝つ。順番は「その印があれば他の可能性を覆す」
    強さの順に並べてある。
    """
    head = b.lstrip()[:80]
    if SPEAKER.search(head):
        return "対話"
    if CALLOUT.search(head):
        return "囲み"
    if ERRORISH.search(b):
        return "エラー"
    if CODEISH.search(head):
        return "コード"
    # 帰属表示か URL があれば、どこかから引いてきたもの
    if ATTRIB.search(b) or URL.search(b):
        return "出典つき"
    ja = len(JA.findall(b))
    if ja == 0 and len(b) > 20:
        return "英文"
    return "地の文"


ORDER = ["対話", "囲み", "エラー", "コード", "出典つき", "英文", "地の文"]


def quote_blocks(body: str) -> list[str]:
    """コードブロックの中を除いて、連続する `>` 行をまとめて返す。"""
    out: list[str] = []
    cur: list[str] = []
    in_code = False
    for ln in body.split("\n"):
        s = ln.strip()
        if s.startswith("```") or s.startswith("~~~"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if s.startswith(">"):
            cur.append(s.lstrip(">").strip())
        elif cur:
            out.append("\n".join(cur))
            cur = []
    if cur:
        out.append("\n".join(cur))
    return [b for b in out if b.strip()]


def scan(month: str, days: int) -> tuple[Counter, Counter, int, int, dict]:
    """ブロック数と「その種類を使う記事数」の両方を返す。

    ブロック数だけだと、引用を1,567個使う記事1本が月全体の比率を
    塗り替えてしまう(2025-08 で実際に起きた)。記事単位も併せて見る。
    """
    kinds: Counter = Counter()
    arts: Counter = Counter()
    n_articles = 0
    n_quoting = 0
    samples: dict = {}
    files = sorted(glob.glob(f"{RAW}/qiita_{month}-*.jsonl"))[:days]
    for p in files:
        with open(p, encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                r = json.loads(line)
                if r.get("slide") or not r.get("body"):
                    continue
                n_articles += 1
                bs = quote_blocks(r["body"])
                if bs:
                    n_quoting += 1
                seen = set()
                for b in bs:
                    k = classify(b)
                    kinds[k] += 1
                    seen.add(k)
                    samples.setdefault(k, []).append(b[:120])
                for k in seen:
                    arts[k] += 1
    return kinds, arts, n_articles, n_quoting, samples


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--years", default="2015,2018,2020,2022,2024,2026",
                    help="各年8月を見る (既定)")
    ap.add_argument("--months", help="年月を直接指定 (例: 2026-01,2026-08)")
    ap.add_argument("--days", type=int, default=8, help="各月の先頭何日分か")
    ap.add_argument("--samples", type=int, default=0, help="分類ごとに何件か例を出す")
    ap.add_argument("--md", action="store_true", help="Markdown の表で出す")
    ap.add_argument("--by", choices=("article", "block"), default="article",
                    help="記事単位(既定)か、ブロック単位か")
    args = ap.parse_args()

    months = (args.months.split(",") if args.months
              else [f"{y}-08" for y in args.years.split(",")])

    rows = []
    last_samples: dict = {}
    for m in months:
        kinds, arts, n, nq, samples = scan(m, args.days)
        total = sum(kinds.values())
        if not total:
            print(f"{m}: データなし")
            continue
        rows.append((m, n, nq, total, kinds, arts))
        last_samples = samples

    sep = " | " if args.md else "  "
    unit = "記事%" if args.by == "article" else "ブロック%"
    head = ["月", "記事数", "引用あり%", "引用数"] + [f"{k}{unit}" for k in ORDER]
    if args.md:
        print("| " + " | ".join(head) + " |")
        print("|" + "|".join("---" for _ in head) + "|")
    else:
        print(sep.join(head))
    for m, n, nq, total, kinds, arts in rows:
        cells = [m, f"{n:,}", f"{nq / n * 100:.1f}", f"{total:,}"]
        if args.by == "article":
            # 全記事に対する割合。引用のある記事だけを母数にすると
            # 「引用が増えた」ぶんが見えなくなる。
            cells += [f"{arts[k] / n * 100:.2f}" for k in ORDER]
        else:
            cells += [f"{kinds[k] / total * 100:.1f}" for k in ORDER]
        line = sep.join(cells)
        print(f"| {line} |" if args.md else line)

    if args.samples and last_samples:
        print(f"\n## 例 ({months[-1]})\n")
        for k in ORDER:
            for b in last_samples.get(k, [])[: args.samples]:
                print(f"- **{k}**: {b!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
