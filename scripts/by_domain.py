#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""タグで分野に分けて、指標の推移を出す。

2026年前半に急変が起きているが、原因が分かっていない
([docs/confounds-2026.md](../docs/confounds-2026.md))。
**特定の分野から始まったのか**を確かめるための道具。

分野の定義はここに置く。docs に表だけ残して定義を残さないと、
後から再現できなくなる(実際そうなっていた)。

使い方:
    ./scripts/by_domain.py --months 2024-08,2025-08,2026-02,2026-08
    ./scripts/by_domain.py --field ten_per_sentence --md
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROC = ROOT / "data" / "processed"

# タグから分野を決める。上から順に見て、最初に当たったものを採る。
# 1記事が複数分野のタグを持つことがあるため、順序に意味がある。
DOMAINS: list[tuple[str, set[str]]] = [
    ("Python/ML", {
        "python", "python3", "機械学習", "deeplearning", "pytorch",
        "tensorflow", "pandas", "numpy", "scikit-learn", "jupyter",
        "自然言語処理", "データ分析", "keras",
    }),
    ("Web frontend", {
        "javascript", "typescript", "react", "vue.js", "vue", "nextjs",
        "next.js", "css", "html", "nuxt", "angular", "svelte", "frontend",
    }),
    ("Web backend", {
        "ruby", "rails", "php", "laravel", "go", "java", "spring",
        "node.js", "nodejs", "django", "api", "rest-api", "graphql",
    }),
    ("Infra/Cloud", {
        "aws", "docker", "kubernetes", "terraform", "gcp", "azure",
        "linux", "ci", "github-actions", "nginx", "infrastructure",
        "devops", "sre",
    }),
    ("Mobile", {
        "ios", "android", "swift", "kotlin", "flutter", "reactnative",
        "react-native", "unity", "xcode",
    }),
    ("AI/LLM", {
        "chatgpt", "openai", "llm", "生成ai", "claude", "gemini",
        "langchain", "rag", "prompt", "copilot", "cursor", "devin",
        "aiエージェント", "mcp",
    }),
]

FIELDS = {
    "nominal_ending_ratio": "体言止め",
    "ten_per_sentence": "読点/文",
    "burstiness_mora": "文長のばらつき",
    "kanji_ratio": "漢字率",
    "chars_body": "地の文字数",
    "bold_per_1k": "太字/千字",
}


def domain_of(tags: list[str] | None) -> str:
    """記事の分野。当たらなければ「その他」。"""
    low = {(t or "").lower() for t in (tags or [])}
    for name, keys in DOMAINS:
        if low & keys:
            return name
    return "その他"


def load(month: str) -> list[dict]:
    f = PROC / f"metrics_{month}.jsonl"
    if not f.exists():
        return []
    return [json.loads(l) for l in f.open(encoding="utf-8") if l.strip()]


def med(rows: list[dict], field: str) -> float | None:
    v = [r[field] for r in rows if isinstance(r.get(field), (int, float))]
    return statistics.median(v) if v else None


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--months",
                    default="2024-08,2025-02,2025-08,2026-02,2026-05,2026-08")
    ap.add_argument("--field", default="nominal_ending_ratio",
                    choices=list(FIELDS))
    ap.add_argument("--min-articles", type=int, default=100,
                    help="この件数に満たない分野は出さない")
    ap.add_argument("--md", action="store_true")
    args = ap.parse_args()

    months = [m.strip() for m in args.months.split(",")]
    months = [m for m in months if load(m)]
    if len(months) < 2:
        print("2か月分以上のデータが要ります", file=sys.stderr)
        return 1

    names = [n for n, _ in DOMAINS] + ["その他"]
    table: dict[str, dict[str, tuple[float | None, int]]] = {}
    for m in months:
        rows = load(m)
        buckets: dict[str, list[dict]] = {n: [] for n in names}
        for r in rows:
            buckets[domain_of(r.get("tags"))].append(r)
        table[m] = {n: (med(rs, args.field), len(rs)) for n, rs in buckets.items()}

    label = FIELDS[args.field]
    shown = [n for n in names
             if all(table[m][n][1] >= args.min_articles for m in months)]

    if args.md:
        print(f"## {label} を分野別に\n")
        print("| 分野 | " + " | ".join(months) + " | 変化 |")
        print("|------|" + "|".join(["---"] * (len(months) + 1)) + "|")
        for n in shown:
            vals = [table[m][n][0] for m in months]
            cells = " | ".join(f"{v:.3f}" if v is not None else "—" for v in vals)
            d = (vals[-1] - vals[0]) if vals[0] is not None and vals[-1] is not None else None
            print(f"| {n} | {cells} | " + (f"{d:+.3f}" if d is not None else "—") + " |")
        print("\n記事数\n")
        print("| 分野 | " + " | ".join(months) + " |")
        print("|------|" + "|".join(["---"] * len(months)) + "|")
        for n in shown:
            print(f"| {n} | " + " | ".join(f"{table[m][n][1]:,}" for m in months) + " |")
    else:
        w = max(len(n) for n in shown) + 2
        print(f"\n{label}\n")
        print(f"{'分野':<{w}}" + "".join(f"{m:>11}" for m in months) + f"{'変化':>10}")
        print("-" * (w + 11 * len(months) + 10))
        for n in shown:
            vals = [table[m][n][0] for m in months]
            line = f"{n:<{w}}" + "".join(
                f"{v:>11.3f}" if v is not None else f"{'—':>11}" for v in vals)
            if vals[0] is not None and vals[-1] is not None:
                line += f"{vals[-1] - vals[0]:>+10.3f}"
            print(line)
        print(f"\n記事数")
        print(f"{'分野':<{w}}" + "".join(f"{m:>11}" for m in months))
        for n in shown:
            print(f"{n:<{w}}" + "".join(f"{table[m][n][1]:>11,}" for m in months))

    skipped = [n for n in names if n not in shown]
    if skipped:
        print(f"\n件数不足で除外: {', '.join(skipped)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
