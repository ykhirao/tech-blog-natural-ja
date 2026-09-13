/**
 * textlint-rule-qiita-tech-style
 *
 * 日本語技術記事の文体を、生成AI以前(2020年8月)の Qiita 6,952本から測った
 * 実分布と照らして指摘する textlint ルール。
 *
 * 設計:
 * - 「AIが書いた」という判定は出さない。指標値と参照分布上の位置(パーセンタイル)
 *   だけを示す。非ネイティブ話者の誤検出率が高いことが先行研究で示されており
 *   (Liang et al. 2023)、文書単位の白黒判定は実在の書き手を不当に貶める。
 * - 閾値は経験則ではなく実測の分位点。既定では p10/p90 の外側だけを指摘する。
 * - 指摘は「疑い」であって、直すかどうかの判断は書き手に残す。
 *
 * 対象は地の文のみ。コードブロック・表・箇条書き・引用は textlint の
 * Paragraph ノードとして来ないもの、あるいは明示的に除外する。
 *
 * MIT License
 */

const profile = require("../profile/qiita-tech-2020.json");

/**
 * 既定は p10/p90 ではなく、その外側に安全余裕を取った値を使う。
 *
 * 理由: AI以前(2020年8月)の実記事30本で試したところ、p10/p90 では
 * 23% の記事が何かしら指摘された。これらは人間が書いた記事なので
 * すべて誤検知になる。coji/natural-japanese が採用している
 * 「人間コーパスでの誤検知率5%未満」に合わせて余裕を広げた。
 *
 * 指標ごとに余裕の取り方が違うのは、分布の裾の形が違うため。
 * 読点(ten_per_sentence)は裾が長く、p90 だと普通の記事が大量に引っかかった。
 */
const DEFAULT_OPTIONS = {
  // 参照分布のどこから外れたら指摘するか(既定の基準点)
  lower: "p10",
  upper: "p90",
  // 指標ごとの上書き。実測で誤検知が多かったものを緩める。
  thresholds: {
    // 読点は裾が長い。p90(1.105)では人間の記事が大量に引っかかったので
    // 実測の最大付近まで引き上げる
    ten_per_sentence: { upper: 1.8 },
    // 太字も 2020年時点で中央値0のため p90(4.329)は厳しい
    bold_per_1k: { upper: 8.0 },
    // 漢字比率は p90(0.249)だと硬めの技術記事が普通に超える
    kanji_ratio: { upper: 0.32 },
    // burstiness は p10(-0.377)より下だけを見る(既定どおり)
  },
  // 個別に無効化したい指標
  disable: [],
  // 最低文数。短い文章では指標が不安定なので黙る
  minSentences: 10,
};

/** 指標の閾値を取る。thresholds の上書きがあればそれを優先する。 */
function limitOf(opts, key, spec, side) {
  const override = opts.thresholds && opts.thresholds[key];
  if (override && typeof override[side] === "number") return override[side];
  return spec[side === "upper" ? opts.upper : opts.lower];
}

/** 文に切る。metrics.py の split_sentences と同じ規則。 */
function splitSentences(text) {
  const out = [];
  let buf = "";
  for (const rawLine of text.split("\n")) {
    const line = rawLine.trim();
    if (!line) continue;
    buf = buf ? buf + line : line;
    if (/[、，]$/.test(buf)) continue; // 読点で終わる行は次行と連結
    for (const part of buf.split(/(?<=[。！？!?])/)) {
      const p = part.trim();
      if (p) out.push(p);
    }
    buf = "";
  }
  if (buf.trim()) out.push(buf.trim());
  return out;
}

/** モーラ数の近似。拗音は直前と合わせて1拍とみなす。 */
function moraApprox(s) {
  let n = 0;
  for (const ch of s) {
    if (/\s/.test(ch)) continue;
    if ("ゃゅょャュョ".includes(ch)) continue;
    n += 1;
  }
  return n;
}

function mean(xs) {
  return xs.reduce((a, b) => a + b, 0) / xs.length;
}

function pstdev(xs) {
  const m = mean(xs);
  return Math.sqrt(mean(xs.map((x) => (x - m) ** 2)));
}

/** (sd - mean) / (sd + mean)。低いほど文長が単調。 */
function burstiness(lengths) {
  if (lengths.length < 2) return null;
  const m = mean(lengths);
  const sd = pstdev(lengths);
  if (m + sd === 0) return null;
  return (sd - m) / (sd + m);
}

/** 値が参照分布のどのあたりか、言葉で返す。 */
function describePosition(value, spec) {
  if (value <= spec.p10) return "下位10%より低い";
  if (value <= spec.p25) return "下位25%あたり";
  if (value >= spec.p90) return "上位10%より高い";
  if (value >= spec.p75) return "上位25%あたり";
  return "中央付近";
}

const reporter = (context, userOptions = {}) => {
  const { Syntax, RuleError, report, getSource } = context;
  const opts = { ...DEFAULT_OPTIONS, ...userOptions };
  const M = profile.metrics;

  // 地の文だけを集める。コード・表・引用・リストは対象外。
  const paragraphs = [];

  return {
    [Syntax.Paragraph](node) {
      // リスト内の段落は箇条書きなので数えない
      let p = node.parent;
      while (p) {
        if (p.type === Syntax.ListItem || p.type === Syntax.BlockQuote) return;
        p = p.parent;
      }
      paragraphs.push({ node, text: getSource(node) });
    },

    [Syntax.Document + ":exit"](node) {
      if (paragraphs.length === 0) return;

      const fullText = paragraphs.map((p) => p.text).join("\n");
      const sentences = splitSentences(fullText);
      if (sentences.length < opts.minSentences) return;

      const anchor = paragraphs[0].node;
      const moraLens = sentences.map(moraApprox);
      const charLens = sentences.map((s) => s.replace(/\s/g, "").length);
      const findings = [];

      // --- 文長のメリハリ ---
      if (!opts.disable.includes("burstiness")) {
        const b = burstiness(moraLens);
        const spec = M.burstiness_mora;
        if (b !== null && b < limitOf(opts, "burstiness_mora", spec, "lower")) {
          findings.push(
            `文の長短のメリハリが乏しい (burstiness=${b.toFixed(3)}、` +
              `技術記事の参照分布で${describePosition(b, spec)}。` +
              `中央値は${spec.p50})。短い文と長い文を混ぜると読みやすくなる。`
          );
        }
      }

      // --- 文長のばらつき ---
      if (!opts.disable.includes("sentenceVariance")) {
        const m = mean(charLens);
        const cv = m > 0 ? pstdev(charLens) / m : null;
        const spec = M.cv_sentence_chars;
        if (cv !== null && cv < limitOf(opts, "cv_sentence_chars", spec, "lower")) {
          findings.push(
            `文の長さが揃いすぎている (変動係数=${cv.toFixed(3)}、` +
              `参照分布で${describePosition(cv, spec)})。`
          );
        }
      }

      // --- 漢字比率 ---
      if (!opts.disable.includes("kanjiRatio")) {
        const body = fullText.replace(/\s/g, "");
        const kanji = (body.match(/[一-鿿]/g) || []).length;
        const ratio = body.length ? kanji / body.length : 0;
        const spec = M.kanji_ratio;
        if (ratio > limitOf(opts, "kanji_ratio", spec, "upper")) {
          findings.push(
            `漢字が多く硬い (${(ratio * 100).toFixed(1)}%、` +
              `参照分布で${describePosition(ratio, spec)}。` +
              `中央値は${(spec.p50 * 100).toFixed(1)}%)。` +
              `ひらがなで書ける語をひらくと読みやすくなる。`
          );
        }
      }

      // --- 読点 ---
      if (!opts.disable.includes("tenPerSentence")) {
        const ten = (fullText.match(/、/g) || []).length / sentences.length;
        const spec = M.ten_per_sentence;
        if (ten > limitOf(opts, "ten_per_sentence", spec, "upper")) {
          findings.push(
            `1文あたりの読点が多い (${ten.toFixed(2)}個、` +
              `参照分布で${describePosition(ten, spec)})。文を分けることを検討する。`
          );
        }
      }

      // --- 太字 ---
      if (!opts.disable.includes("boldDensity")) {
        const body = fullText.replace(/\s/g, "");
        const bold = (fullText.match(/\*\*[^*\n]+\*\*|__[^_\n]+__/g) || []).length;
        const per1k = body.length ? (bold / body.length) * 1000 : 0;
        const spec = M.bold_per_1k;
        if (per1k > limitOf(opts, "bold_per_1k", spec, "upper")) {
          findings.push(
            `太字が多い (千字あたり${per1k.toFixed(1)}箇所、` +
              `参照分布で${describePosition(per1k, spec)}。` +
              `2020年の技術記事は半数が太字を使っていない)。` +
              `強調が多いと、どれが重要か分からなくなる。`
          );
        }
      }

      for (const message of findings) {
        report(anchor, new RuleError(message));
      }
    },
  };
};

module.exports = {
  linter: reporter,
  fixer: undefined, // 自動修正はしない。判断は書き手に残す。
};
