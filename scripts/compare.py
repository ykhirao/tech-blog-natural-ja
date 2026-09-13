#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""2群の指標を比較する。差の大きさと、著者単位ブートストラップの信頼区間を出す。

著者単位でリサンプリングするのは、多作な著者ひとりの癖が全体を動かすのを
防ぐため(逆瀬川氏の分析と同じ方針)。記事単位でやると独立性の仮定が崩れる。

「AIが原因」とは言えない点に注意。ここで出るのは2時点の差であって、
その理由がAIかどうかは別の話。docs の限界の節を参照。

使い方:
    ./scripts/compare.py data/processed/metrics_2020-08.jsonl \
                         data/processed/metrics_2026-08.jsonl
    ./scripts/compare.py A.jsonl B.jsonl --boot 1000 --md
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from collections import defaultdict
from pathlib import Path

SKIP = {"id", "user_id", "created_at", "title", "url", "tags", "likes",
        "user_items_count", "weight"}


def wmean(pairs: list[tuple[float, float]]) -> float:
    """加重平均。重みは build_dataset.py が付けた指標の信頼度。

    短い記事の burstiness は長い記事と同じ確からしさでは扱えないので、
    文数に応じた重みで平均する。重みが無いデータでは単純平均に戻る。
    """
    tw = sum(w for _, w in pairs)
    if tw <= 0:
        return statistics.fmean([v for v, _ in pairs]) if pairs else float("nan")
    return sum(v * w for v, w in pairs) / tw


def load(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.open(encoding="utf-8") if l.strip()]


def numeric_fields(rows: list[dict]) -> list[str]:
    seen: dict[str, int] = defaultdict(int)
    for r in rows[:2000]:
        for k, v in r.items():
            if k in SKIP:
                continue
            if isinstance(v, bool) or isinstance(v, (int, float)):
                seen[k] += 1
    return [k for k, n in seen.items() if n >= 10]


def vals(rows: list[dict], field: str) -> list[float]:
    out = []
    for r in rows:
        v = r.get(field)
        if isinstance(v, bool):
            out.append(1.0 if v else 0.0)
        elif isinstance(v, (int, float)):
            out.append(float(v))
    return out


def wvals(rows: list[dict], field: str) -> list[tuple[float, float]]:
    """(値, 重み) の組を返す。重みが無い行は 1.0 とみなす。"""
    out = []
    for r in rows:
        v = r.get(field)
        w = r.get("weight")
        w = float(w) if isinstance(w, (int, float)) else 1.0
        if isinstance(v, bool):
            out.append((1.0 if v else 0.0, w))
        elif isinstance(v, (int, float)):
            out.append((float(v), w))
    return out


def by_author(rows: list[dict]) -> dict[str, list[dict]]:
    d: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        d[r.get("user_id") or r.get("id")].append(r)
    return d


def boot_ci(a_rows: list[dict], b_rows: list[dict], field: str, n: int,
            rng: random.Random) -> tuple[float, float] | None:
    """著者単位で復元抽出し、差(B-A)の95%区間を返す。"""
    ga, gb = by_author(a_rows), by_author(b_rows)
    ka, kb = list(ga), list(gb)
    if len(ka) < 5 or len(kb) < 5:
        return None
    diffs = []
    for _ in range(n):
        sa = [r for k in rng.choices(ka, k=len(ka)) for r in ga[k]]
        sb = [r for k in rng.choices(kb, k=len(kb)) for r in gb[k]]
        va, vb = vals(sa, field), vals(sb, field)
        if not va or not vb:
            continue
        diffs.append(statistics.fmean(vb) - statistics.fmean(va))
    if len(diffs) < n // 2:
        return None
    diffs.sort()
    lo = diffs[int(0.025 * (len(diffs) - 1))]
    hi = diffs[int(0.975 * (len(diffs) - 1))]
    return lo, hi


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("a", help="比較元 (例: 2020-08)")
    ap.add_argument("b", help="比較先 (例: 2026-08)")
    ap.add_argument("--boot", type=int, default=400, help="ブートストラップ回数")
    ap.add_argument("--md", action="store_true", help="Markdown表で出力")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    A, B = load(Path(args.a)), load(Path(args.b))
    la, lb = Path(args.a).stem.replace("metrics_", ""), Path(args.b).stem.replace("metrics_", "")

    print(f"{la}: {len(A):,}件 / 著者 {len(by_author(A)):,}人")
    print(f"{lb}: {len(B):,}件 / 著者 {len(by_author(B)):,}人\n")

    fields = [f for f in numeric_fields(A) if f in numeric_fields(B)]
    results = []
    for f in fields:
        va, vb = vals(A, f), vals(B, f)
        if len(va) < 30 or len(vb) < 30:
            continue
        ma, mb = statistics.fmean(va), statistics.fmean(vb)
        sd = statistics.pstdev(va)
        # AI以前の標準偏差で標準化(Cohen の d 相当)。差の大きさを比較可能にする
        d = (mb - ma) / sd if sd > 0 else 0.0
        ratio = (mb / ma) if ma not in (0,) else float("nan")
        ci = boot_ci(A, B, f, args.boot, rng)
        results.append((abs(d), f, ma, mb, d, ratio, ci))

    results.sort(reverse=True)

    if args.md:
        print(f"| 指標 | {la} | {lb} | 差(標準化) | 倍率 | 95%CI |")
        print("|------|------|------|-----------|------|-------|")
        for _, f, ma, mb, d, ratio, ci in results:
            cis = f"[{ci[0]:+.3f}, {ci[1]:+.3f}]" if ci else "—"
            rs = f"{ratio:.2f}x" if math.isfinite(ratio) else "—"
            print(f"| `{f}` | {ma:.3f} | {mb:.3f} | **{d:+.2f}** | {rs} | {cis} |")
    else:
        print(f"{'指標':<28} {la:>10} {lb:>10} {'差(SD)':>8} {'倍率':>7}  95%CI")
        print("-" * 88)
        for _, f, ma, mb, d, ratio, ci in results:
            cis = f"[{ci[0]:+.3f},{ci[1]:+.3f}]" if ci else "—"
            rs = f"{ratio:.2f}x" if math.isfinite(ratio) else "—"
            sig = "" if (ci and ci[0] <= 0 <= ci[1]) else " *"
            print(f"{f:<28} {ma:>10.3f} {mb:>10.3f} {d:>+8.2f} {rs:>7}  {cis}{sig}")
        print("\n* = 95%区間が0を含まない(差がある方向は確か)")
        print("注: これは2時点の差であって、原因がAIだとは言えない")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
