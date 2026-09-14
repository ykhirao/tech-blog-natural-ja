#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""語の年次推移を SVG の折れ線グラフにする。

外部ライブラリを使わずに SVG を組み立てる。依存を増やさないため。
明るい背景でも暗い背景でも読めるよう、色は中間トーンで揃える。

使い方:
    ./scripts/plot_words.py --words 設計,判断,整理,検証
    ./scripts/plot_words.py --preset concept --out docs/img/concept.svg
    ./scripts/plot_words.py --preset katakana --normalize
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROC = ROOT / "data" / "processed"
IMG = ROOT / "docs" / "img"

# 明暗どちらの背景でも読める中間トーン。隣り合う線が区別できる並びにする。
COLORS = ["#2f7ed8", "#d9534f", "#5cb85c", "#f0ad4e",
          "#9b59b6", "#00a0a0", "#c9518c", "#7f8c8d"]

# 語は UniDic の見出し語で持つ。カタカナ語は「ツール-tool」のように
# 英語が付く形で格納されているので、そのまま書く。
PRESETS = {
    "concept": ["設計", "判断", "整理", "検証", "運用"],
    "metaphor": ["仕組み", "流れ", "構造", "構成"],
    "katakana": ["ツール-tool", "ライブラリー-library",
                 "モジュール-module", "ベース-base"],
    "weak": ["置く", "作る", "動く"],
}


def resolve(name: str, table: dict) -> str | None:
    """語名を実データの見出し語に合わせる。

    UniDic は「ツール-tool」のように英語を付ける。利用側で毎回それを
    書くのは面倒なので、「ツール」と指定されたら前方一致で探す。
    """
    if name in table:
        return name
    for k in table:
        if k.split("-")[0] == name:
            return k
    return None


def esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;").replace('"', "&quot;"))


def build_svg(years: list[str], series: dict[str, list[float]],
              title: str, ylabel: str, ai_year: str = "2022") -> str:
    W, H = 820, 420
    ml, mr, mt, mb = 62, 150, 48, 52   # 右は凡例用に広く取る
    pw, ph = W - ml - mr, H - mt - mb

    vals = [v for s in series.values() for v in s]
    vmax = max(vals) * 1.1 if vals else 1
    vmin = 0

    def x(i: int) -> float:
        return ml + (pw * i / max(1, len(years) - 1))

    def y(v: float) -> float:
        return mt + ph - (ph * (v - vmin) / (vmax - vmin) if vmax > vmin else 0)

    p: list[str] = []
    p.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
             f'width="100%" style="max-width:{W}px;height:auto;font-family:'
             f'system-ui,-apple-system,sans-serif">')
    # 背景は敷かない。読み手のテーマに任せる(currentColor で線と文字を出す)
    p.append(f'<title>{esc(title)}</title>')
    p.append(f'<text x="{ml}" y="26" font-size="15" font-weight="600" '
             f'fill="currentColor">{esc(title)}</text>')

    # 横目盛りとグリッド
    steps = 4
    for k in range(steps + 1):
        v = vmin + (vmax - vmin) * k / steps
        yy = y(v)
        p.append(f'<line x1="{ml}" y1="{yy:.1f}" x2="{ml+pw}" y2="{yy:.1f}" '
                 f'stroke="currentColor" stroke-opacity="0.12"/>')
        p.append(f'<text x="{ml-8}" y="{yy+4:.1f}" font-size="11" '
                 f'text-anchor="end" fill="currentColor" fill-opacity="0.65">'
                 f'{v:.0f}</text>')
    p.append(f'<text x="{ml-46}" y="{mt-14}" font-size="11" '
             f'fill="currentColor" fill-opacity="0.65">{esc(ylabel)}</text>')

    # 年ラベル(詰まるので2年ごと)
    for i, yr in enumerate(years):
        if i % 2 == 0 or i == len(years) - 1:
            p.append(f'<text x="{x(i):.1f}" y="{mt+ph+20}" font-size="11" '
                     f'text-anchor="middle" fill="currentColor" '
                     f'fill-opacity="0.65">{esc(yr)}</text>')

    # ChatGPT 公開の位置に縦線
    if ai_year in years:
        ax = x(years.index(ai_year))
        p.append(f'<line x1="{ax:.1f}" y1="{mt}" x2="{ax:.1f}" y2="{mt+ph}" '
                 f'stroke="currentColor" stroke-opacity="0.35" '
                 f'stroke-dasharray="4 4"/>')
        p.append(f'<text x="{ax+5:.1f}" y="{mt+13}" font-size="10" '
                 f'fill="currentColor" fill-opacity="0.6">ChatGPT公開</text>')

    # 折れ線
    for n, (name, s) in enumerate(series.items()):
        c = COLORS[n % len(COLORS)]
        pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(s))
        p.append(f'<polyline points="{pts}" fill="none" stroke="{c}" '
                 f'stroke-width="2.2" stroke-linejoin="round"/>')
        p.append(f'<circle cx="{x(len(s)-1):.1f}" cy="{y(s[-1]):.1f}" r="3.2" '
                 f'fill="{c}"/>')
        # 凡例(最終値の順に縦に並べる)
        ly = mt + 14 + n * 21
        p.append(f'<line x1="{ml+pw+14}" y1="{ly-4}" x2="{ml+pw+32}" '
                 f'y2="{ly-4}" stroke="{c}" stroke-width="2.2"/>')
        p.append(f'<text x="{ml+pw+38}" y="{ly}" font-size="12" '
                 f'fill="currentColor">{esc(name)} '
                 f'<tspan fill-opacity="0.6">{s[-1]:.1f}</tspan></text>')

    p.append("</svg>")
    return "\n".join(p)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--words", help="カンマ区切りで語を指定")
    ap.add_argument("--preset", choices=list(PRESETS))
    ap.add_argument("--normalize", action="store_true",
                    help="千字あたりのデータを使う")
    ap.add_argument("--out", help="出力先(既定は docs/img/<名前>.svg)")
    ap.add_argument("--title")
    args = ap.parse_args()

    src = PROC / ("word_timeline_norm.json" if args.normalize else "word_timeline.json")
    if not src.exists():
        print(f"{src} がありません。先に word_timeline.py を実行してください")
        return 1
    data = json.loads(src.read_text(encoding="utf-8"))
    years = data["years"]
    table = {w["word"]: w["series"] for w in data["words"]}

    if args.preset:
        want = PRESETS[args.preset]
        name = args.preset
    elif args.words:
        want = [w.strip() for w in args.words.split(",")]
        name = "-".join(want)[:40]
    else:
        ap.error("--words か --preset を指定してください")

    series = {}
    missing = []
    for w in want:
        key = resolve(w, table)
        if key:
            # 凡例には「ツール-tool」ではなく「ツール」と出す
            series[key.split("-")[0]] = table[key]
        else:
            missing.append(w)
    if missing:
        print(f"データにない語: {missing}")
    if not series:
        return 1

    ylabel = "千字あたり" if args.normalize else "記事出現率(%)"
    title = args.title or f"{'、'.join(series)} の推移"
    svg = build_svg(years, series, title, ylabel)

    out = Path(args.out) if args.out else IMG / f"{name}.svg"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(svg, encoding="utf-8")
    print(f"保存: {out} ({len(series)}語 / {len(years)}年)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
