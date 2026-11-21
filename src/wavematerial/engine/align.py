# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""Stage 6 (with merge): the hybrid aligner. Qwen supplies the words, Parakeet the timings.

Within each chunk, Qwen's words are aligned to Parakeet's with difflib. A Qwen word that
matches a Parakeet word takes its timing exactly; runs that differ are spread over the time
the differing Parakeet words (or the gap between matches) cover, in proportion to length.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from wavematerial.transcript.schema import Word

_NON_WORD = re.compile(r"[^\w']+")
# CJK ideographs, kana, hangul, and CJK and fullwidth punctuation.
_CJK = re.compile(
    "[\u2e80-\u2fdf\u3000-\u303f\u3040-\u30ff\u3100-\u31ff\u3400-\u4dbf"
    "\u4e00-\u9fff\uac00-\ud7af\uf900-\ufaff\uff00-\uffef]+"
)


def drop_cjk(text: str) -> str:
    """English text without CJK characters, which Qwen sometimes writes for fillers (嗯)."""
    return " ".join(_CJK.sub(" ", text).split())


def normalise(word: str) -> str:
    return _NON_WORD.sub("", word.lower())


def split_words(text: str) -> list[str]:
    """Split text into words, attaching punctuation-only pieces to the word before."""
    out: list[str] = []
    for piece in text.split():
        if out and not normalise(piece):
            out[-1] += piece
        else:
            out.append(piece)
    if len(out) > 1 and not normalise(out[0]):  # leading punctuation joins the next word
        out[1] = out[0] + out[1]
        out.pop(0)
    return out


@dataclass
class AlignStats:
    exact: int = 0
    interpolated: int = 0
    fallback_chunks: int = 0


def _spread(texts: list[str], t0: float, t1: float) -> list[Word]:
    """Lay `texts` end to end over [t0, t1], each taking time in proportion to its length."""
    t1 = max(t1, t0)
    weights = [len(normalise(t)) + 1 for t in texts]
    total = sum(weights)
    out, acc = [], 0
    for text, w in zip(texts, weights, strict=True):
        start = t0 + (t1 - t0) * acc / total
        acc += w
        out.append(Word(text, round(start, 3), round(t0 + (t1 - t0) * acc / total, 3)))
    return out


def align_chunk(
    text: str,
    timed: list[Word],
    chunk: tuple[float, float],
    stats: AlignStats | None = None,
) -> list[Word]:
    """Qwen's `text` for one chunk, timed with Parakeet's `timed` words."""
    stats = stats if stats is not None else AlignStats()
    texts = split_words(text)
    if not texts:
        if timed:  # Qwen produced nothing here: keep Parakeet's own words
            stats.fallback_chunks += 1
        return list(timed)
    if not timed:
        stats.interpolated += len(texts)
        return _spread(texts, *chunk)

    a = [normalise(t) for t in texts]
    b = [normalise(w.text) for w in timed]
    out: list[Word] = []
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            out.extend(
                Word(texts[i], timed[j].start, timed[j].end)
                for i, j in zip(range(i1, i2), range(j1, j2), strict=True)
            )
            stats.exact += i2 - i1
        elif i2 > i1:  # replace or insert: Qwen words that need a time
            if j2 > j1:
                t0, t1 = timed[j1].start, timed[j2 - 1].end
            else:
                t0 = timed[j1 - 1].end if j1 > 0 else chunk[0]
                t1 = timed[j1].start if j1 < len(timed) else chunk[1]
            if out:
                t0 = max(t0, out[-1].end)
            out.extend(_spread(texts[i1:i2], t0, t1))
            stats.interpolated += i2 - i1
    return out
