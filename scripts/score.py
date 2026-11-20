# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""Score transcripts against a hand-corrected reference: WER and cpWER.

Both files use the txt output layout: one `SPEAKER: text` paragraph per turn.

WER ignores speakers. cpWER (concatenated minimum-permutation WER) joins each speaker's
words, maps hypothesis speakers to reference speakers in the way that gives the fewest
errors, and counts errors over all words, so wrong speaker attribution counts as errors.

Usage: uv run python scripts/score.py REFERENCE.txt NAME=HYPOTHESIS.txt [...]
"""

from __future__ import annotations

import itertools
import re
import sys
from pathlib import Path

_TURN = re.compile(r"^([^:\n]{1,60}):\s*(.*)$")
_WORD = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)*")


def words(text: str) -> list[str]:
    """Lowercase words without punctuation; hyphenated words split."""
    return _WORD.findall(text.lower())


def read_turns(path: Path) -> list[tuple[str, list[str]]]:
    turns = []
    for para in re.split(r"\n\s*\n", path.read_text(encoding="utf-8")):
        para = " ".join(para.split())
        if not para:
            continue
        m = _TURN.match(para)
        if not m:
            raise SystemExit(f"{path}: paragraph without a 'SPEAKER:' label: {para[:60]!r}")
        turns.append((m.group(1).strip(), words(m.group(2))))
    return turns


def edit_distance(ref: list[str], hyp: list[str]) -> int:
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i]
        for j, h in enumerate(hyp, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h)))
        prev = cur
    return prev[-1]


def by_speaker(turns: list[tuple[str, list[str]]]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for speaker, ws in turns:
        out.setdefault(speaker, []).extend(ws)
    return out


def wer(ref_turns, hyp_turns) -> float:
    ref = [w for _, ws in ref_turns for w in ws]
    hyp = [w for _, ws in hyp_turns for w in ws]
    return edit_distance(ref, hyp) / len(ref)


def cpwer(ref_turns, hyp_turns) -> float:
    ref, hyp = by_speaker(ref_turns), by_speaker(hyp_turns)
    ref_spk, hyp_spk = list(ref), list(hyp)
    n = max(len(ref_spk), len(hyp_spk))
    ref_spk += [None] * (n - len(ref_spk))
    hyp_spk += [None] * (n - len(hyp_spk))
    cost = {(r, h): edit_distance(ref.get(r, []), hyp.get(h, [])) for r in ref_spk for h in hyp_spk}
    best = min(
        sum(cost[(r, h)] for r, h in zip(ref_spk, perm, strict=True))
        for perm in itertools.permutations(hyp_spk)
    )
    return best / sum(len(ws) for ws in ref.values())


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    ref = read_turns(Path(argv[0]))
    print(f"{'name':40s} {'WER':>7s} {'cpWER':>7s}")
    for arg in argv[1:]:
        name, _, path = arg.rpartition("=")
        hyp = read_turns(Path(path))
        print(f"{name or path:40s} {wer(ref, hyp):7.1%} {cpwer(ref, hyp):7.1%}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
