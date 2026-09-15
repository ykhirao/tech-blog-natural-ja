#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""textlint ルールが年ごとに何%の記事を指摘するかを測る。

参照分布は2020年8月で作った。その後 Qiita の書き方は大きく動いていて、
とくに2026年前半は急変している(docs/confounds-2026.md)。
**2020年基準のまま使い続けてよいか**を判断する材料が要る。

見たいのは2つ。

  誤検知   AI以前の記事をどれだけ指摘してしまうか(低いほどよい)
  検出     いまの記事をどれだけ指摘するか

どちらも「正解」がないので、良し悪しの判定はしない。
年ごとの推移を出して、閾値が実態と合っているかを見るだけ。

実行には node と textlint が要る(npm install 済みであること)。

使い方:
    ./scripts/rule_hits.py
    ./scripts/rule_hits.py --years 2020,2023,2026 --sample 200
    ./scripts/rule_hits.py --md > docs/rule-hits.md
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
RULEDIR = ROOT / "src" / "textlint"

sys.path.insert(0, str(ROOT / "scripts"))
from metrics import clean_inline, split_markdown  # noqa: E402


def sample_bodies(year: str, n: int, seed: int) -> list[str]:
    """その年8月から記事本文を n 件選ぶ。

    build_dataset.py の除外基準に近い条件で絞る。短すぎる記事や
    英語記事を入れると、ルールが沈黙するだけで測定にならない。
    """
    pool: list[str] = []
    for f in sorted(RAW.glob(f"qiita_{year}-08-*.jsonl")):
        for line in f.open(encoding="utf-8"):
            body = json.loads(line).get("body") or ""
            if len(body) < 1000:
                continue
            text = clean_inline("\n".join(split_markdown(body)["body_lines"]))
            if len(text) < 300:
                continue
            ja = sum(1 for c in text if "぀" <= c <= "ヿ" or "一" <= c <= "鿿")
            if ja / max(1, len(text)) < 0.30:
                continue
            pool.append(body)
    rnd = random.Random(seed)
    rnd.shuffle(pool)
    return pool[:n]


def kind_of(msg: str) -> str:
    """指摘の種類をメッセージから判別する。何が効いているかを見る。"""
    for key, label in [
        ("メリハリ", "文長のばらつき"),
        ("揃いすぎ", "文長が均一"),
        ("漢字が多く", "漢字率"),
        ("読点が多い", "読点"),
        ("太字が多い", "太字"),
    ]:
        if key in msg:
            return label
    return "翻訳調"


def run_detail(bodies: list[str], config: dict) -> tuple[int, Counter]:
    """指摘された記事数と、指摘の種類ごとの件数。"""
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        paths = []
        for i, b in enumerate(bodies):
            p = d / f"a{i:04d}.md"
            p.write_text(b, encoding="utf-8")
            paths.append(p)
        cfg = d / "rc.json"
        cfg.write_text(json.dumps(config), encoding="utf-8")
        r = subprocess.run(
            ["npx", "textlint", "--rulesdir", str(RULEDIR),
             "--config", str(cfg), "-f", "json"] + [str(p) for p in paths],
            cwd=ROOT, capture_output=True, text=True, timeout=1800,
        )
        if not r.stdout.strip():
            return 0, Counter()
        data = json.loads(r.stdout)
        hit = 0
        kinds: Counter = Counter()
        for f in data:
            msgs = f.get("messages", [])
            if msgs:
                hit += 1
            for m in msgs:
                kinds[kind_of(m.get("message", ""))] += 1
        return hit, kinds


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--years", default="2015,2018,2020,2022,2024,2026")
    ap.add_argument("--sample", type=int, default=200,
                    help="各年から何件見るか")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--md", action="store_true")
    args = ap.parse_args()

    if not (ROOT / "node_modules" / "textlint").exists():
        print("textlint がありません。npm install を先に実行してください",
              file=sys.stderr)
        return 1

    years = [y.strip() for y in args.years.split(",")]
    years = [y for y in years if list(RAW.glob(f"qiita_{y}-08-*.jsonl"))]

    configs = {
        "自前ルール": {"rules": {"qiita-tech-style": True}},
        "AI語彙辞書": {"rules": {"preset-ai-words-ja": True}},
    }

    rows = []
    for y in years:
        bodies = sample_bodies(y, args.sample, args.seed)
        if not bodies:
            continue
        rec: dict = {"year": y, "n": len(bodies)}
        for name, cfg in configs.items():
            hit, kinds = run_detail(bodies, cfg)
            rec[name] = hit / len(bodies) * 100
            if name == "自前ルール":
                rec["kinds"] = kinds
        rows.append(rec)
        print(f"  {y}: n={len(bodies)} "
              + " ".join(f"{k}={rec[k]:.1f}%" for k in configs), file=sys.stderr)

    if not rows:
        print("対象データがありません", file=sys.stderr)
        return 1

    if args.md:
        print("| 年 | n | " + " | ".join(configs) + " |")
        print("|----|---|" + "|".join(["---"] * len(configs)) + "|")
        for r in rows:
            print(f"| {r['year']} | {r['n']} | "
                  + " | ".join(f"{r[k]:.1f}%" for k in configs) + " |")
        print("\n自前ルールの内訳(指摘の件数)\n")
        kinds = sorted({k for r in rows for k in r.get("kinds", {})})
        print("| 年 | " + " | ".join(kinds) + " |")
        print("|----|" + "|".join(["---"] * len(kinds)) + "|")
        for r in rows:
            c = r.get("kinds", Counter())
            print(f"| {r['year']} | " + " | ".join(str(c.get(k, 0)) for k in kinds) + " |")
    else:
        print(f"\n{'年':<8}{'n':>6}" + "".join(f"{k:>14}" for k in configs))
        print("-" * 50)
        for r in rows:
            print(f"{r['year']:<8}{r['n']:>6}"
                  + "".join(f"{r[k]:>13.1f}%" for k in configs))
        print(f"\n自前ルールの内訳")
        kinds = sorted({k for r in rows for k in r.get("kinds", {})})
        print(f"{'年':<8}" + "".join(f"{k:>16}" for k in kinds))
        for r in rows:
            c = r.get("kinds", Counter())
            print(f"{r['year']:<8}" + "".join(f"{c.get(k,0):>16}" for k in kinds))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
