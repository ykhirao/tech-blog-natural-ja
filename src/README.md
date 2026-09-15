# code-natural-ja — 公開成果物

Qiita の記事を実測して作った、**日本語技術記事のための文体プロファイルと道具**。

生成AI以前(2020年8月)と以後(2026年8月)の Qiita 記事 約17,000本を計測し、
閾値を経験的に校正した。すべて MIT ライセンス。

## なぜこれを作ったか

日本語の「AIっぽさ」を検出する OSS はすでに複数ある。中でも
[coji/natural-japanese](https://github.com/coji/natural-japanese)(MIT)が
実質の決定版で、burstiness・MTLD・TTR の検出を実装済み、
`calibrate.py` という閾値校正のしくみまで持っている。

**ただしその閾値は汎用のビジネス文書で校正されていて、技術記事では校正されていない。**
このリポジトリはそこを埋める。技術記事だけの大規模コーパスから閾値を測り直した。

加えて、**2019〜2022年の Qiita は生成AIが存在しなかった時代の日本語**で、
いま作られている多くのコーパス(note や Zenn を含むもの)と違い
AI生成文の混入がない。この時期のデータは後から取り直せない。

> **迷ったら [CAPABILITIES.md](CAPABILITIES.md) を見る。**
> 何ができて何ができないか、AI判定が可能かどうかが1分で分かる。

## 中身

| パス | 内容 |
|------|------|
| `CAPABILITIES.md` | **できること・できないこと・作れるデータの一覧** |
| `profile/qiita-tech-2020.json` | AI以前の技術記事6,952本から測った参照分布(10指標の分位点とゼロ率) |
| `textlint/textlint-rule-qiita-tech-style.js` | 参照分布と照らして指摘する textlint ルール |
| `prompts/qiita-tech-writing.md` | 執筆・推敲用のプロンプト |
| `prh/qiita-tech-style.yml` | 表記の言い換え辞書(prh形式、自動修正対応) |
| `prompts/ai-to-qiita.md` | AI文章をQiitaらしく直すプロンプト |
| `data/` | 集計済みデータ(424KB)。記事本文は含まない |

## 使い方

### textlint ルール

```bash
npm install --no-save textlint
npx textlint --rulesdir ./src/textlint --config .textlintrc.json 記事.md
```

`.textlintrc.json`:

```json
{ "rules": { "qiita-tech-style": true } }
```

出力例:

```
  3:1  error  文の長短のメリハリが乏しい (burstiness=-0.622、技術記事の参照分布で
               下位10%より低い。中央値は-0.234)。短い文と長い文を混ぜると読みやすくなる。
  3:1  error  漢字が多く硬い (47.6%、参照分布で上位10%より高い。中央値は17.4%)。
```

閾値は指標ごとに上書きできる:

```json
{
  "rules": {
    "qiita-tech-style": {
      "thresholds": { "kanji_ratio": { "upper": 0.28 } },
      "disable": ["boldDensity"],
      "minSentences": 15
    }
  }
}
```

### prh 辞書(表記の言い換え)

```bash
npm install --no-save textlint textlint-rule-prh
npx textlint --config .textlintrc.json 記事.md
npx textlint --config .textlintrc.json --fix 記事.md   # 自動修正
```

`.textlintrc.json`:

```json
{ "rules": { "prh": { "rulePaths": ["./src/prh/qiita-tech-style.yml"] } } }
```

収録語は実測で大きく動いたものだけ。たとえば「下記」は 17.4% → 4.7%(0.27倍)、
「とりあえず」は 9.4% → 3.1%(0.33倍)。

ただし **「減ったから直す」ではなく、技術文書として書き換える理由が
説明できる語だけ**を入れている。実際、当初入れた「ことにより → ため」
「する際に → するとき」は、意味が変わる・正当な用法があるため削除した。

textlint ルールと違い、これは**表記の提案**なので指摘率が高くても問題ない
(2020年の記事200本で35%)。AIっぽさの判定ではない。

### プロファイル単体

`profile/qiita-tech-2020.json` は他のツールからも使える。
各指標の p10/p25/p50/p75/p90 と、その指標をどう読むかの注記が入っている。

ゼロが多い指標には `zero_ratio`(その指標が0の記事の割合)も入れてある。
体言止めは11.8%、太字は65.4%の記事が0で、分位点だけでは実態が見えない。
この割合自体が時代とともに動く(体言止め: 2013年17.4% → 2021年10.3% →
2026年18.8%)ので、[docs/zero-users.md](../docs/zero-users.md) を参照。

## 校正について

閾値は分布の分位点をそのまま使っているわけではない。
**AI以前(2020年8月)の実記事200本を実際に lint にかけ、誤検知率を測って決めた。**

| 段階 | 誤検知率(2020年の記事) |
|------|----------------------|
| profile の p10/p90 をそのまま使用 | 23% |
| 指標ごとに余裕を取る(暫定) | 5.0% |
| **実測の裾(p01/p99)から決め直す(現行)** | **2.5%** |

現行の閾値は、AI以前の記事200本を lint にかけて得た実分布の裾から取っている。

```
bold_per_1k       p95=7.72   p97=8.11   p99=13.58
kanji_ratio       p95=0.264  p97=0.288  p99=0.304
ten_per_sentence  p95=1.333  p97=1.489  p99=1.646
burstiness_mora   p01=-0.470 p03=-0.427 p05=-0.396
cv_sentence_chars p01=0.359  p03=0.401  p05=0.431
```

### 検出力

誤検知を下げても、変化した文章は選別できている。

| 対象 | 指摘された記事 |
|------|--------------|
| 2020年8月(AI以前)の記事200本 | **2.5%** |
| 2026年8月の記事200本 | **12.0%** |

**4.8倍の差。** 同じ閾値で、2026年の記事のほうが4.8倍多く指摘される。

基準は [coji/natural-japanese](https://github.com/coji/natural-japanese) が
採用している「人間コーパスでの誤検知率5%未満」に合わせた。

## やらないこと

**記事単位で「AIが書いた」と判定する機能は入れない。**

- 非ネイティブ英語話者の誤検出率 61% (Liang et al., *Patterns* 2023)
- Vanderbilt 大は Turnitin の AI 検出を停止(FPR 1% でも年750名を誤認)
- OpenAI は自社の検出器を撤回
- Sadasivan et al. は理論的な検出不可能性を示した

Qiita には非ネイティブ日本語話者も書いている。誤検出は実在の書き手を
不当に貶める。このツールが出すのは**指標値と参照分布上の位置**まで。
ラベル付けはしない。判断は書き手に残す。

## 実測で覆った通説

| 通説 | 実測 |
|------|------|
| 体言止めの多用がAIっぽい | 逆。**ゼロなのがAI的**(2020年19.0% → 2026年8.3%) |
| 文が長いのはAIっぽい | 平均文長の伸びはAI以前からの傾向で説明できる |
| 「しましょう」はAIっぽい | 元記事の実測では**減っていた** |

思い込みで禁止語リストを作ると外れる。実測が要る。

## 出典と関連

- 分析の詳細: [`../docs/2020-08-vs-2026-08.md`](../docs/2020-08-vs-2026-08.md)
- 語彙の変化: [`../docs/vocabulary-shift.md`](../docs/vocabulary-shift.md)
- 発想の元: [逆瀬川氏「生成AI以前と以後でエンジニアの文章はどう変わったのか」](https://nyosegawa.com/posts/qiita-writing-before-after-ai/)
- 先行実装: [coji/natural-japanese](https://github.com/coji/natural-japanese) (MIT)

## ライセンス

MIT。プロファイルの数値は Qiita の公開記事を集計した統計量であり、
個々の記事の本文は含まない。
