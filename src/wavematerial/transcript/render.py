# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""Output formats, rendered from a transcript: txt, srt, vtt, and json.

Formatting is deliberately plain in 1.0.0: `SPEAKER: text` per turn, one subtitle cue per
turn. Speakers appear under the names the user gave them.
"""

from __future__ import annotations

import json
from pathlib import Path

from wavematerial._fsutil import write_text_atomic
from wavematerial.transcript.schema import SCHEMA_VERSION, Transcript, turns_to_json

OUTPUTS = "outputs"
FORMATS = ("txt", "srt", "vtt", "json")


def format_timestamp(seconds: float, separator: str) -> str:
    """`HH:MM:SS<separator>mmm`, rounded to the millisecond (`,` for SRT, `.` for WebVTT)."""
    ms = max(0, round(seconds * 1000))
    hours, ms = divmod(ms, 3_600_000)
    minutes, ms = divmod(ms, 60_000)
    secs, ms = divmod(ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{ms:03d}"


def _line(t: Transcript, turn_index: int) -> str:
    turn = t.turns[turn_index]
    return f"{t.display_name(turn.speaker)}: {turn.text}"


def render_txt(t: Transcript) -> str:
    return "".join(f"{_line(t, i)}\n\n" for i in range(len(t.turns)))


def render_srt(t: Transcript) -> str:
    cues = []
    for i, turn in enumerate(t.turns):
        start = format_timestamp(turn.start, ",")
        end = format_timestamp(turn.end, ",")
        cues.append(f"{i + 1}\n{start} --> {end}\n{_line(t, i)}\n")
    return "\n".join(cues)


def _vtt_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_vtt(t: Transcript) -> str:
    cues = []
    for i, turn in enumerate(t.turns):
        start = format_timestamp(turn.start, ".")
        end = format_timestamp(turn.end, ".")
        cues.append(f"{start} --> {end}\n{_vtt_escape(_line(t, i))}\n")
    return "WEBVTT\n\n" + "\n".join(cues)


def render_json(t: Transcript) -> str:
    turns = turns_to_json(t.turns)
    for turn in turns:
        turn["speaker_name"] = t.display_name(turn["speaker"])
    data = {
        "schema_version": SCHEMA_VERSION,
        "language": t.language,
        "duration_seconds": t.duration,
        "speakers": [{"id": s, "name": t.display_name(s)} for s in t.speakers],
        "engine": dict(t.engine),
        "turns": turns,
    }
    return json.dumps(data, ensure_ascii=False, indent=1) + "\n"


_RENDERERS = {"txt": render_txt, "srt": render_srt, "vtt": render_vtt, "json": render_json}


def write_outputs(job_dir: Path, t: Transcript) -> list[Path]:
    """(Re)write every output format into the job's `outputs/` folder."""
    paths = []
    for fmt in FORMATS:
        path = job_dir / OUTPUTS / f"transcript.{fmt}"
        write_text_atomic(path, _RENDERERS[fmt](t))
        paths.append(path)
    return paths
