# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""Saved versions of a transcript (the editor's History): named checkpoints to go back to.

Each version is a full snapshot (speakers, names, turns) in the job's `versions/` folder.
Automatic versions (saved when a transcript is opened) are pruned to the newest few; named
ones stay until deleted. `artifact.json` is never touched.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from wavematerial._fsutil import write_text_atomic
from wavematerial.transcript.schema import (
    SCHEMA_VERSION,
    Transcript,
    TranscriptError,
    turns_from_json,
    turns_to_json,
)

VERSIONS = "versions"
KEEP_AUTO = 3
_FILE = re.compile(r"^(\d{4,})\.json$")


def _dir(job_dir: Path) -> Path:
    return job_dir / VERSIONS


def _snapshot(t: Transcript) -> dict[str, Any]:
    return {
        "speakers": list(t.speakers),
        "speaker_names": dict(t.speaker_names),
        "turns": turns_to_json(t.turns),
    }


def _read(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("schema_version") == SCHEMA_VERSION else None


def list_versions(job_dir: Path) -> list[dict[str, Any]]:
    """Newest first: id, name, created (ISO, UTC), auto."""
    out = []
    folder = _dir(job_dir)
    if folder.is_dir():
        for path in folder.iterdir():
            m = _FILE.match(path.name)
            data = _read(path) if m else None
            if data:
                out.append(
                    {
                        "id": int(m.group(1)),
                        "name": str(data.get("name", "")),
                        "created": str(data.get("created", "")),
                        "auto": bool(data.get("auto")),
                    }
                )
    return sorted(out, key=lambda v: v["id"], reverse=True)


def save_version(job_dir: Path, t: Transcript, name: str, *, auto: bool = False) -> int:
    """Save `t` as a version; returns its id. Older automatic versions beyond a few go."""
    existing = list_versions(job_dir)
    vid = (existing[0]["id"] + 1) if existing else 1
    data = {
        "schema_version": SCHEMA_VERSION,
        "name": name,
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "auto": auto,
        **_snapshot(t),
    }
    write_text_atomic(_dir(job_dir) / f"{vid:04d}.json", json.dumps(data, ensure_ascii=False))
    if auto:
        for old in [v for v in list_versions(job_dir) if v["auto"]][KEEP_AUTO:]:
            delete_version(job_dir, old["id"])
    return vid


def load_version(job_dir: Path, vid: int, original: Transcript) -> Transcript:
    """A version as a transcript (language, duration, and engine come from the original)."""
    data = _read(_dir(job_dir) / f"{vid:04d}.json")
    if data is None:
        raise TranscriptError(f"version {vid} is missing or unreadable")
    names = data.get("speaker_names", {})
    return Transcript(
        language=original.language,
        duration=original.duration,
        speakers=tuple(str(s) for s in data.get("speakers", [])),
        turns=turns_from_json(data.get("turns")),
        engine=original.engine,
        speaker_names={str(k): str(v) for k, v in names.items()} if isinstance(names, dict) else {},
    )


def rename_version(job_dir: Path, vid: int, name: str) -> None:
    """Rename a version. A renamed automatic version becomes a named one (kept, not pruned)."""
    path = _dir(job_dir) / f"{vid:04d}.json"
    data = _read(path)
    if data is None:
        raise TranscriptError(f"version {vid} is missing or unreadable")
    data.update(name=name, auto=False)
    write_text_atomic(path, json.dumps(data, ensure_ascii=False))


def delete_version(job_dir: Path, vid: int) -> None:
    (_dir(job_dir) / f"{vid:04d}.json").unlink(missing_ok=True)


def same_content(a: Transcript, b: Transcript) -> bool:
    return _snapshot(a) == _snapshot(b)
