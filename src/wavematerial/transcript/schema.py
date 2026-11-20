# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""The transcript data model and its JSON form (schema version 1).

A transcript is a list of turns; each turn is one speaker's run of words with timings in
seconds. A turn's text, start, and end are derived from its words, so editing words is the
only way to change them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = 1


class TranscriptError(ValueError):
    """A transcript file is malformed or from an unknown schema version."""


@dataclass(frozen=True)
class Word:
    text: str
    start: float
    end: float


@dataclass(frozen=True)
class Turn:
    speaker: str
    words: tuple[Word, ...]

    @property
    def start(self) -> float:
        return self.words[0].start

    @property
    def end(self) -> float:
        return self.words[-1].end

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


@dataclass(frozen=True)
class Transcript:
    language: str
    duration: float
    speakers: tuple[str, ...]
    turns: tuple[Turn, ...]
    engine: dict[str, str] = field(default_factory=dict)
    speaker_names: dict[str, str] = field(default_factory=dict)

    def display_name(self, speaker: str) -> str:
        """The name the user gave this speaker, or its id (`SPEAKER_00`)."""
        return self.speaker_names.get(speaker) or speaker


def turns_to_json(turns: tuple[Turn, ...]) -> list[dict[str, Any]]:
    return [
        {
            "speaker": t.speaker,
            "start": t.start,
            "end": t.end,
            "text": t.text,
            "words": [{"word": w.text, "start": w.start, "end": w.end} for w in t.words],
        }
        for t in turns
    ]


def turns_from_json(data: Any) -> tuple[Turn, ...]:
    """Parse turns; a turn's stored `text`, `start`, and `end` are ignored (they're derived)."""
    if not isinstance(data, list):
        raise TranscriptError("turns must be a list")
    turns = []
    for i, t in enumerate(data):
        try:
            words = tuple(
                Word(str(w["word"]), float(w["start"]), float(w["end"])) for w in t["words"]
            )
            speaker = str(t["speaker"])
        except (KeyError, TypeError, ValueError) as exc:
            raise TranscriptError(f"turn {i} is malformed: {exc!r}") from exc
        if any(w.end < w.start for w in words):
            raise TranscriptError(f"turn {i} has a word that ends before it starts")
        if words:  # a turn without words has nothing to show or play
            turns.append(Turn(speaker, words))
    return tuple(turns)


def check_schema_version(data: Any) -> None:
    if not isinstance(data, dict):
        raise TranscriptError("expected a JSON object")
    version = data.get("schema_version")
    if version != SCHEMA_VERSION:
        raise TranscriptError(f"unsupported schema version {version!r}")
