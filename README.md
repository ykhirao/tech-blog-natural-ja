# tech-blog-natural-ja

Qiita の技術記事 **811,379本・189か月分**(2011〜2026年)を実測して作った、
日本語技術記事のための**文体プロファイルと textlint ルール**。

日本語の「AIっぽさ」を測る OSS はすでにある。中でも
[coji/natural-japanese](https://github.com/coji/natural-japanese)(MIT)が
実質の決定版で、文長のばらつき・MTLD の検出を実装済み。
**ただしその閾値は汎用のビジネス文書で校正されていて、技術記事では校正されていない。**

このリポジトリはそこを埋める。技術記事だけのコーパスから閾値を測り直した。

## 3行でわかる結果

- 文のリズムを表す指標が、ChatGPT の公開より **3か月早く**折れていた
- 「AIっぽい」とされる表現の多くは、実測では**減っている**
- 漢字率は AI 以前の2013年から14年間ずっと上がり続けていた
- 2026年に**2度目の変化**が起きている。2年ぶんの変化が7か月で進んだ

詳細は [article/article01.md](article/article01.md)(記事本体)と [docs/](docs/) にある。

## どこを見ればいいか

| 目的 | 行き先 |
|------|--------|
| **道具を使いたい** | [src/README.md](src/README.md) — textlint ルール・プロンプト・参照分布 |
| **何ができるか知りたい** | [src/CAPABILITIES.md](src/CAPABILITIES.md) — できること・できないこと |
| **分析の中身を読みたい** | [docs/README.md](docs/README.md) — 22本の調査記録 |
| **記事として読みたい** | [article/article01.md](article/article01.md) |
| **自分で測り直したい** | [scripts/](scripts/) と下の「再現する」 |
| **開発の作法を知りたい** | [AGENTS.md](AGENTS.md) |

## 使う

### textlint ルール

```bash
npm install
npx textlint --rulesdir ./src/textlint 記事.md
```

同梱の `.textlintrc.json` は3つを併用する。

- `qiita-tech-style` — 自作。参照分布と照らして文体を指摘する
- `preset-ai-words-ja` — [p1ass さんの辞書](https://github.com/p1ass/textlint-rule-preset-ai-words-ja)。AI が使いがちな語
- `prh` — 表記の言い換え辞書

役割が重ならないことは実測で確かめた([survival-vs-dictionary.md](docs/survival-vs-dictionary.md))。

なお `qiita-tech-style` は **10文未満の文書では何も指摘しない**。
統計量が安定しないため。短い文章で沈黙するのは仕様。

### プロンプト

- [src/prompts/qiita-tech-writing.md](src/prompts/qiita-tech-writing.md) — 執筆・推敲用
- [src/prompts/ai-to-qiita.md](src/prompts/ai-to-qiita.md) — AI の文章を直す用

効果は実測してある。1回目は失敗した([prompt-evaluation.md](docs/prompt-evaluation.md))。

## 再現する

Python スクリプトは [uv](https://docs.astral.sh/uv/) の単一ファイルスクリプト形式で、
依存はファイル内に書いてある。`uv` があればそのまま動く。

```bash
export QIITA_API_TOKEN=...      # https://qiita.com/settings/applications
./scripts/fetch_qiita.py --months 2020-08    # 日単位で取得
./scripts/build_dataset.py --months 2020-08  # 除外基準を当てて指標化
./scripts/timeline.py                        # 推移を表で見る
```

取得は日単位で、途中で止めても manifest から再開する。
Qiita API は認証ありで 1,000 req/hr、`page`×`per_page` が1万件で頭打ちになるため、
月単位ではアドベントカレンダー期の12月を取りこぼす。

### データは同梱していない

`data/` は `.gitignore` 済み。取得した記事本文には他の人の著作物が含まれるため、
リポジトリには入れない。

公開しているのは **集計値だけ**([src/data/](src/data/)、428KB)。
本文は1文字も含まない。

## ライセンス

MIT。ただし [src/data/](src/data/) の数値は Qiita の公開記事から計算した統計量であり、
元記事の著作権は各著者にある。

先行実装の [coji/natural-japanese](https://github.com/coji/natural-japanese)(MIT)から
文長のばらつきの定義と閾値 -0.24 を借りた。
