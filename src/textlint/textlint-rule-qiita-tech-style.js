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
  /**
   * 指標ごとの閾値。AI以前(2020年8月)の実記事200本を実際にlintにかけて
   * 測った分布の裾から決めている。各指標が単独で誤検知2%程度になる位置。
   *
   * 実測値(n=172、10文以上の記事):
   *   bold_per_1k       p95=7.72  p97=8.11  p99=13.58
   *   kanji_ratio       p95=0.264 p97=0.288 p99=0.304
   *   ten_per_sentence  p95=1.333 p97=1.489 p99=1.646
   *   burstiness_mora   p01=-0.470 p03=-0.427 p05=-0.396
   *   cv_sentence_chars p01=0.359  p03=0.401  p05=0.431
   */
  thresholds: {
    ten_per_sentence: { upper: 1.65 },   // p99
    bold_per_1k: { upper: 13.0 },        // p99 付近
    kanji_ratio: { upper: 0.305 },       // p99
    burstiness_mora: { lower: -0.45 },   // p01〜p03 の間
    cv_sentence_chars: { lower: 0.38 },  // p01〜p03 の間
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
            `文の長短のメリハリが乏しい (文長のばらつき=${b.toFixed(3)}、` +
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

      // --- 翻訳調の骨組み ---
      // 英語の構文をそのまま日本語に移した型。実測で増えているものだけ。
      //   「という点です」 0.57% → 4.68% (8倍)   the point that X
      //   「重要なのは」   0.75% → 10.79% (14倍)  What matters is
      //   「一方で」       0.009 → 0.064/千字 (7倍) On the other hand
      // 自動修正はしない。prh で置換を試したところ、文の後半を落とす
      // 危険な置換になったため(詳細は prh/qiita-tech-style.yml のコメント)。
      if (!opts.disable.includes("translationese")) {
        const checks = [
          { re: /という点です/g, name: "「〜という点です」",
            hint: "英語 the point that の直訳。「ことです」で足りることが多い" },
          { re: /重要なのは/g, name: "「重要なのは〜」",
            hint: "英語 What matters is の型。主語を立てて言い切れないか" },
          { re: /ここで重要(?:なのは|になる)/g, name: "「ここで重要なのは」",
            hint: "英語 Here, it is important の型" },
          // 限定の構文。英語 only X / it is only X that をなぞった形。
          // 実測: 「〜だけは」5.49倍、「という事実」7.19倍、「唯一」4.57倍。
          // 「〜だけは〜している」は主語を立てれば言い切れることが多い。
          { re: /[ぁ-んァ-ヶ一-龥]{2,12}だけは/g, name: "「〜だけは」",
            hint: "英語 only X の型。「〜は」で足りないか確かめる" },
          { re: /という事実/g, name: "「〜という事実」",
            hint: "英語 the fact that の直訳。「という事実」を外しても通じることが多い" },
          { re: /注目すべき/g, name: "「注目すべき」",
            hint: "英語 Notably の型" },
          // 学術論文調のヘッジ。英語 is not evidence that / supports をなぞった形。
          // 実測: 「証拠ではない」「を支持する」は2020年に0件(2026年で18件/14件)。
          // 技術記事では使われていなかった語彙。
          { re: /(?:証拠|根拠)[でと]は(?:ない|なら)/g, name: "「〜の証拠ではない」",
            hint: "英語 is not evidence that の型。2020年の技術記事には無かった言い方" },
          { re: /を支持する/g, name: "「〜を支持する」",
            hint: "英語 supports の直訳。論文調。「〜とは言えない」などで足りないか" },
          { re: /に(?:過ぎ|すぎ)ない/g, name: "「〜にすぎない」",
            hint: "英語 is merely の型。4.75倍に増えている" },
          // 英語構文の直訳。25パターンを実データで検定して、
          // 2倍以上に増えたものだけを採用した。
          { re: /(?:の|という)観点/g, name: "「〜の観点」",
            hint: "英語 from the perspective / in terms of の型。3.7倍に増えている" },
          { re: /結果として/g, name: "「結果として」",
            hint: "英語 As a result の型。3.3倍。「その結果」「なので」で足りないか" },
          { re: /(?:我々|私たち)[はが]/g, name: "「我々は/私たちは」",
            hint: "英語 We の型。日本語は主語を省ける。2.9倍に増えている" },
          { re: /^(?:したがって|従って)/gm, name: "「したがって」",
            hint: "英語 Therefore の型。2.4倍。「だから」「なので」で足りないか" },
          // 相場のチャート用語。指標が下がり始めることを「折れる」と書く用法は
          // 技術記事にはない。実測(2015〜2026年の各年8月)で「折れる」は
          // 0.00〜0.38% しか出ず、2026年の10件中9件が「心が折れる」だった。
          // 「心が折れる」は正当な用法なので除く。
          { re: /(?<!心が|心は)折れ(?:る|た|て(?!い?ない)|ます|ました)/g,
            name: "「折れる」(グラフの意味で)",
            hint: "相場のチャート用語。技術記事では通じない。"
                + "「下がり始める」「向きが変わる」で言い換えられないか",
            note: "実測では12年間 0.00〜0.38% しか使われていない。" },
        ];
        // 減った構文もある。翻訳調=増加とは限らない。
        //   しかしながら(However)      0.38倍
        //   〜と思われる(is thought)   0.48倍
        //   〜されている(is being done) 0.75倍
        //   〜することで(by doing)     0.84倍
        // 受動態と硬い接続詞はむしろ避けられるようになった。
        // 「まさに」「唯一」は増えている(6.16倍 / 4.57倍)が、ルールに入れない。
        // coji 氏の実測では「まさに」は人間コーパスでの誤検知の63%を占めており、
        // 日常語として正当に使われる。増えたことと直すべきことは別。
        for (const c of checks) {
          const hits = fullText.match(c.re);
          // 1回なら文章の癖として許容する。2回以上で癖として指摘。
          if (hits && hits.length >= 2) {
            // 既定は「増えている型」。増加が根拠でないものは note で上書きする
            // (「折れる」は増えていない。技術記事で通じないから指摘している)。
            const note = c.note || "実測では2020年より大きく増えている型。";
            findings.push(`${c.name}が${hits.length}回。${c.hint}。${note}`);
          }
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
