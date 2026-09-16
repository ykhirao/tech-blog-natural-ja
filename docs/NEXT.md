# 次にやること（引き継ぎ用）

このファイルを読めば作業を再開できる。
全体像は [../README.md](../README.md) と [../src/CAPABILITIES.md](../src/CAPABILITIES.md)。

最終更新: 2026-09-15

---

## 片付いたこと

| 項目 | 結果 |
|------|------|
| 全期間の取得 | 2011-01〜2026-09、122万件・9.8GB |
| 全期間の月次分析 | 189か月・811,379本([full-timeline.md](full-timeline.md)) |
| 12月の13年分析 | [december-13years.md](december-13years.md)。**前の結論を訂正** |
| 往復翻訳 | 1,744件([roundtrip-1332.md](roundtrip-1332.md)) |
| AI語彙辞書の外部検証 | [verify-ai-words.md](verify-ai-words.md)。45語すべて増加、対照群は減少 |
| 2026年の急変 | [confounds-2026.md](confounds-2026.md)。対抗仮説を5つ潰した |
| 参照分布の妥当性 | [profile-2020-still-valid.md](profile-2020-still-valid.md)。2020年基準のまま使える |
| 「使う人の割合」 | [zero-users.md](zero-users.md)。中央値と同じ2021年で向きが変わる |
| 記事の執筆 | 1,590行、自前 lint 0件、数字の照合 0件 |
| 公開の準備 | README/LICENSE、履歴から記事本文を除去、点検スクリプト2本 |

---

## いま手をつけられること

### 1. 記事を Qiita に投稿する

`article/draft.md` は投稿できる状態。

- 自前 textlint: 0件
- `check_article.py`: 0件(数字が実データと合っている)
- preset-ai-words-ja: 89件。ただし大半は**言及**で直せない
  (「正本は2020年に0件」と書くには「正本」と書くしかない)

### 2. src/ を npm パッケージとして公開する

textlint ルールは単体で動く。`package.json` の `name` を
`textlint-rule-qiita-tech-style` にして publish すれば使える。

未了: パッケージ用の README、テスト、CI。

### 3. 2026年前半に何が起きたのかを調べる

**いちばん大きな穴。** 2022年の変化より大きいのに、原因の見当がついていない。

潰した説明(どれも成り立たなかった):

| 仮説 | 結果 |
|------|------|
| AIを扱う記事が増えただけ | 除いても95%残る |
| 多作な人の書き方が混ざった | 著者1人1本でも86%残る |
| 新しく来た人が違う書き方 | 新規著者率は20〜25%で動いていない |
| 人気記事に引きずられた | いいね層別でも65〜104%残る |
| たくさん書く人が引っ張った | 10本以上を除いても差は同じ |
| 特定の分野から始まった | 全7分野が同じ方向に動く(`by_domain.py`) |
| 長い記事から変わった | 4つの長さ層すべてが同じ方向に動く |
| 業務時間内の投稿から変わった | 4つの時間帯すべてが同じ方向に動く |
| 日報型の記事が引っ張った | 除いても差は -0.051(全体は -0.052) |

**9つ潰したが、原因は分からないまま。**

2026年9月14日まで見ても、体言止め(0.048→0.044)と読点(0.879→0.908)は
まだ動いている。頭打ちの兆しはない。

---

## 分析したら面白そうなこと

手元にあるもので測れる順に並べる。上ほど確実。

### A. すぐ測れる(データも道具もある)

> 測り終わったもの: 見出し([heading-trend.md](heading-trend.md))、
> コードブロック([code-trend.md](code-trend.md))、
> 箇条書きとリンク([list-trend.md](list-trend.md))、
> 文末表現([sentence-endings.md](sentence-endings.md))、
> 引用・段落・画像([structure-trend.md](structure-trend.md))。

**引用の中身。** 引用を使う記事が2倍になった
([structure-trend.md](structure-trend.md))が、何を引用しているかは見ていない。
エラーメッセージか、他の記事か、AI の出力か。

**外部画像がU字で戻った理由。** 2013年15.4% → 2024年1.9% → 2026年14.8%。
GitHub と Zenn が上位に来るが、なぜ Qiita に直接上げなくなったのかは分からない。

**2022年の変化も同じ形か。** 2026年では文章を本人が変え、装飾は人が
入れ替わっていた([within-author.md](within-author.md))。
2021-08 → 2023-08 で同じ測り方をすれば、2つの変化が同じ性質かが分かる。

**装飾が「書き始める時点の型」で決まるのか。** 本人内で動かない理由の
説明として挙げたが、検証していない。新規著者の初投稿と2本目以降を
比べれば確かめられるかもしれない。

**画像だけ逆側にある理由。** 画像を使う記事は太字が少なく体言止めが多い。
「見せる」手段と「囲って目立たせる」手段の違いに見えるが、検証していない。

**引用の中身。** 引用を使う記事が2倍になった
([structure-trend.md](structure-trend.md))が、何を引用しているかは見ていない。
日本語ブロックと同じで、引用も「枠で囲う」手段のひとつかもしれない。

### B. 交絡の補正が要る

**ストック・コメント数。** `stocks_count` と `comments_count` は
未使用のまま。ただし**いいねと同じく経過時間の交絡**を受ける
(2020年はストック平均8.01、2026年は0.95)。
公開から同じ日数で切る仕組みが要る。

**フォロワー数と文体。** `user_followers_count` がある。
影響力のある書き手ほど変化が遅い、といった話が測れるかもしれない。
ただしフォロワー数は取得時点の値で、記事を書いた時点の値ではない。

### C. 外部データが要る

**Zenn との比較。** 同じ指標で測れば「Qiita 固有か」が分かる。
利用規約の確認から始める必要がある。

**AI モデルの公開日との突き合わせ。** 2026年前半の急変が、
特定のモデルの公開と重なるかを見る。ただし**後付けで合わせやすい**ので、
先に「どのモデルのどの日付を見るか」を決めてから測らないと意味がない。

### D. やらないと決めたもの

**記事単位の AI 判定。** 誤検出が実在の書き手を不当に貶めるため
([../AGENTS.md](../AGENTS.md))。指標値と参照分布からの距離までは出す。

**いいねを使った年またぎの比較。** 経過時間を補正する仕組みがない
([confounds-2026.md](confounds-2026.md))。

### 4. 他プラットフォームとの比較

Zenn には API がある。同じ指標で測れば「Qiita 固有か」が分かる。
ただし利用規約の確認から始める必要がある。

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
