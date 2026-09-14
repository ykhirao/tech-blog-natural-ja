# 次にやること（引き継ぎ用）

このファイルを読めば作業を再開できる。
全体像は [README.md](README.md) と [../src/CAPABILITIES.md](../src/CAPABILITIES.md)。

最終更新: 2026-09-15

---

## 前回までに片付いたこと

前の版で挙げていた項目はすべて完了した。

| 項目 | 結果 |
|------|------|
| 記事長で正規化した語彙指標 | 完了。**前の結論が誤りと判明し訂正**([word-trends-500.md](word-trends-500.md)) |
| 往復翻訳5,000件 | 1,332件で傾向が出たので打ち切り([roundtrip-1332.md](roundtrip-1332.md)) |
| グラフの画像化 | SVG 4枚。`scripts/plot_words.py` |
| 「依存」の文脈分類 | 完了([izon-context.md](izon-context.md))。用法の構成比は変わっていなかった |
| 記事への統合 | 5つの発見を追加。1,148行、lint 0件 |

---

## いま手をつけられること

### 1. 全期間データで月次分析（取得完了待ち）

いちばん価値がある。**各年8月しか見ていないのが現在の最大の制約。**

2022年だけ月次で見たとき、年次では見えない構造が出た
([monthly-2022.md](monthly-2022.md))。

- 文長のばらつきは2022年前半から下降(AI公開より早い)
- 体言止め・地の文字数・漢字率は2022年11月から(公開月と一致)

**同じことを16年分やれば、指標ごとに動き出す時期が特定できる。**

取得が終わったら:

```bash
./scripts/build_dataset.py --months 2022-01,2022-02,...   # 年ごとに分ける
./scripts/timeline.py --chart
```

注意: `--all` は形態素解析を全記事(120万件)にかけるので重い。
年ごとに分けて回すこと。

### 2. 「作り」の生き残り率を他の語に広げる

往復翻訳で「作り」が48%(98件)と突出して不安定だった。
英語に安定した対応物がない語といえる。

同じ測り方を広げれば、**日本語側に選択の余地がある語の一覧**が作れる。
いまは8つの概念グループ(40語ほど)しか対象にしていない。

```bash
./scripts/roundtrip_queue.py build --count 3000 --mode article
./scripts/roundtrip_queue.py work &   # 4並列まで(下の注意を参照)
```

### 3. 生き残り率を lint に入れるか決める

[roundtrip-1332.md](roundtrip-1332.md) で「生き残り率が低い語 =
書き手に選択の余地がある語」と分かった。

textlint ルールにするかは未決。
p1ass さんの [preset-ai-words-ja](https://github.com/p1ass/textlint-rule-preset-ai-words-ja)
と役割が重なる可能性があるので、先に突き合わせる。

### 4. 記事の公開準備

`article/draft.md` は1,148行。Qiita 投稿用。

- 自前 textlint: 0件
- preset-ai-words-ja: 21件(大半は「言及」で直せない)

公開するなら、スクリプトとデータをどこまで出すかを決める。
`data/` は7GB になるのでそのままは置けない。
集計済みの JSON(`word_timeline.json` など)だけなら数百KBで済む。

---

## データの取得状況

### 全期間取得（稼働中）

2011-01 から 2026-09 まで。**8割方終わっている。**

| 項目 | 実測 |
|------|------|
| 取得済み | 5,010日分 / **6.3 GB** |
| 1日あたり | 1,312 KB |
| 残り | 741日分 / 約0.9 GB |
| 完了時 | **約7.2 GB** |

当初「3.4GB」と見積もったが**倍以上だった**。1件3KBと想定したのが甘い。
空き容量は101GBあるので問題はない。

中断しても続きから再開する:
```bash
./scripts/fetch_qiita.py --range 2011-01:2026-09
./scripts/status_qiita.py --resume-cmd
```

### 各年8月（完了）

2011〜2026年の16年分がそろっている。
2011年は記事が少なく(年527件)、条件に合う本文が取れない。

---

## 注意点（つまずいたところ）

### pid(ollama-cloud)は4並列まで

実測した結果:

| 並列数 | 結果 |
|--------|------|
| 3 | 成功3 / 429ゼロ |
| **4** | **成功4 / 429ゼロ** |
| 5 | 1成功 / **4つが429** |

`:cloud` モデルはサーバ側の枠に従う。ローカルの ollama とは別物。
20並列にしたら失敗率48%になった。`run_pid()` に429の再試行を入れてある。

### textlint 本体が node_modules から消える

`--no-save` で入れたものが後続の install で剥がれる。
`npx textlint` が "No rules found" を出したらこれを疑う。

```bash
npm install --no-save textlint@15 textlint-rule-preset-ai-words-ja
```

### テスト文が短いとルールが発火しない

`minSentences: 10` が既定で、翻訳調ルールは2回以上で指摘する。
短い例文で「ルールが壊れている」と誤認しないこと。実際2回やった。

### fugashi が SIGSEGV で落ちる

533,563字の記事で発生。対策済み(100,000字で打ち切り + 長い記事は
別プロセスに隔離)だが、`BrokenProcessPool` が出たらこれ。

### UniDic の見出し語は英語付き

「ライブラリー-library」のように格納される。
`plot_words.py` の `resolve()` が前方一致で吸収する。

### data/ は .gitignore 済み

分析結果は docs に書かないと残らない。

---

## よく使うコマンド

```bash
# 取得
./scripts/fetch_qiita.py --months 2017-08
./scripts/status_qiita.py --resume-cmd

# 指標化(形態素解析あり)
./scripts/build_dataset.py --months 2017-08

# 比較(著者単位ブートストラップ)
./scripts/compare.py data/processed/metrics_2020-08.jsonl \
                     data/processed/metrics_2026-08.jsonl

# 長期推移(生データを直接読む。形態素解析なしで速い)
./scripts/long_trend.py --years 2015,2017,2019,2022,2026 --preset conclusion
./scripts/long_trend.py --pattern "SDK:SDK" --pattern "部品:部品"

# 500語の推移
./scripts/word_timeline.py --top 500              # 記事出現率
./scripts/word_timeline.py --top 500 --normalize  # 千字あたり

# グラフ
./scripts/plot_words.py --preset concept

# 往復翻訳
./scripts/roundtrip_queue.py build --count 500 --mode article
./scripts/roundtrip_queue.py work &    # 4並列まで
./scripts/roundtrip_queue.py report

# 記事の検査
npx textlint --rulesdir ./src/textlint --config .textlintrc.json article/draft.md
./scripts/style_distance.py article/draft.md
```

`.env` に `QIITA_API_TOKEN` が要る(認証ありで 1000 req/時)。

---

## 作業の進め方（ユーザの指示）

- **実測してからルール化する。** 思いつきで直さない。
  「〜だけは」「符合する」などの指摘を受けたら、まず2020 vs 2026 で測る
- **増えた = 直すべき ではない。** 「まさに」「最後に」は増えていても
  人間の日常語なのでルールに入れない
- **面白いデータは全部記事に入れる**
- **捏造しない。** 分量を増やすために推測を書かず、検証を増やす
- 止まらず進める。確認は必要なときだけ
