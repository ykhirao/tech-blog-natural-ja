---
name: qiita-style
description: Measure a Japanese tech article against a pre-AI Qiita reference distribution (6,952 articles, 10 metrics) and revise it toward those measured values. Use when the user wants a draft checked or de-AI-ified, asks "AIっぽい？" about Japanese prose, wants 体言止め/読点/太字/漢字率 measured, or runs textlint/prh on a tech article. Never labels who or what wrote a text. 日本語技術記事の文体を実測の参照分布に照らして測り、直す。AI判定はしない。
---

# qiita-style

日本語の技術記事を、**生成AI以前(2020年8月)の Qiita 記事 6,952本から測った
参照分布**に照らして見る。閾値は通説ではなく実測値。

リポジトリ: `/Users/ymini/orca/projects/tech-blog-natural-ja`（以下 `$REPO`）

## 絶対にやらないこと

**「これはAIが書いた」と判定しない。** 出していいのは指標値と参照分布上の
位置まで。ラベル付けはしない。

- 非ネイティブ話者の誤検出率が高い(Liang et al., Patterns 2023 で英語61%)
- Qiita には非ネイティブ日本語話者も書いている。誤検出は実在の書き手を不当に貶める
- 「AIしか使わない語」を81万記事で探したが**存在しなかった**。最有力の「自律」でも
  非AI記事の1.2%が使い、AI以前の2020年にも13本が使っていた

ユーザーに「AIが書いたか判定して」と言われたら、**判定はできないと答えて**
指標と分布上の位置を出す。そのうえで判断はユーザーに残す。

## 1. 測る

```bash
$REPO/scripts/style_distance.py 記事.md
$REPO/scripts/style_distance.py 記事.md --json
$REPO/scripts/style_distance.py drafts/*.md --rank   # 離れている順
```

10指標のパーセンタイルと、参照分布からの平均的なズレが出る。
`●` が現在位置、`|` が中央値。

**読み方**: p50 付近なら参照分布の真ん中。p95 や p5 は端。
ズレの数値は0に近いほど参照分布に近い。

## 2. 直す

プロンプトを読んで適用する: `$REPO/src/prompts/ai-to-qiita.md`

目標値（すべて AI以前の実測中央値）:

| 指標 | 目標 | 2026年の実測 |
|---|---|---|
| 文長のメリハリ | -0.234 | -0.281 |
| 漢字割合 | 17.4% | 23.4% |
| 体言止め率 | 15.5% | 8.3% |
| 読点/文 | 0.52 | 0.90 |
| 太字/千字 | 0（半数が未使用） | 3.17 |

**要点は「短くする」ではなく「落差を作る」。** 検証の1回目で全部の文を
短く切ったら、平均文長が p22 → p10 と悪化した。長い文を混ぜ直して
2回目で 0.556 → 0.398(28%改善)になった
(`$REPO/docs/prompt-evaluation.md`)。検証は1本だけなので統計的な主張はしない。

直したら **1 で測り直して、ズレが縮んだか確かめる**。縮んでいなければ直せていない。

## 3. 機械的に指摘する

```bash
cd $REPO && npx textlint --rulesdir ./src/textlint 記事.md
```

`--rulesdir` を付けないとルールが読まれず**無言で素通りする**ので必ず付ける。

表記の自動修正は prh: `$REPO/src/prh/qiita-tech-style.yml`（`textlint --fix` 対応）

## 測るときに踏みやすい罠

このリポジトリで実際にやらかしたもの。

- **記事出現率で見ると長さの効果を拾う。** 「解像度」は記事出現率だと
  3.7倍に見えるが、千字あたりで正規化すると11年横ばい
- **12月を跨いで月を比べない。** 体言止めは12月だけ 2.5SD ずれて1月に戻る。
  アドベントカレンダーで書き手の層が変わるため。季節性があるのは12月だけ
- **週次の外れ値はまず著者の集中度を見る。** 1人が44本投稿していただけ、
  という例があった
- **プール集計(合計÷合計)は長い記事に引っ張られる。** 記事ごとに出してから平均する

## 語彙リストを足したいと言われたら

**思いついた語を足さない。** 実測で確かめる:

```bash
$REPO/scripts/verify_ai_words.py --dict yomiyasu --md
```

外部の44語リストを検証したら、**30語はどの年も30記事に届かず**、
9語は10,618記事で0件だった(`$REPO/docs/verify-slop-words.md`)。
対照語も1.7倍に動くので、倍率で見ないと偽の信号を拾う。

実測に耐えた語の例: 土台(10倍)・した瞬間(15倍)・正本(新語)
