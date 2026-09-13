#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["fugashi[unidic-lite]>=1.3"]
# ///
"""文章が、AI以前の技術記事の分布からどれだけ離れているかを出す。

「AIが書いたか」は判定しない。出すのは参照分布上の位置(パーセンタイル)と、
指標ごとのズレの大きさだけ。判断は読み手に残す。

なぜ判定しないか:
- 「AIしか使わない語」を実データで探したが、存在しなかった。
  最も強かった「自律」でもAI記事率88%で、非AI記事の1.2%が使う。
  しかもそれは文体ではなく話題の語(AIについて書けば人間でも使う)。
  AI以前の2020年にも13本が使っていた。
- 非ネイティブ話者の誤検出率が高いことが先行研究で示されている
  (Liang et al. 2023, Patterns)。誤検出は実在の書き手を不当に貶める。

使い方:
    ./scripts/style_distance.py 記事.md
    ./scripts/style_distance.py 記事.md --json
    ./scripts/style_distance.py *.md --rank    # 離れている順に並べる
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from metrics import analyze_with_pos  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PROFILE = ROOT / "src" / "profile" / "qiita-tech-2020.json"

# 参照分布と照らす指標。direction は「どちら側が参照から外れる方向か」。
WATCH = [
    ("burstiness_mora", "文長のメリハリ", "low"),
    ("cv_sentence_chars", "文長のばらつき", "low"),
    ("nominal_ending_ratio", "体言止め率", "low"),
    ("kanji_ratio", "漢字割合", "high"),
    ("ten_per_sentence", "読点/文", "high"),
    ("bold_per_1k", "太字/千字", "high"),
    ("list_ratio", "箇条書き割合", "high"),
    ("paragraph_sentences_cv", "段落文数のばらつき", "low"),
    ("mtld", "語彙多様性", "two"),
    ("mean_sentence_chars", "平均文長", "two"),
]


def percentile_of(value: float, spec: dict) -> float:
    """参照分布の中で、その値がおよそ何パーセンタイルかを線形補間で出す。"""
    pts = [(spec["p10"], 10), (spec["p25"], 25), (spec["p50"], 50),
           (spec["p75"], 75), (spec["p90"], 90)]
    if value <= pts[0][0]:
        return max(0.0, 10 * value / pts[0][0]) if pts[0][0] else 0.0
    if value >= pts[-1][0]:
        return 95.0
    for (v1, p1), (v2, p2) in zip(pts, pts[1:]):
        if v1 <= value <= v2:
            if v2 == v1:
                return float(p1)
            return p1 + (p2 - p1) * (value - v1) / (v2 - v1)
    return 50.0


def bar(pct: float, width: int = 21) -> str:
    """パーセンタイル位置を棒で示す。中央が p50。"""
    pos = int(pct / 100 * (width - 1))
    cells = ["·"] * width
    cells[width // 2] = "|"
    cells[pos] = "●"
    return "".join(cells)


def evaluate(md: str, profile: dict) -> dict:
    m = analyze_with_pos(md)
    M = profile["metrics"]
    rows = []
    for key, label, direction in WATCH:
        v = m.get(key)
        spec = M.get(key)
        if v is None or spec is None:
            continue
        pct = percentile_of(float(v), spec)
        # 参照から外れている度合い。中央から離れるほど大きい。
        if direction == "low":
            dev = max(0.0, 50 - pct) / 50
        elif direction == "high":
            dev = max(0.0, pct - 50) / 50
        else:
            dev = abs(pct - 50) / 50
        rows.append({"key": key, "label": label, "value": float(v),
                     "percentile": round(pct, 1), "deviation": round(dev, 3),
                     "median": spec["p50"]})
    rows.sort(key=lambda r: -r["deviation"])
    overall = statistics.fmean([r["deviation"] for r in rows]) if rows else 0.0
    return {"metrics": m, "rows": rows, "overall_deviation": round(overall, 3)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--rank", action="store_true", help="離れている順に一覧")
    args = ap.parse_args()

    profile = json.loads(PROFILE.read_text(encoding="utf-8"))

    results = []
    for fp in args.files:
        p = Path(fp)
        try:
            md = p.read_text(encoding="utf-8")
        except OSError as e:
            print(f"{fp}: 読めません ({e})", file=sys.stderr)
            continue
        r = evaluate(md, profile)
        r["file"] = str(p)
        results.append(r)

    if args.json:
        print(json.dumps([{k: v for k, v in r.items() if k != "metrics"}
                          for r in results], ensure_ascii=False, indent=2))
        return 0

    if args.rank:
        results.sort(key=lambda r: -r["overall_deviation"])
        print(f"{'ズレ':>6}  ファイル")
        print("-" * 60)
        for r in results:
            top = r["rows"][0]["label"] if r["rows"] else ""
            print(f"{r['overall_deviation']:>6.3f}  {Path(r['file']).name}  ({top})")
        print("\n注: ズレが大きい=参照分布から離れている。AI判定ではない。")
        return 0

    for r in results:
        print(f"\n## {r['file']}")
        print(f"参照分布(AI以前のQiita技術記事)からの平均的なズレ: "
              f"{r['overall_deviation']:.3f}\n")
        print(f"{'指標':<18}{'値':>9}{'中央値':>9}  {'低い':<10}{'高い':<11} 位置")
        print("-" * 72)
        for row in r["rows"]:
            print(f"{row['label']:<18}{row['value']:>9.3f}{row['median']:>9.3f}  "
                  f"{bar(row['percentile'])} p{row['percentile']:.0f}")
        print("\n● が現在位置、| が参照分布の中央値。")
        print("これは指標と分布上の位置であって、AIが書いたかの判定ではない。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
