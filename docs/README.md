# docs — 調査と分析の記録

Qiita の技術記事を実測して、日本語技術記事の文体プロファイルを作る調査の記録。

> **作業を再開するときは [NEXT.md](NEXT.md) を最初に読む。**
> 取得状況、次にやること、つまずきどころがまとまっている。

## 読む順番

| ファイル | 内容 |
|---------|------|
| [NEXT.md](NEXT.md) | **引き継ぎ用。次にやること・データの状態・注意点** |
| [qiita-writing-before-after-ai.md](qiita-writing-before-after-ai.md) | 出発点になった逆瀬川氏の記事の読書メモ |
| [2020-08-vs-2026-08.md](2020-08-vs-2026-08.md) | 本体の分析。AI以前と以後の文体比較 |
| [vocabulary-shift.md](vocabulary-shift.md) | 語彙の変化。どの語が増えて減ったか |
| [robustness.md](robustness.md) | **交絡の検証。対抗仮説を3つ潰した記録** |
| [nominal-ending.md](nominal-ending.md) | 体言止めの実際の用法。「短く切る」は誤りだった |
| [prompt-evaluation.md](prompt-evaluation.md) | **変換プロンプトの効果検証。1回目は失敗した** |
| [translationese.md](translationese.md) | 英語直訳の構文は増えたか。「〜できます」は逆に激減 |
| [domain-differences.md](domain-differences.md) | 分野で文体は違うか。**時代差が分野差の2倍** |
| [monthly-baseline.md](monthly-baseline.md) | **AI以前の月次変動。漢字率は6か月で0.001しか動かない** |
| [when-did-it-change.md](when-did-it-change.md) | **変化はいつ始まったか。2021年はまだAI以前と区別がつかない** |
| [monthly-2022.md](monthly-2022.md) | **2022年を月次で見たら年次の見立てが崩れた。指標で時期が違う** |
| [full-timeline.md](full-timeline.md) | **16年189か月の全月分析。漢字率は14年ずっと上昇していた** |
| [word-trends-500.md](word-trends-500.md) | **頻出500語の12年推移。記事長の交絡に注意** |
| [metaphor-vocabulary.md](metaphor-vocabulary.md) | **技術用語が和語・比喩に言い換えられた。「仕組み」36%** |
| [sdk-vocabulary.md](sdk-vocabulary.md) | SDK系の語は11年間減り続けていた |
| [advent-calendar.md](advent-calendar.md) | 12月の分析(2022年のみ)。**december-13years.md で一部訂正** |
| [december-13years.md](december-13years.md) | **12月を13年分。常連と非常連の差は2022年から出た** |
| [roundtrip-translation.md](roundtrip-translation.md) | 往復翻訳の仕組み。並行処理しても壊れない設計 |
| [roundtrip-1332.md](roundtrip-1332.md) | **往復翻訳1,332件の結果。生き残り率で語が2層に分かれる** |
| [izon-context.md](izon-context.md) | 「依存」は何の話で増えたか。用法の構成比は変わっていない |
| [survival-vs-dictionary.md](survival-vs-dictionary.md) | **生き残り率と AI語彙辞書は役割が重ならない。併用が正しい** |
| [verify-ai-words.md](verify-ai-words.md) | **AI語彙辞書を実測で検証。45語すべて増加、対照群は減少。2026年に2度目の変化** |
| [confounds-2026.md](confounds-2026.md) | **2026年の急変に対抗仮説を4つぶつけた。同じ人が半年で書き方を変えている** |
| [profile-2020-still-valid.md](profile-2020-still-valid.md) | **2020年の参照分布はまだ使えるか。分位点はずれたがルールは保っている** |
| [zero-users.md](zero-users.md) | **「1回も使わない人の割合」も2021年で折れた。太字だけ2024年末から動く** |
| [title-trend.md](title-trend.md) | **タイトルは本文より遅れて2024〜2025年に動いた。12年間28〜31字だった** |
| [edit-rate.md](edit-rate.md) | **公開後に直さない記事が2倍に。2017年に底を打ち、生成AIより5年早い** |
| [sentence-endings.md](sentence-endings.md) | **体言止めの行き先は「です」だった。2.2倍に増えている** |
| [heading-trend.md](heading-trend.md) | **見出しの長さは11年間9〜10字で不変。2025年から動き、階層は逆に浅くなった** |
| [code-trend.md](code-trend.md) | **コード行数は半減し、`text` タグが12倍に。コードでないものが枠に入る** |

成果物は [`../src/`](../src/) にある(プロファイル・textlintルール・プロンプト)。

## 結論の要約

2020年8月と2026年8月の Qiita 技術記事を比べると、文体が大きく変わっている。

| 指標 | 2020-08 | 2026-08 | 変化 |
|------|---------|---------|------|
| 地の文字数 | 1,458 | 2,795 | 1.92x |
| 漢字割合 | 18.1% | 23.4% | 1.30x |
| 太字/千字 | 1.33 | 3.17 | 2.39x |
| 箇条書き割合 | 11.3% | 22.1% | 1.96x |
| 「まとめ」見出し | 23.4% | 66.3% | 2.84x |
| **体言止め率** | **19.0%** | **8.3%** | **0.43x** |
| **画像/千字** | **1.951** | **0.844** | **0.43x** |
| burstiness | -0.230 | -0.281 | — |

この変化は以下の3つでは説明できないことを確認した([robustness.md](robustness.md))。

1. **経年変化ではない** — AI以前(2019→2020)の変動は最大±0.09。2020→2026はその10〜35倍。
   月次で見るとさらに明確で、2019年3〜8月の漢字率は 0.172〜0.173(幅0.001)しか
   動かない([monthly-baseline.md](monthly-baseline.md))
2. **話題の変化ではない** — AI言及記事(27%→59%)を全部除いても変化は残る
3. **書き手の入れ替わりではない** — 同一著者128人でも全指標が同じ方向に動く

ただし**原因が生成AIだとは言えない**。対抗仮説を潰しただけで、
AIを積極的に支持する証拠ではない。

## 実測で覆った通説

思い込みで禁止語リストを作ると外れる。

| 通説 | 実測 |
|------|------|
| 体言止めの多用がAIっぽい | 逆。**ゼロなのがAI的**(19.0% → 8.3%) |
| 体言止めは短く切って余韻を出す | 直前より短いのは**36%だけ**。平均はむしろ長い |
| 文が長いのはAIっぽい | 平均文長の伸びはAI以前からの傾向で説明できる |
| 「しましょう」はAIっぽい | 元記事の実測では**減っていた** |
| 「最後に」「まさに」はAI語 | coji氏の実測では人間の日常語(誤検知の63%) |

## 元記事との関係

[逆瀬川氏の分析](https://nyosegawa.com/posts/qiita-writing-before-after-ai/)
(2019-2022 → 2026年8月、5万記事)を、別の基準年・別実装で再現した。
方向と桁はすべて一致している。

本分析で新しく分かったこと:

- **体言止めの半減** — 元記事にない指標。coji氏の実測(人間60%/AI 0%)と同方向
- **「下記」の激減** — 17.7% → 4.2%(0.2倍)。話題と無関係な純粋な文体語
- **画像密度の半減** — 文章は倍増したのに画像は微減
- **MTLD と TTR が逆方向** — 文書長の影響。長さが変わる比較ではMTLDを見る
- **burstiness が既存閾値をまたぐ** — 2020年は -0.230 で閾値-0.24を通り、
  2026年は -0.281 で割り込む。既定閾値は技術記事でも妥当だった

## データの再現手順

```bash
# 取得(日単位・レジューム対応)
./scripts/fetch_qiita.py --months 2020-08,2026-08
./scripts/status_qiita.py --resume-cmd     # 進捗と穴の確認

# 指標の計算とデータセット化
./scripts/build_dataset.py --months 2020-08,2026-08

# 比較(著者単位ブートストラップ)
./scripts/compare.py data/processed/metrics_2020-08.jsonl \
                     data/processed/metrics_2026-08.jsonl

# 語彙
./scripts/vocab.py data/raw/qiita_2020-08-*.jsonl \
                   --vs data/raw/qiita_2026-08-*.jsonl --md

# 外れ値の診断(スクリプト改善用)
./scripts/inspect_outliers.py data/processed/metrics_2026-08.jsonl --dist
```

`.env` に `QIITA_API_TOKEN` が要る(認証ありで 1000 req/h)。
