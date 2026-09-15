#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""記事に書いた数字が、いまのデータと合っているかを検算する。

記事は1,400行を超えていて、データを測り直すたびに数字がずれる。
目視で追うと必ず見落とすので、機械で照合する。

照合するもの:

  規模       全体の本数・月数・年数
  月次の値   「2026-08 の体言止めは0.048」のような記述
  年次の値   年ごとの中央値を書いた表
  内部矛盾   同じ量を別の場所で違う値で書いていないか

数字の書き方は一定ではない(747,948本 / 74.7万件 / 74万記事)ので、
拾えるのは決まった形だけ。**これを通しても保証にはならない。**

使い方:
    ./scripts/check_article.py
    ./scripts/check_article.py --file article/draft.md
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROC = ROOT / "data" / "processed"
RAW = ROOT / "data" / "raw"

# 記事で使う指標名 → metrics のフィールド
LABELS = {
    "体言止め": "nominal_ending_ratio",
    "読点/文": "ten_per_sentence",
    "文長のばらつき": "burstiness_mora",
    "漢字率": "kanji_ratio",
    "地の文字数": "chars_body",
    "MTLD": "mtld",
}


# 列名に期間の限定が入っていたら、年や月の全体と比べてはいけない。
# 「体言止め(1-25)」は12月1〜25日だけの値なので、年全体とは別物。
SCOPED_RE = re.compile(r"\(\s*(?:\d+\s*-\s*\d+|\d+月|[^)]*日)\s*\)")

# 「体言止め差」のように差分を載せた列。値そのものではないので照合しない。
# 「〜の変化」「〜比」も同じ理由で外す。
DERIVED_RE = re.compile(r"(?:差|比|変化|倍|残存|%|\(件\)|件数)\s*\**\s*$")


def load_months() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for p in sorted(PROC.glob("metrics_????-??.jsonl")):
        out[p.stem[8:]] = [json.loads(l) for l in p.open(encoding="utf-8") if l.strip()]
    return out


def med(rows: list[dict], field: str) -> float | None:
    v = [r[field] for r in rows if isinstance(r.get(field), (int, float))]
    return statistics.median(v) if v else None


def fetched_total() -> int | None:
    """API から取得した生データの件数。manifest の合計。

    分析対象(除外基準を通ったもの)とは別の数。記事では
    「122万件取得して81万本を分析」のように両方を書くので、
    どちらと照合してもよいことにする。
    """
    n = 0
    found = False
    for f in RAW.glob("qiita_*.manifest.json"):
        try:
            n += json.loads(f.read_text(encoding="utf-8")).get("fetched", 0)
            found = True
        except Exception:  # noqa: BLE001 — 壊れた manifest 1つで止めない
            continue
    return n if found else None


def check_scale(text: str, data: dict[str, list[dict]]) -> list[str]:
    """全体の規模を書いた箇所が、実データと合うか。"""
    problems = []
    big = {m: rs for m, rs in data.items() if len(rs) >= 200}
    total = sum(len(rs) for rs in data.values())
    n_months = len(data)

    # 「189か月」のような記述
    for m in re.finditer(r"(\d{2,3})か月", text):
        n = int(m.group(1))
        # 月数として妥当な範囲のものだけ見る(「20か月で17倍」などは別の話)
        if 100 <= n <= 250 and n != n_months:
            line = text[: m.start()].count("\n") + 1
            problems.append(f"{line}行目: 「{n}か月」だが実データは {n_months}か月")

    # 「811,379本」のような記述
    for m in re.finditer(r"([\d,]{5,})本", text):
        n = int(m.group(1).replace(",", ""))
        if n > 500_000 and n != total:
            line = text[: m.start()].count("\n") + 1
            problems.append(f"{line}行目: 「{n:,}本」だが実データは {total:,}本")

    # 「74万記事」のような概数。5%以上ずれていたら指摘する。
    # 10%にしていたら、811,379本を「74万記事」と書いた誤りが
    # 8.8%で通り抜けた。丸めの誤差は5%にも達しない。
    fetched = fetched_total()
    for m in re.finditer(r"(\d+(?:\.\d+)?)万(?:記事|件|本)", text):
        n = float(m.group(1)) * 10_000
        if n <= 100_000:
            continue
        # 分析対象と取得件数、どちらかに合っていればよい
        ok = [t for t in (total, fetched) if t and abs(n - t) / t <= 0.05]
        if not ok:
            line = text[: m.start()].count("\n") + 1
            problems.append(
                f"{line}行目: 「{m.group(0)}」は分析 {total:,}本 / "
                f"取得 {fetched:,}件 のどちらとも5%以上ずれる")
    return problems


def check_monthly(text: str, data: dict[str, list[dict]]) -> list[str]:
    """表の中の「| 2026-08 | 0.048 | ...」のような行を照合する。

    行頭が年月の表だけを対象にする。列の意味はヘッダ行から取る。
    """
    problems = []
    lines = text.splitlines()
    header: list[str] = []
    for i, line in enumerate(lines, 1):
        if not line.startswith("|"):
            header = []
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if not cells:
            continue
        # ヘッダ行を覚える
        if any(lbl in c for c in cells for lbl in LABELS):
            header = cells
            continue
        m = re.fullmatch(r"\*{0,2}(\d{4}-\d{2})\*{0,2}", cells[0])
        if not m or not header:
            continue
        month = m.group(1)
        rows = data.get(month)
        if not rows:
            continue
        for j, c in enumerate(cells[1:], 1):
            if j >= len(header):
                break
            if SCOPED_RE.search(header[j]) or DERIVED_RE.search(header[j]):
                continue  # 期間の限定つき、または差分・比率の列
            field = next((f for lbl, f in LABELS.items() if lbl in header[j]), None)
            if not field:
                continue
            num = re.fullmatch(r"\*{0,2}(-?[\d,]+(?:\.\d+)?)\*{0,2}", c)
            if not num:
                continue
            want = med(rows, field)
            if want is None:
                continue
            got = float(num.group(1).replace(",", ""))
            # 書いてある桁数に合わせて丸めてから比べる
            dec = len(num.group(1).split(".")[1]) if "." in num.group(1) else 0
            if abs(round(want, dec) - got) > 10 ** (-dec) / 2 + 1e-9:
                problems.append(
                    f"{i}行目: {month} の{header[j]} を {got} と書いているが "
                    f"実測は {round(want, dec)}")
    return problems


def check_yearly(text: str, data: dict[str, list[dict]]) -> list[str]:
    """行頭が年(4桁)の表を照合する。200件以上の月だけを年にまとめる。"""
    problems = []
    by_year: dict[str, list[dict]] = defaultdict(list)
    for m, rows in data.items():
        if len(rows) >= 200:
            by_year[m[:4]].extend(rows)

    lines = text.splitlines()
    header: list[str] = []
    for i, line in enumerate(lines, 1):
        if not line.startswith("|"):
            header = []
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if any(lbl in c for c in cells for lbl in LABELS):
            header = cells
            continue
        m = re.fullmatch(r"\*{0,2}(\d{4})(?:年)?\*{0,2}", cells[0] if cells else "")
        if not m or not header:
            continue
        year = m.group(1)
        rows = by_year.get(year)
        if not rows:
            continue
        for j, c in enumerate(cells[1:], 1):
            if j >= len(header):
                break
            if SCOPED_RE.search(header[j]) or DERIVED_RE.search(header[j]):
                continue  # 期間の限定つき、または差分・比率の列
            field = next((f for lbl, f in LABELS.items() if lbl in header[j]), None)
            if not field:
                continue
            num = re.fullmatch(r"\*{0,2}(-?[\d,]+(?:\.\d+)?)\*{0,2}", c)
            if not num:
                continue
            want = med(rows, field)
            if want is None:
                continue
            got = float(num.group(1).replace(",", ""))
            dec = len(num.group(1).split(".")[1]) if "." in num.group(1) else 0
            if abs(round(want, dec) - got) > 10 ** (-dec) / 2 + 1e-9:
                problems.append(
                    f"{i}行目: {year}年の{header[j]} を {got} と書いているが "
                    f"実測は {round(want, dec)}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--file", action="append", default=[],
                    help="対象ファイル。複数指定できる(既定: article/draft.md)")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    targets = args.file or ["article/draft.md"]
    # データの読み込みが重い(189か月)ので、1回だけ読んで全ファイルに使う
    data = load_months()
    if not data:
        print("data/processed にデータがありません", file=sys.stderr)
        return 1

    grand = 0
    for rel in targets:
        path = ROOT / rel
        if not path.exists():
            print(f"{path} がありません", file=sys.stderr)
            return 1
        text = path.read_text(encoding="utf-8")
        checks = [
            ("規模の記述", check_scale(text, data)),
            ("月次の値", check_monthly(text, data)),
            ("年次の値", check_yearly(text, data)),
        ]
        total = 0
        for name, problems in checks:
            if problems:
                total += len(problems)
                print(f"\n## {rel} — {name} — {len(problems)}件")
                for p in problems:
                    print(f"  {p}")
            elif args.verbose:
                print(f"\n## {rel} — {name} — 問題なし")
        grand += total
        if args.verbose or total:
            print(f"\n{rel}: {len(text.splitlines())}行 / 指摘 {total}件")

    if grand == 0:
        print(f"{len(targets)}ファイル / 指摘 0件")
        print("(拾えるのは決まった書き方の数字だけ。これで保証にはならない)")
    return 1 if grand else 0


if __name__ == "__main__":
    raise SystemExit(main())
