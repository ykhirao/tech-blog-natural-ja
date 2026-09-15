#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""ある期間の文体変化に対して、対抗仮説をまとめて潰す。

「2時点で値が違う」だけでは、その理由は言えない。考えられる別の説明を
先に潰しておかないと、変化そのものを主張できない。

潰す対抗仮説:

  話題      AI を扱う記事が増えただけではないか
            → AI に言及する記事を全部除いて測り直す
  書き手    多作な人の書き方が混ざっただけではないか
            → 著者1人につき1本に絞って測り直す
  新規参入  新しく来た人が違う書き方をしているだけではないか
            → 前の期間にも書いていた著者だけで測り直す
  人気      いいねが多い記事に引きずられていないか
            → いいね数の層ごとに測り直す

どれも「除いても変化が残るか」を見る。残れば、その説明では足りない。

使い方:
    ./scripts/confounds.py 2026-01 2026-08
    ./scripts/confounds.py 2021-08 2023-08 --md
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROC = ROOT / "data" / "processed"
RAW = ROOT / "data" / "raw"

FIELDS = [
    ("nominal_ending_ratio", "体言止め", "{:.3f}"),
    ("ten_per_sentence", "読点/文", "{:.3f}"),
    ("burstiness_mora", "文長のばらつき", "{:.3f}"),
    ("kanji_ratio", "漢字率", "{:.3f}"),
    ("chars_body", "地の文字数", "{:,.0f}"),
    ("mtld", "MTLD", "{:.2f}"),
]

# AI を扱う記事の判定。タイトルとタグで見る。本文は「AIで書いた」とだけ
# 触れている記事も拾ってしまい、話題が AI とは限らないため使わない。
AI_RE = re.compile(
    r"(?:ChatGPT|GPT-?[0-9]|Claude|Gemini|Copilot|LLM|生成AI|生成系AI"
    r"|プロンプト|RAG|LangChain|Ollama|Cursor|DeepSeek|Devin"
    r"|AIエージェント|機械学習|ディープラーニング)",
    re.I,
)


def load(month: str) -> list[dict]:
    f = PROC / f"metrics_{month}.jsonl"
    if not f.exists():
        print(f"{f} がありません。build_dataset.py を先に実行してください",
              file=sys.stderr)
        raise SystemExit(1)
    return [json.loads(l) for l in f.open(encoding="utf-8") if l.strip()]


def med(rows: list[dict], field: str) -> float | None:
    vals = [r[field] for r in rows if isinstance(r.get(field), (int, float))]
    return statistics.median(vals) if vals else None


def is_ai_topic(r: dict) -> bool:
    text = (r.get("title") or "") + " " + " ".join(r.get("tags") or [])
    return bool(AI_RE.search(text))


def one_per_author(rows: list[dict]) -> list[dict]:
    """著者1人につき最初の1本だけ残す。

    多作な人が中央値を引っ張っていないかを見る。
    """
    seen: set[str] = set()
    out = []
    for r in rows:
        u = r.get("user_id")
        if u and u not in seen:
            seen.add(u)
            out.append(r)
    return out


def returning_only(rows: list[dict], prev_authors: set[str]) -> list[dict]:
    """前の期間にも書いていた著者だけ残す。

    新しく来た人が違う書き方をしているだけ、という説明を潰す。
    """
    return [r for r in rows if r.get("user_id") in prev_authors]


def by_likes(rows: list[dict], lo: int, hi: int | None) -> list[dict]:
    out = []
    for r in rows:
        k = r.get("likes")
        if not isinstance(k, (int, float)):
            continue
        if k >= lo and (hi is None or k < hi):
            out.append(r)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("a", help="比較元の月 (例: 2026-01)")
    ap.add_argument("b", help="比較先の月 (例: 2026-08)")
    ap.add_argument("--md", action="store_true", help="Markdown で出す")
    args = ap.parse_args()

    A, B = load(args.a), load(args.b)
    authors_a = {r["user_id"] for r in A if r.get("user_id")}

    cases: list[tuple[str, list[dict], list[dict]]] = [
        ("全体", A, B),
        ("AI関連を除く",
         [r for r in A if not is_ai_topic(r)],
         [r for r in B if not is_ai_topic(r)]),
        ("著者1人1本", one_per_author(A), one_per_author(B)),
        ("前期にも書いた人だけ", A, returning_only(B, authors_a)),
        ("いいね0", by_likes(A, 0, 1), by_likes(B, 0, 1)),
        ("いいね1〜9", by_likes(A, 1, 10), by_likes(B, 1, 10)),
        ("いいね10以上", by_likes(A, 10, None), by_likes(B, 10, None)),
    ]

    # 全体の差を基準にして、各条件で何割が残るかを見る
    base: dict[str, float] = {}
    for f, _, _ in FIELDS:
        x, y = med(A, f), med(B, f)
        if x is not None and y is not None:
            base[f] = y - x

    rows_out = []
    for name, sa, sb in cases:
        if not sa or not sb:
            rows_out.append((name, len(sa), len(sb), {}))
            continue
        diffs = {}
        for f, _, _ in FIELDS:
            x, y = med(sa, f), med(sb, f)
            if x is not None and y is not None:
                diffs[f] = (x, y, y - x)
        rows_out.append((name, len(sa), len(sb), diffs))

    def fmt_case(name, na, nb, diffs) -> list[str]:
        cells = []
        for f, _, _ in FIELDS:
            if f not in diffs:
                cells.append("—")
                continue
            _, _, d = diffs[f]
            b0 = base.get(f)
            # 全体の差に対する残存率。100%なら全部残っている
            pct = f" ({d / b0 * 100:.0f}%)" if b0 else ""
            cells.append(f"{d:+.3f}{pct}" if abs(d) < 100 else f"{d:+,.0f}{pct}")
        return cells

    if args.md:
        print(f"## {args.a} → {args.b} の差と、条件を変えたときの残り方\n")
        print("| 条件 | n(前) | n(後) | " + " | ".join(l for _, l, _ in FIELDS) + " |")
        print("|------|------|------|" + "|".join(["---"] * len(FIELDS)) + "|")
        for name, na, nb, diffs in rows_out:
            print(f"| {name} | {na:,} | {nb:,} | "
                  + " | ".join(fmt_case(name, na, nb, diffs)) + " |")
    else:
        w = max(len(n) for n, _, _, _ in rows_out) + 2
        print(f"\n{args.a} → {args.b} の差(括弧は全体の差に対する残存率)\n")
        print(f"{'条件':<{w}}{'n(前)':>8}{'n(後)':>8}"
              + "".join(f"{l:>17}" for _, l, _ in FIELDS))
        print("-" * (w + 16 + 17 * len(FIELDS)))
        for name, na, nb, diffs in rows_out:
            cells = fmt_case(name, na, nb, diffs)
            print(f"{name:<{w}}{na:>8,}{nb:>8,}"
                  + "".join(f"{c:>17}" for c in cells))

    print(f"\n判定: 各条件で差が残っていれば、その説明では足りない",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
