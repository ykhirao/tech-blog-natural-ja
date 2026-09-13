#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["fugashi[unidic-lite]>=1.3"]
# ///
"""記事1本から文体指標を計算するライブラリ兼CLI。

分析(集計)・textlint 連携・プロンプト生成のいずれからも同じ数値が出るよう、
指標の定義はここ1か所に集約する。

方針:
- 「この記事はAI製か」という判定は出さない。指標値と、参照分布からの距離まで。
  非ネイティブ話者の誤検出率が高いことが先行研究で示されており(Liang et al. 2023)、
  文書単位の白黒判定は誤って実在の書き手を貶める。
- Markdown の地の文だけを対象にする。コードブロック・表・引用は文体分析の
  対象外なので、本文抽出の段階で落とす。

使い方:
    ./scripts/metrics.py 記事.md
    ./scripts/metrics.py --jsonl data/raw/qiita_2024-12-01.jsonl --limit 100
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
from pathlib import Path

# --- Markdown の分解 -------------------------------------------------------

FENCE = re.compile(r"^\s*(```|~~~)")
HEADING = re.compile(r"^\s{0,3}#{1,6}\s")
LIST_ITEM = re.compile(r"^\s*([-*+]|\d+[.)])\s+")
TABLE_ROW = re.compile(r"^\s*\|")
QUOTE = re.compile(r"^\s*>")
BOLD = re.compile(r"\*\*[^*\n]+\*\*|__[^_\n]+__")
INLINE_CODE = re.compile(r"`[^`\n]+`")
LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
HTML_TAG = re.compile(r"<[^>]+>")


def split_markdown(md: str) -> dict:
    """Markdown を行種別に分ける。戻り値の body が地の文。"""
    body: list[str] = []
    headings: list[str] = []
    list_items = 0
    table_rows = 0
    code_lines = 0
    quote_lines = 0
    paragraphs: list[list[str]] = []
    cur: list[str] = []

    in_fence = False
    for raw in md.splitlines():
        if FENCE.match(raw):
            in_fence = not in_fence
            code_lines += 1
            continue
        if in_fence:
            code_lines += 1
            continue
        if HEADING.match(raw):
            headings.append(HEADING.sub("", raw).strip())
            if cur:
                paragraphs.append(cur)
                cur = []
            continue
        if TABLE_ROW.match(raw):
            table_rows += 1
            continue
        if QUOTE.match(raw):
            quote_lines += 1
            continue
        if LIST_ITEM.match(raw):
            list_items += 1
            continue
        if not raw.strip():
            if cur:
                paragraphs.append(cur)
                cur = []
            continue
        body.append(raw)
        cur.append(raw)
    if cur:
        paragraphs.append(cur)

    return {
        "body_lines": body,
        "headings": headings,
        "list_items": list_items,
        "table_rows": table_rows,
        "code_lines": code_lines,
        "quote_lines": quote_lines,
        "paragraphs": paragraphs,
    }


def clean_inline(text: str) -> str:
    """地の文から装飾記法を外して素の日本語にする。"""
    text = IMAGE.sub("", text)
    text = LINK.sub(r"\1", text)
    text = INLINE_CODE.sub("", text)
    text = HTML_TAG.sub("", text)
    text = re.sub(r"\*\*|__|\*|~~", "", text)
    return text


# --- 文分割 ---------------------------------------------------------------

def split_sentences(text: str) -> list[str]:
    """句点と改行で文に切る。読点で終わる行は次行と連結する。

    元記事(逆瀬川氏)の前処理に合わせている。外部ライブラリに頼らないのは、
    ja-sentence-segmenter の normalize が全角記号を半角に潰してしまい、
    表記の分析と競合するため。
    """
    out: list[str] = []
    buf = ""
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        buf = (buf + line) if buf else line
        if buf.endswith(("、", "，")):
            continue  # 次行と連結
        for part in re.split(r"(?<=[。！？!?])", buf):
            part = part.strip()
            if part:
                out.append(part)
        buf = ""
    if buf.strip():
        out.append(buf.strip())
    return [s for s in out if s]


# --- 形態素解析 -----------------------------------------------------------

_tagger = None


def tagger():
    global _tagger
    if _tagger is None:
        import fugashi

        _tagger = fugashi.Tagger()
    return _tagger


def mora_approx(s: str) -> int:
    """モーラ数の近似。拗音(ゃゅょ)は直前と合わせて1拍として数えない。"""
    small = "ゃゅょャュョ"
    return sum(1 for ch in s if not ch.isspace() and ch not in small)


# --- 指標 -----------------------------------------------------------------

def burstiness(lengths: list[int]) -> float | None:
    """文長のばらつき。(sd - mean) / (sd + mean)。負に振れるほど単調。

    coji/natural-japanese と同じ定義。閾値 -0.24 も同スキルの値だが、
    それは汎用ビジネス文書で校正されたもので、技術記事で妥当かは未検証。
    このプロジェクトで Qiita コーパスから測り直すのが目的。
    """
    if len(lengths) < 2:
        return None
    mean = statistics.fmean(lengths)
    sd = statistics.pstdev(lengths)
    if mean + sd == 0:
        return None
    return (sd - mean) / (sd + mean)


def type_token_ratio(tokens: list[str]) -> float | None:
    if not tokens:
        return None
    return len(set(tokens)) / len(tokens)


def mtld(tokens: list[str], threshold: float = 0.72) -> float | None:
    """語彙の多様性。TTR と違い文書長の影響を受けにくい。"""
    if len(tokens) < 50:
        return None

    def one_pass(seq: list[str]) -> float:
        factors = 0.0
        types: set[str] = set()
        count = 0
        for t in seq:
            types.add(t)
            count += 1
            if len(types) / count <= threshold:
                factors += 1
                types, count = set(), 0
        if count:
            ttr = len(types) / count
            factors += (1 - ttr) / (1 - threshold) if threshold < 1 else 0
        return len(seq) / factors if factors else float(len(seq))

    return statistics.fmean([one_pass(tokens), one_pass(tokens[::-1])])


def analyze(md: str) -> dict:
    """記事1本の指標をまとめて返す。"""
    parts = split_markdown(md)
    body_raw = "\n".join(parts["body_lines"])
    body = clean_inline(body_raw)
    sentences = split_sentences(body)

    chars = len(re.sub(r"\s", "", body))
    per_k = (lambda n: round(n / chars * 1000, 3)) if chars else (lambda n: None)

    lens_char = [len(re.sub(r"\s", "", s)) for s in sentences]
    lens_mora = [mora_approx(s) for s in sentences]

    # 構成: 地の文に対する箇条書き・太字の比率
    total_struct = len(parts["body_lines"]) + parts["list_items"]
    bold_n = len(BOLD.findall(body_raw))

    m: dict = {
        "chars_body": chars,
        "n_sentences": len(sentences),
        "n_paragraphs": len(parts["paragraphs"]),
        "n_headings": len(parts["headings"]),
        "n_list_items": parts["list_items"],
        "n_code_lines": parts["code_lines"],
        "n_table_rows": parts["table_rows"],
        "bold_per_1k": per_k(bold_n),
        "list_ratio": round(parts["list_items"] / total_struct, 4) if total_struct else None,
        "mean_sentence_chars": round(statistics.fmean(lens_char), 2) if lens_char else None,
        "sd_sentence_chars": round(statistics.pstdev(lens_char), 2) if len(lens_char) > 1 else None,
        "cv_sentence_chars": None,
        "burstiness_mora": None,
        "mean_mora": round(statistics.fmean(lens_mora), 2) if lens_mora else None,
        "sd_mora": round(statistics.pstdev(lens_mora), 2) if len(lens_mora) > 1 else None,
    }
    if m["mean_sentence_chars"] and m["sd_sentence_chars"] is not None:
        m["cv_sentence_chars"] = round(m["sd_sentence_chars"] / m["mean_sentence_chars"], 4)
    b = burstiness(lens_mora)
    m["burstiness_mora"] = round(b, 4) if b is not None else None

    # 読点・記号
    m["ten_per_sentence"] = round(body.count("、") / len(sentences), 3) if sentences else None
    m["dash_per_1k"] = per_k(body.count("—") + body.count("――"))
    m["kanji_ratio"] = (
        round(len(re.findall(r"[一-鿿]", body)) / chars, 4) if chars else None
    )

    # 文体: です・ます / である、体言止め
    desumasu = sum(1 for s in sentences if re.search(r"(です|ます|ました|ません|でしょう)[。！？]?$", s))
    dearu = sum(1 for s in sentences if re.search(r"(である|だ|った|ない)[。！？]?$", s))
    m["desumasu_ratio"] = round(desumasu / len(sentences), 4) if sentences else None
    m["dearu_ratio"] = round(dearu / len(sentences), 4) if sentences else None

    # 段落構造の均質さ: 段落あたり文数のばらつき
    para_sent = [len(split_sentences(clean_inline("\n".join(p)))) for p in parts["paragraphs"]]
    para_sent = [n for n in para_sent if n > 0]
    if len(para_sent) >= 3:
        pm = statistics.fmean(para_sent)
        m["paragraph_sentences_mean"] = round(pm, 2)
        m["paragraph_sentences_cv"] = round(statistics.pstdev(para_sent) / pm, 4) if pm else None
    else:
        m["paragraph_sentences_mean"] = None
        m["paragraph_sentences_cv"] = None

    # 「まとめ」見出しの有無
    m["has_matome_heading"] = any(
        re.search(r"(まとめ|おわりに|終わりに|最後に|結論)", h) for h in parts["headings"]
    )
    return m


def analyze_with_pos(md: str) -> dict:
    """形態素解析を伴う指標。fugashi が要るので分けてある。"""
    m = analyze(md)
    parts = split_markdown(md)
    body = clean_inline("\n".join(parts["body_lines"]))
    if not body.strip():
        return m
    tg = tagger()
    words = [w for w in tg(body)]
    lemmas = [getattr(w.feature, "lemma", None) or w.surface for w in words]
    pos = [w.feature.pos1 for w in words]

    m["n_tokens"] = len(words)
    m["ttr"] = round(type_token_ratio(lemmas), 4) if lemmas else None
    v = mtld(lemmas)
    m["mtld"] = round(v, 2) if v is not None else None

    # 体言止め: 文末が名詞で終わる比率。AI は極端に少ないと報告されている
    sentences = split_sentences(body)
    nominal = 0
    for s in sentences:
        toks = [w for w in tg(s.rstrip("。！？!?"))]
        if toks and toks[-1].feature.pos1 == "名詞":
            nominal += 1
    m["nominal_ending_ratio"] = round(nominal / len(sentences), 4) if sentences else None

    # 品詞比率。助詞率は日本語のAI文体研究で有効とされる(Zaitsu & Jin 2023)
    if pos:
        for p in ("名詞", "動詞", "助詞", "助動詞", "形容詞", "副詞", "接続詞"):
            m[f"pos_{p}_ratio"] = round(pos.count(p) / len(pos), 4)
    return m


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", nargs="?", help="Markdown ファイル")
    ap.add_argument("--jsonl", help="fetch_qiita.py が出した JSONL")
    ap.add_argument("--limit", type=int, help="JSONL の先頭N件だけ")
    ap.add_argument("--no-pos", action="store_true", help="形態素解析を使わない(高速)")
    args = ap.parse_args()

    fn = analyze if args.no_pos else analyze_with_pos

    if args.jsonl:
        n = 0
        for line in Path(args.jsonl).open(encoding="utf-8"):
            if args.limit and n >= args.limit:
                break
            item = json.loads(line)
            body = item.get("body") or ""
            if not body.strip():
                continue
            rec = {"id": item.get("id"), "user_id": item.get("user_id"),
                   "created_at": item.get("created_at"), **fn(body)}
            print(json.dumps(rec, ensure_ascii=False))
            n += 1
        return 0

    if not args.file:
        ap.error("file か --jsonl が要ります")
    md = Path(args.file).read_text(encoding="utf-8")
    print(json.dumps(fn(md), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
