# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""A job's transcript files: the model output and the user's revision.

`artifact.json` is the model output. It is written once and never modified. The user's
edits and speaker names go into `revision.json` beside it, which records the sha256 of the
artifact it was made from, so a revision is never applied to a different artifact.
Deleting the revision restores the original.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from wavematerial._fsutil import write_text_atomic, write_text_once
from wavematerial.transcript.schema import (
    SCHEMA_VERSION,
    Transcript,
    TranscriptError,
    check_schema_version,
    turns_from_json,
    turns_to_json,
)

ARTIFACT = "artifact.json"
REVISION = "revision.json"

log = logging.getLogger(__name__)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_bytes())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TranscriptError(f"{path}: not valid JSON: {exc}") from exc


def _dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=1) + "\n"


def write_artifact(job_dir: Path, transcript: Transcript) -> None:
    """Write the model output. Raises `FileExistsError` if the job already has one."""
    data = {
        "schema_version": SCHEMA_VERSION,
        "language": transcript.language,
        "duration_seconds": transcript.duration,
        "speakers": list(transcript.speakers),
        "engine": dict(transcript.engine),
        "turns": turns_to_json(transcript.turns),
    }
    write_text_once(job_dir / ARTIFACT, _dumps(data))


def read_artifact(job_dir: Path) -> Transcript:
    """The original model output, without any edits."""
    path = job_dir / ARTIFACT
    data = _read_json(path)
    try:
        check_schema_version(data)
        return Transcript(
            language=str(data["language"]),
            duration=float(data["duration_seconds"]),
            speakers=tuple(str(s) for s in data["speakers"]),
            turns=turns_from_json(data["turns"]),
            engine={str(k): str(v) for k, v in data.get("engine", {}).items()},
        )
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise TranscriptError(f"{path}: {exc}") from exc


def _artifact_sha256(job_dir: Path) -> str:
    return hashlib.sha256((job_dir / ARTIFACT).read_bytes()).hexdigest()


def has_revision(job_dir: Path) -> bool:
    return (job_dir / REVISION).exists()


def save_revision(job_dir: Path, transcript: Transcript) -> None:
    """Save the user's edits and speaker names. The artifact is not touched."""
    data = {
        "schema_version": SCHEMA_VERSION,
        "artifact_sha256": _artifact_sha256(job_dir),
        "speakers": list(transcript.speakers),
        "speaker_names": dict(transcript.speaker_names),
        "turns": turns_to_json(transcript.turns),
    }
    write_text_atomic(job_dir / REVISION, _dumps(data))


def read_current(job_dir: Path) -> Transcript:
    """The transcript as the user last left it: the artifact with the revision applied.

    A revision made from a different artifact, or one that can't be read, is ignored (and
    logged), so the original is shown instead.
    """
    original = read_artifact(job_dir)
    path = job_dir / REVISION
    if not path.exists():
        return original
    try:
        data = _read_json(path)
        check_schema_version(data)
        if data.get("artifact_sha256") != _artifact_sha256(job_dir):
            raise TranscriptError("it was made from a different artifact")
        names = data.get("speaker_names", {})
        if not isinstance(names, dict):
            raise TranscriptError("speaker_names must be an object")
        return Transcript(
            language=original.language,
            duration=original.duration,
            speakers=tuple(str(s) for s in data["speakers"]),
            turns=turns_from_json(data["turns"]),
            engine=original.engine,
            speaker_names={str(k): str(v) for k, v in names.items() if str(v).strip()},
        )
    except (TranscriptError, KeyError, TypeError, ValueError) as exc:
        log.warning("Ignoring revision %s: %s", path, exc)
        return original


# Edited words get approximate timings, so allow a little slack before calling them wrong.
_SLACK = 0.5


def edited_transcript(data: Any, original: Transcript) -> Transcript:
    """Check an edited transcript sent by the editor; raise `TranscriptError` if it's wrong.

    `data` has `speakers` (ids), `names` (id -> name), and `turns` in the JSON layout.
    Timings must stay in order and inside the recording; they are never edited by hand,
    only carried over or shared out by the editor, so anything else is a bug.
    """
    if not isinstance(data, dict):
        raise TranscriptError("expected a JSON object")
    speakers = data.get("speakers")
    names = data.get("names", {})
    if (
        not isinstance(speakers, list)
        or not all(isinstance(s, str) and s.strip() for s in speakers)
        or len(set(speakers)) != len(speakers)
    ):
        raise TranscriptError("speakers must be a list of distinct ids")
    if not isinstance(names, dict) or not all(isinstance(v, str) for v in names.values()):
        raise TranscriptError("names must map speaker ids to text")
    turns = turns_from_json(data.get("turns"))
    previous = 0.0
    for i, turn in enumerate(turns):
        if turn.speaker not in speakers:
            raise TranscriptError(f"turn {i} has an unknown speaker {turn.speaker!r}")
        for w in turn.words:
            if not w.text.strip() or any(c.isspace() for c in w.text):
                raise TranscriptError(f"turn {i} has a word that is empty or contains a space")
            if w.start < previous - 1e-3 or w.start < 0 or w.end > original.duration + _SLACK:
                raise TranscriptError(f"turn {i} has a word out of order or outside the recording")
            previous = w.start
    return Transcript(
        language=original.language,
        duration=original.duration,
        speakers=tuple(speakers),
        turns=turns,
        engine=original.engine,
        speaker_names={str(k): v.strip() for k, v in names.items() if k in speakers and v.strip()},
    )


def restore_original(job_dir: Path) -> None:
    """Drop the user's edits and speaker names."""
    (job_dir / REVISION).unlink(missing_ok=True)
