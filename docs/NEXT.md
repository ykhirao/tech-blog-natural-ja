# 次にやること（引き継ぎ用）

このファイルを読めば作業を再開できる。
全体像は [../README.md](../README.md) と [../src/CAPABILITIES.md](../src/CAPABILITIES.md)。

最終更新: 2026-09-15

---

## 片付いたこと

| 項目 | 結果 |
|------|------|
| 全期間の取得 | 完了。2011-01〜2026-08、122万件・9.8GB |
| 全期間の月次分析 | 完了。182か月・747,948本([full-timeline.md](full-timeline.md)) |
| 12月の13年分析 | 完了([december-13years.md](december-13years.md))。**前の結論を訂正** |
| 往復翻訳 | 1,744件([roundtrip-1332.md](roundtrip-1332.md)) |
| 辞書との突き合わせ | 完了([survival-vs-dictionary.md](survival-vs-dictionary.md))。役割が重ならない |
| 記事の執筆 | 1,300行、自前 lint 0件 |
| 公開の準備 | 完了。README/LICENSE、履歴から記事本文を除去、`check_repo.py` |

---

## いま手をつけられること

### 1. AI語彙辞書の外部検証（実施中）

p1ass さんの [preset-ai-words-ja](https://github.com/p1ass/textlint-rule-preset-ai-words-ja)
は観察から作られた辞書。こちらには **AI が存在しなかった時代の日本語**があるので、
辞書の語が本当に AI 以後に増えたのかを後から確かめられる。

```bash
./scripts/verify_ai_words.py --years 2015,2017,2019,2020,2021,2022,2023,2024,2025,2026
```

対照群(辞書に無い一般語)を同時に測る。辞書語が全部増えたとき
「正規化が効いていないだけ」を疑う必要があるため。

### 2. 記事を Qiita に投稿する

`article/draft.md` は投稿可能な状態。

- 自前 textlint: 0件
- preset-ai-words-ja: 102件(「実測」「入口」など。**辞書の検証結果しだいで対応を決める**)

### 3. src/ を npm パッケージとして公開する

textlint ルールは単体で動く。`package.json` の `name` を
`textlint-rule-qiita-tech-style` にして publish すれば使える。

未了: パッケージ用の README、テスト、CI。

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
