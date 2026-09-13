#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["fugashi[unidic-lite]>=1.3"]
# ///
"""生 JSONL に除外基準をかけ、指標を付けた分析用データセットを作る。

除外基準は逆瀬川氏の分析(docs/qiita-writing-before-after-ai.md)に合わせつつ、
Qiita の実分布を見て決めている。2024-12-01 の706件を実測したところ、
地の文の p05 が112字で、コード貼り付けだけの記事がかなり混ざっていた。

出力は data/processed/metrics_YYYY-MM.jsonl(記事1行)。
除外した記事も理由付きで data/processed/excluded_YYYY-MM.jsonl に残す。
あとで「除外が厳しすぎないか」を検証できるようにするため。

使い方:
    ./scripts/build_dataset.py --months 2024-12
    ./scripts/build_dataset.py --all
    ./scripts/build_dataset.py --all --workers 8
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from metrics import analyze_with_pos, clean_inline, split_markdown  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed"

MIN_BODY_CHARS = 300  # 逆瀬川氏の基準に合わせる
MIN_SENTENCES = 5     # burstiness は文数が少ないと意味を成さない

# 日本語が主でない記事を弾く。英語記事や翻訳記事が混ざると文体分析が壊れる。
JA_CHARS = re.compile(r"[぀-ゟ゠-ヿ一-鿿]")


def exclusion_reason(item: dict) -> str | None:
    """除外すべきなら理由を返す。分析対象なら None。"""
    if item.get("private"):
        return "private"
    if item.get("slide"):
        return "slide_mode"  # スライドモードは文章構造が別物
    body = item.get("body") or ""
    if not body.strip():
        return "empty_body"

    parts = split_markdown(body)
    text = clean_inline("\n".join(parts["body_lines"]))
    chars = len(re.sub(r"\s", "", text))
    if chars < MIN_BODY_CHARS:
        return f"short_body(<{MIN_BODY_CHARS})"
    ja = len(JA_CHARS.findall(text))
    if chars and ja / chars < 0.3:
        return "not_japanese"
    return None


def process_file(path: Path) -> tuple[list[dict], list[dict]]:
    kept: list[dict] = []
    dropped: list[dict] = []
    for line in path.open(encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        item = json.loads(line)
        reason = exclusion_reason(item)
        if reason:
            dropped.append({"id": item.get("id"), "created_at": item.get("created_at"),
                            "reason": reason})
            continue
        try:
            m = analyze_with_pos(item["body"])
        except Exception as e:  # 1本のせいで全体を止めない
            dropped.append({"id": item.get("id"), "created_at": item.get("created_at"),
                            "reason": f"error:{e.__class__.__name__}"})
            continue
        if (m.get("n_sentences") or 0) < MIN_SENTENCES:
            dropped.append({"id": item.get("id"), "created_at": item.get("created_at"),
                            "reason": f"few_sentences(<{MIN_SENTENCES})"})
            continue
        kept.append({
            "id": item.get("id"),
            "user_id": item.get("user_id"),
            "created_at": item.get("created_at"),
            "title": item.get("title"),
            "likes": item.get("likes_count"),
            "tags": item.get("tags"),
            "user_items_count": item.get("user_items_count"),
            **m,
        })
    return kept, dropped


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--months", help="例: 2024-06,2024-12")
    ap.add_argument("--all", action="store_true", help="data/raw の全月")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 1))
    args = ap.parse_args()

    files = sorted(RAW.glob("qiita_*.jsonl"))
    if args.months:
        want = {m.strip() for m in args.months.split(",")}
        files = [f for f in files if f.stem.replace("qiita_", "")[:7] in want]
    elif not args.all:
        ap.error("--months か --all を指定してください")
    if not files:
        print("対象ファイルがありません")
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    by_month: dict[str, list[Path]] = defaultdict(list)
    for f in files:
        by_month[f.stem.replace("qiita_", "")[:7]].append(f)

    print(f"対象 {len(files)} 日分 / {len(by_month)} か月 (workers={args.workers})")
    total_kept = 0
    total_drop: Counter = Counter()

    for month, paths in sorted(by_month.items()):
        kept_all: list[dict] = []
        drop_all: list[dict] = []
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            for kept, dropped in ex.map(process_file, paths):
                kept_all.extend(kept)
                drop_all.extend(dropped)

        with (OUT / f"metrics_{month}.jsonl").open("w", encoding="utf-8") as f:
            for r in kept_all:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        with (OUT / f"excluded_{month}.jsonl").open("w", encoding="utf-8") as f:
            for r in drop_all:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

        reasons = Counter(r["reason"] for r in drop_all)
        total_kept += len(kept_all)
        total_drop.update(reasons)
        top = " ".join(f"{k}={v}" for k, v in reasons.most_common(3))
        print(f"  {month}: 採用 {len(kept_all):>6,} / 除外 {len(drop_all):>6,}  {top}")

    print(f"\n合計 採用 {total_kept:,} 件")
    print("除外の内訳:")
    for k, v in total_drop.most_common():
        print(f"  {k:<28} {v:>8,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
