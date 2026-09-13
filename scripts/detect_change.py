#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""どの年から文体が変わり始めたかを、事前に固定した閾値で判定する。

閾値は data/interim/change_threshold.json に入っている。
AI以前(2019年3〜8月)の月次変動幅の3倍を「月次のゆらぎでは説明できない」
ラインとし、**データを取得する前に**確定させた。結果を見てから線引きを
決めると後付けになるため。

形態素解析を使わない(生成済みの指標を読むだけ)ので、何度回しても安全。

使い方:
    ./scripts/detect_change.py
    ./scripts/detect_change.py --md
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROC = ROOT / "data" / "processed"
THRESHOLD = ROOT / "data" / "interim" / "change_threshold.json"

LABELS = {
    "chars_body": "地の文字数",
    "kanji_ratio": "漢字率",
    "burstiness_mora": "burstiness",
    "nominal_ending_ratio": "体言止め",
    "ten_per_sentence": "読点/文",
    "mtld": "MTLD",
    "list_ratio": "箇条書き",
    "has_matome_heading": "まとめ見出し",
}


def median_of(rows: list[dict], field: str) -> float | None:
    vals: list[float] = []
    for r in rows:
        v = r.get(field)
        if isinstance(v, bool):
            vals.append(1.0 if v else 0.0)
        elif isinstance(v, (int, float)):
            vals.append(float(v))
    return statistics.median(vals) if vals else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--md", action="store_true")
    args = ap.parse_args()

    if not THRESHOLD.exists():
        print(f"閾値ファイルがありません: {THRESHOLD}")
        return 1
    conf = json.loads(THRESHOLD.read_text(encoding="utf-8"))
    base, thr = conf["base"], conf["threshold"]

    # 8月だけを並べる(季節性を揃えるため)
    months = []
    for p in sorted(PROC.glob("metrics_*-08.jsonl")):
        label = p.stem.replace("metrics_", "")
        if len(label) == 7 and label[:4].isdigit():
            months.append(label)
    if not months:
        print("8月のデータがありません")
        return 1

    stats: dict[str, dict[str, float | None]] = {}
    counts: dict[str, int] = {}
    for m in months:
        rows = [json.loads(l) for l in (PROC / f"metrics_{m}.jsonl").open(encoding="utf-8") if l.strip()]
        counts[m] = len(rows)
        stats[m] = {f: median_of(rows, f) for f in LABELS}

    print("各年8月の指標と、AI以前の基準からのズレ")
    print("(◯ = 閾値内 / ● = 閾値超え。閾値は取得前に固定済み)\n")

    hdr = f"{'指標':<14}{'基準':>9}" + "".join(f"{m[:4]:>10}" for m in months)
    print(hdr)
    print("-" * len(hdr))

    first_change: dict[str, str] = {}
    for f, lbl in LABELS.items():
        b = base[f]["mean"]
        t = thr[f]
        line = f"{lbl:<14}{b:>9.3f}"
        for m in months:
            v = stats[m].get(f)
            if v is None:
                line += f"{'—':>10}"
                continue
            over = abs(v - b) > t if t > 0 else v != b
            mark = "●" if over else "◯"
            line += f"{v:>9.3f}{mark}"
            if over and f not in first_change and m[:4] != "2019":
                first_change[f] = m
        print(line)

    print(f"\n記事数: " + " / ".join(f"{m} {counts[m]:,}" for m in months))

    print("\n## 閾値を超えた最初の年")
    if first_change:
        by_year: dict[str, list[str]] = {}
        for f, m in first_change.items():
            by_year.setdefault(m, []).append(LABELS[f])
        for m in sorted(by_year):
            print(f"  {m}: {', '.join(by_year[m])}")
    else:
        print("  なし")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
