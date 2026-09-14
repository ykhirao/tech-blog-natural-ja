#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""日本語 → 英語 → 日本語 の往復翻訳で、揺れる語を見つける。

ねらい: 同じ概念に複数の日本語があるとき、翻訳器がどれを選ぶかを見る。
「土台」を英訳して戻すと「基盤」になる、といった置き換わりを集める。

実データで観測した多極化(外来語の一強 → 和語が加わる)と突き合わせると、
どの語が互いに置き換え可能かが分かる。

翻訳には手元の `pid`(pi --provider ollama-cloud --model deepseek-v4-flash:cloud)を使う。
ollama-cloud 経由なので外部に送信される。送るのは Qiita の公開記事の
短い抜粋だけにしてある。

使い方:
    ./scripts/roundtrip.py --sentences 20
    ./scripts/roundtrip.py --file data/interim/samples.txt
    ./scripts/roundtrip.py --words 土台,経路,入口,部品
"""

from __future__ import annotations

import argparse
import json
import random
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"

sys.path.insert(0, str(ROOT / "scripts"))
from metrics import clean_inline, split_markdown, split_sentences  # noqa: E402

# 実データで多極化を確認した概念グループ(docs/metaphor-vocabulary.md)
GROUPS = {
    "土台": ["土台", "基盤", "ベース", "下地", "足場", "インフラ"],
    "経路": ["経路", "流れ", "パス", "ルート", "導線", "フロー"],
    "入口": ["入口", "入り口", "エントリ", "窓口", "受け口"],
    "部品": ["部品", "コンポーネント", "パーツ", "モジュール", "ブロック"],
    "境界": ["境界", "境目", "区切り", "切れ目", "線引き"],
    "仕組み": ["仕組み", "構造", "アーキテクチャ", "作り", "構成", "枠組み"],
}
ALL_WORDS = {w: g for g, ws in GROUPS.items() for w in ws}


def run_pid(prompt: str, timeout: int = 120) -> str | None:
    """pid に問い合わせる。失敗したら None。"""
    try:
        r = subprocess.run(["zsh", "-ic", "pid " + json.dumps(prompt, ensure_ascii=False)],
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    out = (r.stdout or "").strip()
    return out or None


def to_english(ja: str) -> str | None:
    return run_pid(
        "Translate this Japanese technical sentence to English. "
        "Output ONLY the English translation, nothing else.\n\n" + ja)


def to_japanese(en: str) -> str | None:
    return run_pid(
        "Translate this English sentence to natural Japanese. "
        "Output ONLY the Japanese translation, nothing else.\n\n" + en)


def sample_sentences(n: int, seed: int = 7) -> list[str]:
    """対象語を含む文を、実記事から集める。"""
    rng = random.Random(seed)
    files = sorted(RAW.glob("qiita_2026-08-*.jsonl"))
    rng.shuffle(files)
    out: list[str] = []
    for f in files[:12]:
        for line in f.open(encoding="utf-8"):
            item = json.loads(line)
            body = item.get("body") or ""
            if len(body) < 1000:
                continue
            text = clean_inline("\n".join(split_markdown(body)["body_lines"]))
            for s in split_sentences(text):
                s = s.strip()
                # 対象語を1つ含み、短すぎず長すぎない文
                if not (25 <= len(s) <= 90):
                    continue
                hits = [w for w in ALL_WORDS if w in s]
                if len(hits) != 1:
                    continue
                # コードや記号が多い文は避ける
                if len(re.findall(r"[A-Za-z0-9_./`]", s)) > len(s) * 0.3:
                    continue
                out.append(s)
                if len(out) >= n * 3:
                    break
            if len(out) >= n * 3:
                break
        if len(out) >= n * 3:
            break
    rng.shuffle(out)
    return out[:n]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sentences", type=int, default=15, help="試す文の数")
    ap.add_argument("--out", default="data/processed/roundtrip.jsonl")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    sents = sample_sentences(args.sentences, args.seed)
    if not sents:
        print("対象語を含む文が見つかりませんでした")
        return 1
    print(f"{len(sents)}文を往復翻訳します\n", file=sys.stderr)

    results = []
    changed = 0
    for i, ja in enumerate(sents, 1):
        before = [w for w in ALL_WORDS if w in ja]
        en = to_english(ja)
        if not en:
            print(f"  {i}: 英訳に失敗", file=sys.stderr)
            continue
        back = to_japanese(en)
        if not back:
            print(f"  {i}: 和訳に失敗", file=sys.stderr)
            continue
        after = [w for w in ALL_WORDS if w in back]
        lost = [w for w in before if w not in after]
        gained = [w for w in after if w not in before]
        rec = {"original": ja, "english": en, "back": back,
               "before": before, "after": after,
               "lost": lost, "gained": gained}
        results.append(rec)
        if lost or gained:
            changed += 1
            print(f"\n[{i}] {' '.join(lost)} → {' '.join(gained) or '(消失)'}")
            print(f"  元:   {ja[:70]}")
            print(f"  英:   {en[:70]}")
            print(f"  戻し: {back[:70]}")
        else:
            print(f"[{i}] 変化なし ({' '.join(before)})", file=sys.stderr)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with Path(args.out).open("w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"\n語が変わった: {changed}/{len(results)}文")
    # どの語がどの語に置き換わったかを集計
    pairs: dict[tuple[str, str], int] = {}
    for r in results:
        for a in r["lost"]:
            for b in r["gained"]:
                pairs[(a, b)] = pairs.get((a, b), 0) + 1
    if pairs:
        print("\n置き換わった組み合わせ:")
        for (a, b), n in sorted(pairs.items(), key=lambda x: -x[1]):
            same = "同じ概念" if ALL_WORDS.get(a) == ALL_WORDS.get(b) else "別概念"
            print(f"  {a} → {b}  ({n}回, {same})")
    print(f"\n保存: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
