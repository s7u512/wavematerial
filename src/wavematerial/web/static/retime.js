// SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
// Timings for edited words: the aligner's rule from engine/align.py, in the page.
// Words that still match keep their timings exactly; runs that changed share out the time
// the old words covered (or the gap they sit in), in proportion to their length.
(() => {
  "use strict";
  const NON_WORD = /[^\p{L}\p{N}_']+/gu;
  const normalise = (word) => word.toLowerCase().replace(NON_WORD, "");

  // Split text into words, attaching punctuation-only pieces to the word before.
  function splitWords(text) {
    const out = [];
    for (const piece of text.split(/\s+/)) {
      if (!piece) continue;
      if (out.length && !normalise(piece)) out[out.length - 1] += piece;
      else out.push(piece);
    }
    if (out.length > 1 && !normalise(out[0])) out.splice(0, 2, out[0] + out[1]);
    return out;
  }

  const r3 = (x) => Math.round(x * 1000) / 1000;

  function spread(texts, t0, t1) {
    t1 = Math.max(t1, t0);
    const weights = texts.map((t) => normalise(t).length + 1);
    const total = weights.reduce((a, b) => a + b, 0);
    let acc = 0;
    return texts.map((text, i) => {
      const start = t0 + ((t1 - t0) * acc) / total;
      acc += weights[i];
      return { text, start: r3(start), end: r3(t0 + ((t1 - t0) * acc) / total) };
    });
  }

  // Longest common subsequence of a and b, as matched index pairs in order.
  function matches(a, b) {
    const n = a.length;
    const m = b.length;
    const dp = new Uint32Array((n + 1) * (m + 1));
    for (let i = n - 1; i >= 0; i--) {
      for (let j = m - 1; j >= 0; j--) {
        dp[i * (m + 1) + j] =
          a[i] === b[j]
            ? dp[(i + 1) * (m + 1) + j + 1] + 1
            : Math.max(dp[(i + 1) * (m + 1) + j], dp[i * (m + 1) + j + 1]);
      }
    }
    const pairs = [];
    let i = 0;
    let j = 0;
    while (i < n && j < m) {
      if (a[i] === b[j]) {
        pairs.push([i++, j++]);
      } else if (dp[(i + 1) * (m + 1) + j] >= dp[i * (m + 1) + j + 1]) {
        i++;
      } else {
        j++;
      }
    }
    return pairs;
  }

  // Time `texts` (the new words) using `old` ({text, start, end}) within [t0, t1].
  function retime(texts, old, t0, t1) {
    if (!texts.length) return [];
    if (!old.length) return spread(texts, t0, t1);
    const a = texts.map(normalise);
    const b = old.map((w) => normalise(w.text));
    // Typing changes a small region, so match the common ends directly.
    let pre = 0;
    while (pre < a.length && pre < b.length && a[pre] === b[pre]) pre++;
    let suf = 0;
    while (
      suf < a.length - pre &&
      suf < b.length - pre &&
      a[a.length - 1 - suf] === b[b.length - 1 - suf]
    ) suf++;
    const pairs = [];
    for (let k = 0; k < pre; k++) pairs.push([k, k]);
    for (const [i, j] of matches(a.slice(pre, a.length - suf), b.slice(pre, b.length - suf))) {
      pairs.push([i + pre, j + pre]);
    }
    for (let k = suf; k > 0; k--) pairs.push([a.length - k, b.length - k]);

    const out = [];
    let i = 0;
    let j = 0;
    const fill = (i2, j2) => {
      if (i2 <= i) return;
      let s;
      let e;
      if (j2 > j) {
        s = old[j].start;
        e = old[j2 - 1].end;
      } else {
        s = j > 0 ? old[j - 1].end : t0;
        e = j < old.length ? old[j].start : t1;
      }
      if (out.length) s = Math.max(s, out[out.length - 1].end);
      out.push(...spread(texts.slice(i, i2), s, e));
    };
    for (const [pi, pj] of pairs) {
      fill(pi, pj);
      out.push({ text: texts[pi], start: old[pj].start, end: old[pj].end });
      i = pi + 1;
      j = pj + 1;
    }
    fill(texts.length, old.length);
    return out;
  }

  window.wmRetime = { normalise, splitWords, retime };
})();
