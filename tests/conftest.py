# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""Shared pytest fixtures. Tests use the fake engine backend and never need models or a GPU.

Sample text is from NASA's Apollo 11 air-to-ground transcript (public domain).
"""

import pytest

from wavematerial.transcript.schema import Transcript, Turn, Word


def _words(start: float, *pairs: tuple[str, float]) -> tuple[Word, ...]:
    """Words laid end to end from `start`, each `(text, duration)`."""
    out, t = [], start
    for text, dur in pairs:
        out.append(Word(text, round(t, 3), round(t + dur, 3)))
        t += dur
    return tuple(out)


@pytest.fixture
def apollo() -> Transcript:
    return Transcript(
        language="en",
        duration=12.0,
        speakers=("SPEAKER_00", "SPEAKER_01"),
        turns=(
            Turn("SPEAKER_00", _words(0.5, ("30", 0.4), ("seconds.", 0.6))),
            Turn(
                "SPEAKER_01",
                _words(2.0, ("Contact", 0.5), ("light.", 0.5)),
            ),
            Turn(
                "SPEAKER_01",
                _words(
                    5.25, ("Houston,", 0.6), ("Tranquility", 0.7), ("Base", 0.3), ("here.", 0.4)
                ),
            ),
        ),
        engine={"model": "test"},
    )
