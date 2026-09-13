#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""取得の進捗を一覧する。どの月が完了していて、どこに穴があるかを出す。

fetch_qiita.py が日ごとに書く manifest を集計する。manifest が無い日・
complete=false の日を「未取得」として報告するので、中断からの再開時に
何を流し直せばいいかがそのまま分かる。

使い方:
    ./scripts/status_qiita.py                      # 取得済みの全月
    ./scripts/status_qiita.py --range 2019-01:2026-09   # 範囲内の穴も出す
    ./scripts/status_qiita.py --missing            # 未完了の月だけ
    ./scripts/status_qiita.py --resume-cmd         # 再開コマンドを出力
"""

from __future__ import annotations

import argparse
import calendar
import json
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"


def iter_months(start: str, end: str):
    sy, sm = (int(x) for x in start.split("-"))
    ey, em = (int(x) for x in end.split("-"))
    y, m = sy, sm
    while (y, m) <= (ey, em):
        yield y, m
        m += 1
        if m > 12:
            y, m = y + 1, 1


def load_all() -> dict[date, dict]:
    out: dict[date, dict] = {}
    for p in sorted(RAW.glob("qiita_*.manifest.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            out[date.fromisoformat(d["date"])] = d
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--range", help="例: 2019-01:2026-09 (未着手の月も穴として出す)")
    ap.add_argument("--missing", action="store_true", help="未完了の月だけ表示")
    ap.add_argument("--resume-cmd", action="store_true", help="再開用コマンドを出力")
    args = ap.parse_args()

    mf = load_all()
    if not mf and not args.range:
        print("取得データがありません。まず fetch_qiita.py を実行してください。")
        return 0

    by_month: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for d, m in mf.items():
        by_month[(d.year, d.month)].append(m)

    if args.range:
        months = list(iter_months(*args.range.split(":")))
    else:
        months = sorted(by_month)

    print(f"{'月':<9} {'状態':<10} {'日数':>7} {'記事数':>9}  備考")
    print("-" * 62)

    incomplete: list[tuple[int, int]] = []
    grand = 0
    for (y, m) in months:
        ndays = calendar.monthrange(y, m)[1]
        got = by_month.get((y, m), [])
        done = [x for x in got if x.get("complete")]
        arts = sum(x.get("fetched", 0) for x in got)
        grand += arts

        notes = []
        if any(x.get("truncated_at_10k") for x in got):
            notes.append("10k到達日あり")
        partial = [x for x in got if not x.get("complete")]
        if partial:
            notes.append(f"未完了{len(partial)}日")

        if len(done) == ndays:
            state = "完了"
        elif not got:
            state = "未着手"
            incomplete.append((y, m))
        else:
            state = "部分"
            incomplete.append((y, m))
            missing_days = ndays - len(done)
            notes.append(f"残{missing_days}日")

        if args.missing and state == "完了":
            continue
        print(f"{y}-{m:02d}   {state:<10} {len(done):>3}/{ndays:<3} {arts:>9,}  {' '.join(notes)}")

    print("-" * 62)
    print(f"合計 {grand:,} 件 / 完了 {len(months) - len(incomplete)}か月 / 未完了 {len(incomplete)}か月")

    if incomplete and args.resume_cmd:
        spec = ",".join(f"{y}-{m:02d}" for y, m in incomplete)
        print(f"\n# 再開コマンド\n./scripts/fetch_qiita.py --months {spec}")
    elif incomplete:
        print("\n--resume-cmd を付けると再開コマンドを出します")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
