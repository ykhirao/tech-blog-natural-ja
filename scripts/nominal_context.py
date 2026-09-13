#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["fugashi[unidic-lite]>=1.3"]
# ///
"""体言止めが「どういう文脈で」使われているかを実データから調べる。

「体言止めを使え」という指針だけでは、使いどころが分からず機械的に混ぜる
ことになる。実際にAI以前の技術記事で体言止めがどう使われているかを測り、
使いどころを言語化するための材料を集める。

調べること:
- 体言止めの文はどのくらいの長さか(前後の文と比べて)
- 文末がどんな語で終わるか
- 段落のどの位置に置かれるか(冒頭/中間/末尾)
- 実例そのもの(前後の文を含めて)

使い方:
    ./scripts/nominal_context.py data/raw/qiita_2020-08-*.jsonl --limit 2000
    ./scripts/nominal_context.py data/raw/qiita_2020-08-*.jsonl --examples 30
"""

from __future__ import annotations

import argparse
import json
import random
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from metrics import clean_inline, mora_approx, split_markdown, split_sentences  # noqa: E402

# 体言止めとみなさない文末。名詞で終わっていても修辞ではないもの。
SKIP_TAIL = re.compile(r"[:：\-—ー…]$")

# 修辞としての体言止めではない「断片」を弾くための規則。
#
# 素朴に「名詞で終わる文」を数えると、Markdown の見出し(#まとめ)、
# 箇条書きの項目(・概要)、コードの残骸(float ms = millis();)が大量に混ざる。
# 実測すると抽出結果の23%が8モーラ未満の断片で、上位の文末語は
# 「作成・設定・クリック・インストール」という手順語だった。
# これらは文ではないので、修辞の分析対象から外す。
FRAGMENT = re.compile(
    r"^\s*(?:#{1,6}\s*"          # 見出し記法
    r"|[-*+・]\s*"                # 箇条書き
    r"|\d+[.)]\s*"                # 番号付き
    r"|[①-⑳]\s*"                 # 丸数字
    r"|※\s*"                      # 注記
    r"|>+\s*)"                    # 引用
)
# コード片の特徴。代入・関数呼び出し・セミコロン終端など。
CODE_LIKE = re.compile(r"[=;{}()\[\]<>]|//|/\*|\*/")
MIN_FRAGMENT_MORA = 8  # これ未満は文として短すぎる


def is_nominal(sentence: str, tagger) -> tuple[bool, str]:
    """文が「修辞としての」体言止めか判定し、末尾の語を返す。

    見出し・箇条書き・コード片は除く。それらは名詞で終わるのが当たり前で、
    文章のリズムの話とは関係がない。
    """
    s = sentence.rstrip("。！？!?").strip()
    if not s or SKIP_TAIL.search(s):
        return False, ""
    if FRAGMENT.match(s):
        return False, ""
    if mora_approx(s) < MIN_FRAGMENT_MORA:
        return False, ""
    # 記号が多い行はコードや表の残骸
    if len(CODE_LIKE.findall(s)) >= 2:
        return False, ""
    # 「名前: 任意の名前」のような設定値の羅列、表の行の残骸
    if re.search(r"[:：|｜]", s):
        return False, ""
    # 【】や第N章はタイトル・目次の断片
    if re.search(r"[【】〜]|^第[０-９0-9一二三四五六七八九十]+[章節部]", s):
        return False, ""
    # 助詞で始まる断片(前の行から切れている)
    if re.match(r"^[はがをにでとへやのも、。]", s):
        return False, ""
    # ASCII が半分以上ならコードか英文
    ascii_n = sum(1 for ch in s if ord(ch) < 128 and not ch.isspace())
    if ascii_n > len(s.replace(" ", "")) * 0.5:
        return False, ""

    toks = list(tagger(s))
    if not toks:
        return False, ""
    last = toks[-1]
    if last.feature.pos1 != "名詞":
        return False, ""
    surf = last.surface
    # 数字やアルファベットだけの語は修辞ではない
    if re.fullmatch(r"[\dA-Za-z_.\-]+", surf):
        return False, ""
    return True, surf


def analyze_article(body: str, tagger) -> list[dict]:
    """1記事から体言止めの文脈を抽出する。"""
    parts = split_markdown(body)
    out: list[dict] = []
    for para in parts["paragraphs"]:
        text = clean_inline("\n".join(para))
        sents = split_sentences(text)
        if len(sents) < 2:
            continue
        lens = [mora_approx(s) for s in sents]
        for i, s in enumerate(sents):
            ok, tail = is_nominal(s, tagger)
            if not ok:
                continue
            if i == 0:
                pos = "first"
            elif i == len(sents) - 1:
                pos = "last"
            else:
                pos = "middle"
            out.append({
                "sentence": s,
                "tail": tail,
                "mora": lens[i],
                "prev_mora": lens[i - 1] if i > 0 else None,
                "next_mora": lens[i + 1] if i + 1 < len(sents) else None,
                "prev": sents[i - 1] if i > 0 else None,
                "next": sents[i + 1] if i + 1 < len(sents) else None,
                "position": pos,
                "para_sentences": len(sents),
            })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--limit", type=int, default=1500, help="読む記事数の上限")
    ap.add_argument("--examples", type=int, default=0, help="実例をN件出す")
    ap.add_argument("--out", help="抽出結果を JSONL で保存")
    ap.add_argument("--seed", type=int, default=3)
    args = ap.parse_args()

    import fugashi
    tagger = fugashi.Tagger()
    rng = random.Random(args.seed)

    hits: list[dict] = []
    n_articles = 0
    all_mora: list[int] = []
    n_sent_total = 0

    for fp in args.files:
        if n_articles >= args.limit:
            break
        for line in Path(fp).open(encoding="utf-8"):
            if n_articles >= args.limit:
                break
            item = json.loads(line)
            if item.get("slide") or item.get("private"):
                continue
            body = item.get("body") or ""
            text = clean_inline("\n".join(split_markdown(body)["body_lines"]))
            if len(re.sub(r"\s", "", text)) < 300:
                continue
            n_articles += 1
            for s in split_sentences(text):
                all_mora.append(mora_approx(s))
                n_sent_total += 1
            hits.extend(analyze_article(body, tagger))

    if not hits:
        print("体言止めが見つかりませんでした")
        return 1

    print(f"記事 {n_articles:,}本 / 全文 {n_sent_total:,} / 体言止め {len(hits):,}文"
          f" ({len(hits)/n_sent_total*100:.1f}%)\n")

    nm = [h["mora"] for h in hits]
    print("## 長さ(モーラ近似)")
    print(f"  体言止めの文   平均 {statistics.fmean(nm):.1f} / 中央 {statistics.median(nm):.0f}")
    print(f"  全文           平均 {statistics.fmean(all_mora):.1f} / 中央 {statistics.median(all_mora):.0f}")
    print(f"  → 体言止めは全体平均の {statistics.fmean(nm)/statistics.fmean(all_mora):.2f}倍の長さ")

    pairs = [(h["prev_mora"], h["mora"]) for h in hits if h["prev_mora"]]
    if pairs:
        shorter = sum(1 for p, c in pairs if c < p)
        print(f"\n  直前の文より短い: {shorter/len(pairs)*100:.0f}% ({shorter:,}/{len(pairs):,})")
        print(f"  直前の文  平均 {statistics.fmean([p for p, _ in pairs]):.1f}モーラ")
        print(f"  体言止め  平均 {statistics.fmean([c for _, c in pairs]):.1f}モーラ")

    print("\n## 段落内の位置")
    pos = Counter(h["position"] for h in hits)
    label = {"first": "段落の冒頭", "middle": "段落の中間", "last": "段落の末尾"}
    for k, v in pos.most_common():
        print(f"  {label.get(k, k):<16} {v:>6,} ({v/len(hits)*100:.1f}%)")

    print("\n## 文末に来る語(上位20)")
    for w, c in Counter(h["tail"] for h in hits).most_common(20):
        print(f"  {w:<12} {c:>5,}")

    if args.examples:
        print(f"\n## 実例({args.examples}件)")
        cands = [h for h in hits if h["prev"] and h["mora"] < 25]
        for h in rng.sample(cands, min(args.examples, len(cands))):
            print(f"\n  前: {h['prev'][:70]}")
            print(f"  ★ {h['sentence'][:70]}   ({h['mora']}モーラ, {label.get(h['position'])})")
            if h["next"]:
                print(f"  後: {h['next'][:70]}")

    if args.out:
        with Path(args.out).open("w", encoding="utf-8") as f:
            for h in hits:
                f.write(json.dumps(h, ensure_ascii=False) + "\n")
        print(f"\n保存: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
