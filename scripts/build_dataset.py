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
import multiprocessing as mp
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, TimeoutError
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from metrics import analyze_with_pos, clean_inline, split_markdown  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed"

# この長さを超える記事は、形態素解析を使い捨てのプロセスに隔離して行う。
# 短い記事まで隔離するとプロセス起動のコストで極端に遅くなるため、
# 落ちる可能性がある長い記事だけを対象にする。
# 実際に落ちたのは 533,563字 の記事だが、余裕を持って低めに設定する。
ISOLATE_OVER_CHARS = 50_000

MIN_BODY_CHARS = 300  # 逆瀬川氏の基準に合わせる
MIN_SENTENCES = 5     # burstiness は文数が少ないと意味を成さない
# 日本語率は「日本語の記事か」の判定なので比率で見る。英語1万字に日本語3千字が
# 混ざった記事は、比率30%でも英語記事。
# ただし比率が同じでも日本語の絶対量が少ない記事は指標が不安定になるため、
# 絶対量の下限を別に設ける(1000字中300字と1万字中3千字を同列に扱わない)。
MIN_JA_RATIO = 0.30
MIN_JA_CHARS = 200    # 日本語文字そのものの下限
# コード量による除外は入れない。
# 指標はもともと split_markdown() がコードフェンス・表・箇条書きを落とした
# 「地の文」だけに対して計算している。コードがいくら多くても本文の分析は歪まず、
# 本文が痩せている記事は short_body が既に捕まえる。
# 実測: code_dominant で落ちた66件は地の文300〜597字あり、
# 「〜を作りました」「〜できるようにする」という解説記事だった。二重に切るのは誤り。
MIN_KANA_RATIO = 0.12 # かなが極端に少ない = 単語の羅列や設定ファイルの説明

# 日本語が主でない記事を弾く。英語記事や翻訳記事が混ざると文体分析が壊れる。
JA_CHARS = re.compile(r"[぀-ゟ゠-ヿ一-鿿]")
KANA = re.compile(r"[぀-ゟ゠-ヿ]")

# メモ書き・告知系。文体分析の母集団に入れると平均を歪める。
MEMO_TITLE = re.compile(
    r"(備忘録?|自分用メモ|個人用メモ|メモ$|メモ書き|ハンズオン記録|"
    r"日報|週報|学習記録|作業ログ|やったことリスト)",
)


def exclusion_reason(item: dict) -> str | None:
    """除外すべきなら理由を返す。分析対象なら None。

    Qiita には「コードを貼っただけ」「英語のみ」「備忘録」が相当数ある。
    これらは文体分析の対象ではないので落とす。実測した境界例では
    「地の文301字・コード426行」のような記事が通過していたため、
    文字数の絶対値だけでなく地の文とコードの比率も見る。
    """
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
    if ja / chars < MIN_JA_RATIO:
        return "not_japanese"
    if ja < MIN_JA_CHARS:
        return f"too_little_japanese(<{MIN_JA_CHARS})"

    # かな比率が低い = 名詞の羅列やコマンド説明で、文になっていない
    if len(KANA.findall(text)) / chars < MIN_KANA_RATIO:
        return "low_kana(word_list)"

    title = item.get("title") or ""
    if MEMO_TITLE.search(title):
        return "memo_post"

    return None


def _run_one(item: dict) -> dict | None:
    """1記事を解析する。子プロセスの中で呼ばれる。"""
    return analyze_with_pos(item["body"])


def analyze_isolated(item: dict, timeout: float = 60.0) -> tuple[dict | None, str]:
    """記事1本を別プロセスで解析する。落ちても呼び出し側は生き残る。

    fugashi(libmecab の C 拡張)は、解析中に MeCab が NULL を返したのを
    チェックせず参照するため SIGSEGV でプロセスごと落ちることがある。
    Python の例外にならないので try/except では捕まらない。
    実際に 2019-07-20 の記事1本でプール全体が BrokenProcessPool になり、
    その月の処理が丸ごと失敗した。

    そこで1本ずつ使い捨てのプロセスに隔離する。死んだらその記事だけ
    諦めて次に進む。戻り値は (結果, 理由)。
    """
    ctx = mp.get_context("spawn")
    with ProcessPoolExecutor(max_workers=1, mp_context=ctx) as ex:
        fut = ex.submit(_run_one, item)
        try:
            return fut.result(timeout=timeout), ""
        except BrokenProcessPool:
            return None, "segfault(morphological_analyzer)"
        except TimeoutError:
            return None, "timeout(morphological_analyzer)"
        except Exception as e:  # 通常の例外はここで拾う
            return None, f"error:{e.__class__.__name__}"


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
        # まず素直に解析する。ほとんどの記事はこれで通る。
        # 失敗した(あるいは形態素解析器が落ちうる長さの)ものだけ隔離して再試行する。
        m = None
        reason = ""
        if len(item.get("body") or "") > ISOLATE_OVER_CHARS:
            m, reason = analyze_isolated(item)
        else:
            try:
                m = analyze_with_pos(item["body"])
            except Exception as e:
                m, reason = None, f"error:{e.__class__.__name__}"
        if m is None:
            dropped.append({"id": item.get("id"), "created_at": item.get("created_at"),
                            "reason": reason or "analyze_failed"})
            continue
        if (m.get("n_sentences") or 0) < MIN_SENTENCES:
            dropped.append({"id": item.get("id"), "created_at": item.get("created_at"),
                            "reason": f"few_sentences(<{MIN_SENTENCES})"})
            continue
        # 指標の信頼度を記事ごとに持たせる。短い記事の burstiness は
        # 長い記事と同じ確からしさでは扱えないので、集計時に重みとして使う。
        # 除外ではなく重みにするのは、切り捨てると母集団が偏るため。
        n_sent = m.get("n_sentences") or 0
        weight = min(1.0, n_sent / 30)  # 30文で満点。それ未満は線形に減衰

        kept.append({
            "id": item.get("id"),
            "user_id": item.get("user_id"),
            "created_at": item.get("created_at"),
            "title": item.get("title"),
            "likes": item.get("likes_count"),
            "tags": item.get("tags"),
            "user_items_count": item.get("user_items_count"),
            "weight": round(weight, 4),
            **m,
        })
    return kept, dropped


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--months", help="例: 2024-06,2024-12")
    ap.add_argument("--all", action="store_true", help="data/raw の全月")
    ap.add_argument("--files", nargs="+",
                    help="任意の JSONL を直接指定する(部分集合の分析用)")
    ap.add_argument("--label", help="--files のときの出力名")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 1))
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    by_month: dict[str, list[Path]] = defaultdict(list)

    if args.files:
        # 任意のファイルを1グループとして扱う。AI話題を除いた部分集合のように、
        # 月名の規約に乗らないデータを分析するため。
        if not args.label:
            ap.error("--files には --label が要ります")
        paths = [Path(x) for x in args.files]
        missing = [p for p in paths if not p.exists()]
        if missing:
            print(f"存在しないファイル: {missing}")
            return 1
        by_month[args.label] = paths
        files = paths
    else:
        files = sorted(RAW.glob("qiita_*.jsonl"))
        if args.months:
            want = {m.strip() for m in args.months.split(",")}
            files = [f for f in files if f.stem.replace("qiita_", "")[:7] in want]
        elif not args.all:
            ap.error("--months / --all / --files のいずれかを指定してください")
        if not files:
            print("対象ファイルがありません")
            return 1
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
