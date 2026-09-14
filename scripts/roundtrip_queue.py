#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""往復翻訳を大量に回すためのキュー。同時実行しても壊れない。

設計:
- 仕事は JSONL の1行1件。id で区別する
- 取り出しは fcntl のファイルロックで排他する。複数プロセスが同時に
  走っても、同じ仕事を二重に処理しない
- 結果は追記のみ。途中で落ちても、完了済みは残る
- 再実行すると未処理だけ拾う(レジューム)

3段階を pid にやらせる:
  raw    元の日本語
  tran_en 英訳
  tran_ja 英語から戻した日本語
  diff    どの語が入れ替わったかの分析

使い方:
    # 1. 仕事を作る(実記事から文を抽出)
    ./scripts/roundtrip_queue.py build --count 5000

    # 2. 処理する(複数プロセスで同時に走らせてよい)
    ./scripts/roundtrip_queue.py work
    ./scripts/roundtrip_queue.py work &   # 並行するならこれを複数

    # 3. 進捗と集計
    ./scripts/roundtrip_queue.py status
    ./scripts/roundtrip_queue.py report
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import random
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
QDIR = ROOT / "data" / "roundtrip"
JOBS = QDIR / "jobs.jsonl"
DONE = QDIR / "done.jsonl"
LOCK = QDIR / ".lock"

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
    "道具": ["道具", "ツール", "手段", "仕掛け"],
    "確認": ["確認", "検証", "照合", "突き合わせる", "チェック"],
}
ALL_WORDS = {w: g for g, ws in GROUPS.items() for w in ws}


# --- ロック付きの読み書き ------------------------------------------------

class FileLock:
    """fcntl による排他ロック。同時実行しても取り出しが重複しない。"""

    def __init__(self, path: Path):
        self.path = path
        self.fh = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = self.path.open("a+")
        fcntl.flock(self.fh, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        if self.fh:
            fcntl.flock(self.fh, fcntl.LOCK_UN)
            self.fh.close()


def done_ids() -> set[str]:
    if not DONE.exists():
        return set()
    ids = set()
    for line in DONE.open(encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            ids.add(json.loads(line)["id"])
        except (json.JSONDecodeError, KeyError):
            continue
    return ids


def append_done(rec: dict) -> None:
    """結果を追記する。ロックするので同時に書いても混ざらない。"""
    with FileLock(LOCK):
        with DONE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())


def claim_jobs(n: int) -> list[dict]:
    """未処理の仕事を n 件取る。ロック中に done を読み直すので重複しない。"""
    with FileLock(LOCK):
        done = done_ids()
        out = []
        for line in JOBS.open(encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            job = json.loads(line)
            if job["id"] in done:
                continue
            out.append(job)
            if len(out) >= n:
                break
        # 取った分をすぐ「処理中」として記録する。
        # 落ちた場合は status --reset で戻せる。
        for job in out:
            with DONE.open("a", encoding="utf-8") as f:
                f.write(json.dumps(
                    {"id": job["id"], "state": "claimed",
                     "pid": os.getpid(), "at": time.time()},
                    ensure_ascii=False) + "\n")
        return out


# --- pid の呼び出し -------------------------------------------------------

def run_pid(prompt: str, timeout: int = 180, retries: int = 6) -> str | None:
    """pid に問い合わせる。429 のときは待って再試行する。

    ollama-cloud には同時接続の制限がある。実測すると5並列でも
    4つが `429 "too many concurrent requests"` で弾かれ、
    実質1リクエストずつしか通らなかった。
    並列を上げるほど失敗が増えるので、待って順番待ちする。
    """
    delay = 3.0
    for attempt in range(retries):
        try:
            r = subprocess.run(
                ["zsh", "-ic", "pid " + json.dumps(prompt, ensure_ascii=False)],
                capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return None
        out = (r.stdout or "").strip()
        err = (r.stderr or "")
        blob = out + err
        if "429" in blob or "too many concurrent" in blob.lower():
            # 待ち時間をずらして、複数ワーカーが同時に再開しないようにする
            time.sleep(delay + random.random() * 2)
            delay = min(delay * 1.8, 45)
            continue
        return out or None
    return None


def translate_roundtrip(ja: str, mode: str = "sentence") -> tuple[str | None, str | None]:
    unit = "text" if mode == "article" else "sentence"
    en = run_pid(
        f"Translate this Japanese technical {unit} to English. "
        f"Keep the structure and paragraph breaks. "
        f"Output ONLY the English translation, nothing else.\n\n" + ja,
        timeout=300 if mode == "article" else 180)
    if not en:
        return None, None
    back = run_pid(
        f"Translate this English {unit} to natural Japanese. "
        f"Keep the structure and paragraph breaks. "
        f"Output ONLY the Japanese translation, nothing else.\n\n" + en,
        timeout=300 if mode == "article" else 180)
    return en, back


# --- 仕事の生成 -----------------------------------------------------------

def build(count: int, years: list[str], seed: int, mode: str = "sentence",
          max_chars: int = 2000) -> int:
    """仕事を作る。

    mode="sentence": 対象語を含む1文だけを取る(翻訳が速い)
    mode="article":  記事の地の文をまるごと取る(実態に近いが遅い)

    article モードでは max_chars で頭打ちにする。
    翻訳器の入力上限と、1件あたりの所要時間を抑えるため。
    """
    rng = random.Random(seed)

    # 年ごとに均等に配分する。全ファイルをまとめてシャッフルすると、
    # 上限に達した時点で残りの年が丸ごと欠ける(実際 2019-2022 がゼロになった)。
    per_year = max(1, count // max(1, len(years)))
    files_by_year: dict[str, list] = {}
    for y in years:
        fs = sorted(RAW.glob(f"qiita_{y}-08-*.jsonl"))
        rng.shuffle(fs)
        if fs:
            files_by_year[y] = fs

    seen: set[str] = set()
    jobs: list[dict] = []
    for y, fs in files_by_year.items():
        year_start = len(jobs)
        for f in fs:
            if len(jobs) - year_start >= per_year or len(jobs) >= count:
                break
            year = f.stem.replace("qiita_", "")[:4]
            for line in f.open(encoding="utf-8"):
                # 年あたりの上限は内側でも見る。外側(ファイル単位)だけだと
                # 1ファイルの中で上限を大きく超えてしまい、後ろの年が
                # 丸ごと欠ける(実際 2019年が143件になり 2023/2026 がゼロだった)。
                if len(jobs) - year_start >= per_year or len(jobs) >= count:
                    break
                item = json.loads(line)
                body = item.get("body") or ""
                if len(body) < 1000 or item.get("slide"):
                    continue
                text = clean_inline("\n".join(split_markdown(body)["body_lines"]))

                if mode == "article":
                    # 地の文をまるごと。長すぎるものは句点で切り詰める。
                    t = re.sub(r"\n{3,}", "\n\n", text).strip()
                    if len(t) < 300:
                        continue
                    if len(t) > max_chars:
                        cut = t.rfind("。", 0, max_chars)
                        t = t[: cut + 1] if cut > max_chars // 2 else t[:max_chars]
                    hits = sorted({w for w in ALL_WORDS if w in t})
                    if not hits:
                        continue
                    jobs.append({
                        "id": f"{item['id']}_a",
                        "year": year,
                        "article_id": item["id"],
                        "mode": "article",
                        "raw": t,
                        "target_word": hits[0],
                        "target_words": hits,
                        "group": ALL_WORDS[hits[0]],
                        "chars": len(t),
                    })
                    # ここで break すると1ファイル(=1日)あたり1件しか取れない。
                    # 実際そうなっていて、31日×6年=186件で頭打ちになった。
                    # article モードは1記事が1件なので、次の記事へ進めばよい。
                    continue

                for s in split_sentences(text):
                    s = s.strip()
                    if not (25 <= len(s) <= 90):
                        continue
                    hits = [w for w in ALL_WORDS if w in s]
                    if len(hits) != 1:
                        continue
                    # コードや記号が多い文は翻訳が荒れるので避ける
                    if len(re.findall(r"[A-Za-z0-9_./`]", s)) > len(s) * 0.3:
                        continue
                    if s in seen:
                        continue
                    seen.add(s)
                    jobs.append({
                        "id": f"{item['id']}_{len(jobs)}",
                        "year": year,
                        "article_id": item["id"],
                        "mode": "sentence",
                        "raw": s,
                        "target_word": hits[0],
                        "target_words": hits,
                        "group": ALL_WORDS[hits[0]],
                    })
                    break  # 1記事1文まで

    QDIR.mkdir(parents=True, exist_ok=True)
    with JOBS.open("w", encoding="utf-8") as f:
        for j in jobs:
            f.write(json.dumps(j, ensure_ascii=False) + "\n")
    by_group = Counter(j["group"] for j in jobs)
    by_year = Counter(j["year"] for j in jobs)
    print(f"{len(jobs)}件の仕事を作成: {JOBS}")
    print(f"  概念別: {dict(by_group.most_common())}")
    print(f"  年別:   {dict(sorted(by_year.items()))}")
    return 0


# --- 処理 -----------------------------------------------------------------

def work(batch: int, limit: int | None) -> int:
    if not JOBS.exists():
        print("先に build してください")
        return 1
    processed = 0
    while True:
        if limit is not None and processed >= limit:
            break
        jobs = claim_jobs(min(batch, (limit - processed) if limit else batch))
        if not jobs:
            print("未処理の仕事がありません")
            break
        for job in jobs:
            en, back = translate_roundtrip(job["raw"], job.get("mode", "sentence"))
            if not en or not back:
                append_done({**job, "state": "failed"})
                print(f"  失敗 {job['id']}", file=sys.stderr)
                continue
            before = [w for w in ALL_WORDS if w in job["raw"]]
            after = [w for w in ALL_WORDS if w in back]
            rec = {
                **job, "state": "done",
                "tran_en": en, "tran_ja": back,
                "before": before, "after": after,
                "lost": [w for w in before if w not in after],
                "gained": [w for w in after if w not in before],
            }
            append_done(rec)
            processed += 1
            mark = ""
            if rec["lost"] or rec["gained"]:
                mark = f"  {' '.join(rec['lost'])} → {' '.join(rec['gained']) or '(消失)'}"
            print(f"[{processed}] {job['target_word']}{mark}")
    return 0


# --- 状態と集計 -----------------------------------------------------------

def status(reset_stale: bool) -> int:
    total = sum(1 for _ in JOBS.open(encoding="utf-8")) if JOBS.exists() else 0
    states: Counter = Counter()
    claimed_at: dict[str, float] = {}
    finished: set[str] = set()
    if DONE.exists():
        for line in DONE.open(encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            st = r.get("state", "done")
            if st == "claimed":
                claimed_at[r["id"]] = r.get("at", 0)
            else:
                finished.add(r["id"])
                states[st] += 1
    stale = [i for i, t in claimed_at.items()
             if i not in finished and time.time() - t > 900]
    print(f"仕事:     {total:,}")
    print(f"完了:     {states.get('done', 0):,}")
    print(f"失敗:     {states.get('failed', 0):,}")
    print(f"処理中:   {len([i for i in claimed_at if i not in finished]):,}")
    print(f"未処理:   {total - len(finished) - len([i for i in claimed_at if i not in finished]):,}")
    if stale:
        print(f"\n15分以上応答のない仕事: {len(stale)}件")
        if reset_stale:
            with FileLock(LOCK):
                lines = [l for l in DONE.open(encoding="utf-8")
                         if l.strip() and json.loads(l).get("id") not in stale]
            DONE.write_text("".join(lines), encoding="utf-8")
            print(f"  → 未処理に戻しました")
        else:
            print(f"  --reset で未処理に戻せます")
    return 0


def report() -> int:
    if not DONE.exists():
        print("結果がありません")
        return 1
    recs = []
    for line in DONE.open(encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        if r.get("state") == "done":
            recs.append(r)
    if not recs:
        print("完了した仕事がありません")
        return 1

    changed = [r for r in recs if r["lost"] or r["gained"]]
    print(f"完了 {len(recs):,}件 / 語が変わった {len(changed):,}件 "
          f"({len(changed)/len(recs)*100:.1f}%)\n")

    pairs: Counter = Counter()
    vanished: Counter = Counter()
    for r in changed:
        if not r["gained"]:
            for a in r["lost"]:
                vanished[a] += 1
        for a in r["lost"]:
            for b in r["gained"]:
                pairs[(a, b)] += 1

    print("## 置き換わった組み合わせ(上位30)\n")
    print(f"{'元の語':<14}{'戻った語':<14}{'回数':>6}  概念")
    print("-" * 50)
    for (a, b), n in pairs.most_common(30):
        same = "同じ" if ALL_WORDS.get(a) == ALL_WORDS.get(b) else "別"
        print(f"{a:<14}{b:<14}{n:>6}  {same}")

    if vanished:
        print("\n## 往復で消えた語(上位15)\n")
        for w, n in vanished.most_common(15):
            print(f"  {w:<14}{n:>5}回")

    # 語ごとの「生き残り率」
    print("\n## 語ごとの生き残り率(往復しても同じ語が残る割合)\n")
    surv: dict[str, list[int]] = {}
    for r in recs:
        w = r["target_word"]
        surv.setdefault(w, []).append(1 if w in r["after"] else 0)
    rows = [(sum(v) / len(v), w, len(v)) for w, v in surv.items() if len(v) >= 5]
    rows.sort()
    print(f"{'語':<14}{'生き残り':>9}{'件数':>6}")
    print("-" * 32)
    for rate, w, n in rows:
        print(f"{w:<14}{rate*100:>8.1f}%{n:>6}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="仕事を作る")
    b.add_argument("--count", type=int, default=5000)
    b.add_argument("--years", default="2019,2020,2021,2022,2023,2026")
    b.add_argument("--seed", type=int, default=7)
    b.add_argument("--mode", choices=["sentence", "article"], default="sentence",
                   help="sentence=対象語を含む1文 / article=地の文まるごと")
    b.add_argument("--max-chars", type=int, default=2000,
                   help="article モードでの1件あたりの上限文字数")

    w = sub.add_parser("work", help="処理する(並行実行可)")
    w.add_argument("--batch", type=int, default=5, help="一度に取る件数")
    w.add_argument("--limit", type=int, help="このプロセスで処理する上限")

    s = sub.add_parser("status", help="進捗")
    s.add_argument("--reset", action="store_true", help="止まった仕事を戻す")

    sub.add_parser("report", help="集計")

    args = ap.parse_args()
    if args.cmd == "build":
        return build(args.count, [y.strip() for y in args.years.split(",")], args.seed,
                     args.mode, args.max_chars)
    if args.cmd == "work":
        return work(args.batch, args.limit)
    if args.cmd == "status":
        return status(args.reset)
    return report()


if __name__ == "__main__":
    raise SystemExit(main())
