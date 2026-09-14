# 集計済みデータ

Qiita の記事を集計した統計量。**記事の本文は含まない。**

生データ(`data/raw/`)は7GBあるので公開できない。
API から再取得できるよう、取得スクリプトを `scripts/fetch_qiita.py` に置いてある。

| ファイル | 内容 | サイズ |
|---------|------|-------|
| `word_timeline.json` | 頻出500語の年次推移(記事出現率%) | 143 KB |
| `word_timeline_norm.json` | 同上(千字あたりの出現数) | 141 KB |
| `vocab_2020_2026_top500.json` | 語彙の対数オッズ比(2020 vs 2026) | 64 KB |
| `vocab_nonai_top500.json` | 同上(AI言及記事を除いた部分集合) | 64 KB |
| `change_threshold.json` | 変化判定の閾値(取得前に固定したもの) | 1 KB |

## word_timeline.json

```json
{
  "years": ["2015", "2016", ..., "2026"],
  "article_counts": {"2015": 2360, ...},
  "words": [
    {
      "word": "設計",
      "series": [3.64, ...],      // years と同じ並び
      "pre_slope": 0.385,          // AI以前(2022年まで)の年あたり変化
      "post_slope": 8.580,         // AI以後の年あたり変化
      "first": 3.64, "last": 40.66, "ratio": 11.17
    }
  ]
}
```

`series` の単位はファイルによって違う。

- `word_timeline.json` — 記事出現率(%)。その語を含む記事の割合
- `word_timeline_norm.json` — 千字あたりの延べ出現数

記事が長くなると前者だけ上がるので、両方置いてある。
ただし実測すると倍率はほとんど変わらなかった
([../../docs/word-trends-500.md](../../docs/word-trends-500.md))。

## vocab_*.json

対数オッズ比(informative Dirichlet prior)。
`z` の絶対値が大きい順に上位500語。

```json
{
  "word": "実測",
  "z": 18.0,                  // 正なら2026年側に偏る
  "doc_ratio_a": 0.0008,      // 2020年の記事出現率
  "doc_ratio_b": 0.0817,      // 2026年の記事出現率
  "freq_a": 6, "freq_b": 886  // 延べ出現数
}
```

`vocab_nonai_top500.json` は、AI に言及する記事を除いた部分集合。
話題の変化と文体の変化を分けるために作った。

## change_threshold.json

「変化した」と判定する閾値。**2021年以降のデータを取得する前に固定した。**
結果を見てから線を引くと都合のいい場所に引いてしまうため。

AI以前(2019年3〜8月)の月次変動幅の3倍を基準にしている。

## 出典と再現

すべて Qiita API v2 から取得した公開記事の集計。
取得と集計の手順は [../../docs/README.md](../../docs/README.md) にある。

```bash
./scripts/fetch_qiita.py --months 2020-08,2026-08
./scripts/build_dataset.py --months 2020-08,2026-08
./scripts/word_timeline.py --top 500
```

`.env` に `QIITA_API_TOKEN` が要る。

## ライセンス

集計値は MIT。
元記事の著作権は各執筆者にある。このデータには本文を含まないが、
語の出現頻度という統計量である点に留意すること。
