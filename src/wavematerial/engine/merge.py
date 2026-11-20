# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""Stage 6: give each word a speaker and group the words into turns."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from wavematerial.transcript.schema import Turn, Word


@dataclass(frozen=True)
class SpeakerSegment:
    start: float
    end: float
    speaker: int


def _speaker_for(word: Word, segments: Sequence[SpeakerSegment], previous: int | None) -> int:
    best, best_overlap = None, 0.0
    for s in segments:
        overlap = min(word.end, s.end) - max(word.start, s.start)
        if overlap > best_overlap:
            best, best_overlap = s.speaker, overlap
    if best is not None:
        return best
    if previous is not None:  # in a gap between segments: stay with the current speaker
        return previous
    nearest = min(segments, key=lambda s: max(s.start - word.end, word.start - s.end))
    return nearest.speaker


def merge(
    words: Sequence[Word], segments: Sequence[SpeakerSegment]
) -> tuple[tuple[str, ...], tuple[Turn, ...]]:
    """Speakers (named SPEAKER_00, ... in order of first appearance) and their turns."""
    if not words:
        return (), ()
    if not segments:
        return ("SPEAKER_00",), (Turn("SPEAKER_00", tuple(words)),)

    labels: dict[int, str] = {}
    turns: list[Turn] = []
    run: list[Word] = []
    current: int | None = None
    for w in words:
        spk = _speaker_for(w, segments, current)
        if spk != current and run:
            turns.append(Turn(labels[current], tuple(run)))  # type: ignore[index]
            run = []
        current = spk
        labels.setdefault(spk, f"SPEAKER_{len(labels):02d}")
        run.append(w)
    turns.append(Turn(labels[current], tuple(run)))  # type: ignore[index]
    return tuple(labels.values()), tuple(turns)
