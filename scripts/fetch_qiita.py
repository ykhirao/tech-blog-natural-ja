#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx>=0.27"]
# ///
"""Qiita API v2 から指定期間の記事を取得して JSONL に落とす。

Qiita API には page<=100 / per_page<=100 の制約があり、1クエリで 10,000 件しか
取れない。12月は月あたり 13,000〜19,500 件あるため月単位では取りこぼす。
そこで日単位に切って取得し、日ごとに 10,000 件を超える場合のみ警告する。

レジューム対応: 取得済みの日は data/raw/qiita_YYYY-MM-DD.jsonl の存在で判定し、
デフォルトでスキップする(--force で再取得)。

使い方:
    ./scripts/fetch_qiita.py --months 2024-12
    ./scripts/fetch_qiita.py --months 2024-06,2024-12
    ./scripts/fetch_qiita.py --years 2020,2025          # 1〜12月すべて
    ./scripts/fetch_qiita.py --range 2019-01:2026-09    # 範囲指定
    ./scripts/fetch_qiita.py --months 2024-12 --limit-days 2   # パイロット用
"""

from __future__ import annotations

import argparse
import calendar
import json
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import httpx

API = "https://qiita.com/api/v2/items"
PER_PAGE = 100
MAX_PAGE = 100  # API 上限。page*per_page = 10,000 が1クエリの天井
ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"


def load_token() -> str | None:
    """.env から QIITA_API_TOKEN を読む。無認証でも動くが 60req/h に落ちる。"""
    token = os.environ.get("QIITA_API_TOKEN")
    if token:
        return token
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("QIITA_API_TOKEN="):
                return line.split("=", 1)[1].strip().strip("\"'")
    return None


def month_days(year: int, month: int) -> list[date]:
    last = calendar.monthrange(year, month)[1]
    return [date(year, month, d) for d in range(1, last + 1)]


def parse_targets(args: argparse.Namespace) -> list[tuple[int, int]]:
    """--months / --years / --range を (year, month) のリストに正規化する。"""
    out: list[tuple[int, int]] = []
    if args.months:
        for tok in args.months.split(","):
            y, m = tok.strip().split("-")
            out.append((int(y), int(m)))
    if args.years:
        for tok in args.years.split(","):
            y = int(tok.strip())
            out.extend((y, m) for m in range(1, 13))
    if args.range:
        start, end = args.range.split(":")
        sy, sm = (int(x) for x in start.split("-"))
        ey, em = (int(x) for x in end.split("-"))
        y, m = sy, sm
        while (y, m) <= (ey, em):
            out.append((y, m))
            m += 1
            if m > 12:
                y, m = y + 1, 1
    # 重複除去しつつ順序を保つ
    return sorted(set(out))


def fetch_day(
    client: httpx.Client, day: date, log
) -> tuple[list[dict], int, bool]:
    """1日分を全ページ取得する。

    戻り値は (記事リスト, APIが申告した総件数, 完走したか)。
    完走フラグが False の日は取りこぼしがあるので、再実行時に取り直す。
    """
    query = f"created:>={day.isoformat()} created:<={day.isoformat()}"
    items: list[dict] = []
    total = -1
    page = 1
    while page <= MAX_PAGE:
        for attempt in range(5):
            try:
                r = client.get(
                    API,
                    params={"query": query, "page": page, "per_page": PER_PAGE},
                    timeout=60,
                )
            except httpx.HTTPError as e:
                log(f"    ! 通信エラー ({e.__class__.__name__}) 再試行 {attempt + 1}/5")
                time.sleep(2 * (attempt + 1))
                continue

            if r.status_code == 200:
                break
            if r.status_code in (403, 429):
                # レートリミット。Rate-Reset があればそこまで待つ
                reset = r.headers.get("rate-reset")
                wait = 60
                if reset and reset.isdigit():
                    wait = max(5, int(reset) - int(time.time()) + 5)
                log(f"    ! レート制限 {r.status_code}: {wait}s 待機")
                time.sleep(min(wait, 3700))
                continue
            log(f"    ! HTTP {r.status_code}: 再試行 {attempt + 1}/5")
            time.sleep(2 * (attempt + 1))
        else:
            log(f"    !! {day} page={page} を5回失敗。この日は未完了として記録")
            return items, total, False

        if total < 0:
            total = int(r.headers.get("total-count", -1))
        batch = r.json()
        if not batch:
            break
        items.extend(batch)
        if len(batch) < PER_PAGE:
            break
        page += 1

    # page が MAX_PAGE を超えて打ち切られた場合も取りこぼし扱いにする
    complete = page <= MAX_PAGE and (total < 0 or len(items) >= total)
    return items, total, complete


# 本文分析に不要な巨大フィールドを落として保存サイズを抑える。
# body(Markdown 原文)は分析の主対象なので必ず残す。
KEEP = (
    "id", "title", "body", "created_at", "updated_at", "likes_count",
    "stocks_count", "comments_count", "private", "coediting", "slide", "url",
)


def manifest_path(day: date) -> Path:
    return RAW / f"qiita_{day.isoformat()}.manifest.json"


def write_manifest(day: date, fetched: int, total: int, complete: bool) -> None:
    """その日の取得結果を記録する。

    ファイルの存在だけでは「中断途中」と「完走」を区別できないので、
    完走したかどうかをここに明示的に残す。status_qiita.py はこれを読む。
    """
    manifest_path(day).write_text(
        json.dumps(
            {
                "date": day.isoformat(),
                "fetched": fetched,
                "api_total_count": total,
                "complete": complete,
                "truncated_at_10k": total >= 10000,
                "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def read_manifest(day: date) -> dict | None:
    p = manifest_path(day)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def slim(item: dict) -> dict:
    out = {k: item.get(k) for k in KEEP}
    user = item.get("user") or {}
    # 著者単位のブートストラップと「常連/非常連」判定に使う
    out["user_id"] = user.get("id")
    out["user_followees_count"] = user.get("followees_count")
    out["user_followers_count"] = user.get("followers_count")
    out["user_items_count"] = user.get("items_count")
    out["tags"] = [t.get("name") for t in (item.get("tags") or [])]
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--months", help="例: 2024-06,2024-12")
    p.add_argument("--years", help="例: 2020,2025 (1〜12月すべて)")
    p.add_argument("--range", help="例: 2019-01:2026-09")
    p.add_argument("--limit-days", type=int, help="各月の先頭N日だけ取る(パイロット用)")
    p.add_argument("--force", action="store_true", help="取得済みでも再取得")
    p.add_argument("--sleep", type=float, default=0.2, help="リクエスト間の待機秒")
    args = p.parse_args()

    targets = parse_targets(args)
    if not targets:
        p.error("--months / --years / --range のいずれかを指定してください")

    token = load_token()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    RAW.mkdir(parents=True, exist_ok=True)

    def log(msg: str) -> None:
        print(msg, flush=True)

    log(f"認証: {'あり (1000 req/h)' if token else 'なし (60 req/h)'}")
    log(f"対象: {len(targets)} か月")

    grand_total = 0
    warnings: list[str] = []

    with httpx.Client(headers=headers) as client:
        for (year, month) in targets:
            days = month_days(year, month)
            if args.limit_days:
                days = days[: args.limit_days]
            log(f"\n=== {year}-{month:02d} ({len(days)}日) ===")
            month_count = 0
            for day in days:
                out = RAW / f"qiita_{day.isoformat()}.jsonl"
                mf = read_manifest(day)
                # 完走マニフェストがある日だけスキップする。
                # 中断した日はマニフェストが complete=false なので自動で取り直す。
                if mf and mf.get("complete") and out.exists() and not args.force:
                    n = mf.get("fetched", 0)
                    log(f"  {day} スキップ (取得済み {n}件)")
                    month_count += n
                    continue
                if mf and not mf.get("complete"):
                    log(f"  {day} 前回未完了のため再取得")

                items, total, complete = fetch_day(client, day, log)
                if total >= 10000:
                    w = f"{day}: total-count={total} が 10,000 以上。取りこぼしの可能性"
                    warnings.append(w)
                    log(f"  !! {w}")

                tmp = out.with_suffix(".jsonl.tmp")
                with tmp.open("w", encoding="utf-8") as f:
                    for it in items:
                        f.write(json.dumps(slim(it), ensure_ascii=False) + "\n")
                tmp.replace(out)  # 中断時に壊れたファイルを残さない

                got = len(items)
                # 完了マニフェスト。これが無い日は「未完了」として再取得対象になる。
                # ファイルの存在だけでは中断途中と完走を区別できないため必須。
                write_manifest(day, got, total, complete)

                month_count += got
                flag = "" if total < 0 or got >= total else f" (API申告 {total})"
                if not complete:
                    flag += " [未完了]"
                log(f"  {day} {got:5d}件{flag}")
                time.sleep(args.sleep)

            log(f"  --- {year}-{month:02d} 計 {month_count}件")
            grand_total += month_count

    log(f"\n完了: 合計 {grand_total} 件")
    if warnings:
        log(f"\n警告 {len(warnings)}件:")
        for w in warnings:
            log(f"  - {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
