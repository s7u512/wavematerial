# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""The job store: one SQLite row per job (WAL mode), plus GPUs remembered as unreliable."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

STATES = ("queued", "running", "done", "failed", "cancelled")

# Rough share of a job's time per stage, for an overall progress figure and ETA.
STAGE_WEIGHTS = {
    "decode": 0.02,
    "vad": 0.03,
    "timings": 0.20,
    "text": 0.55,
    "diarize": 0.15,
    "merge": 0.03,
    "render": 0.02,
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    source TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    min_speakers INTEGER NOT NULL,
    max_speakers INTEGER NOT NULL,
    key_terms TEXT NOT NULL DEFAULT '[]',
    state TEXT NOT NULL CHECK (state IN ('queued','running','done','failed','cancelled')),
    stage TEXT,
    stage_fraction REAL NOT NULL DEFAULT 0,
    error TEXT,
    device TEXT,
    position REAL NOT NULL,
    duration REAL,
    speakers INTEGER,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);
CREATE TABLE IF NOT EXISTS unreliable_gpus (
    device_id TEXT PRIMARY KEY,
    reason TEXT NOT NULL,
    at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def fingerprint(path: Path) -> str:
    """Size plus a hash of the first and last MiB: cheap, and catches a replaced file."""
    size = path.stat().st_size
    h = hashlib.sha256(str(size).encode())
    with path.open("rb") as f:
        h.update(f.read(1 << 20))
        if size > 2 << 20:
            f.seek(-(1 << 20), 2)
            h.update(f.read())
    return h.hexdigest()


@dataclass(frozen=True)
class Job:
    id: int
    name: str
    source: Path
    fingerprint: str
    min_speakers: int
    max_speakers: int
    key_terms: tuple[str, ...]
    state: str
    stage: str | None
    stage_fraction: float
    error: str | None
    device: str | None
    position: float
    duration: float | None
    speakers: int | None
    created_at: str
    started_at: str | None
    finished_at: str | None

    @property
    def progress(self) -> float:
        """Overall progress, 0..1, from the stage weights."""
        if self.state == "done":
            return 1.0
        if not self.stage:
            return 0.0
        done = 0.0
        for name, weight in STAGE_WEIGHTS.items():
            if name == self.stage:
                return done + weight * self.stage_fraction
            done += weight
        return done


def _job(row: sqlite3.Row) -> Job:
    d = dict(row)
    d["source"] = Path(d["source"])
    d["key_terms"] = tuple(json.loads(d["key_terms"]))
    return Job(**d)


class JobStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(_SCHEMA)

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        """A short-lived connection per call, so any thread can use the store."""
        db = sqlite3.connect(self.db_path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def add(
        self,
        source: Path,
        *,
        min_speakers: int,
        max_speakers: int,
        key_terms=(),
        duration: float | None = None,
    ) -> Job:
        with self._db() as db:
            position = db.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM jobs").fetchone()[0]
            cur = db.execute(
                "INSERT INTO jobs (name, source, fingerprint, min_speakers, max_speakers,"
                " key_terms, state, position, duration, created_at)"
                " VALUES (?,?,?,?,?,?,'queued',?,?,?)",
                (
                    source.name,
                    str(source),
                    fingerprint(source),
                    min_speakers,
                    max_speakers,
                    json.dumps(list(key_terms)),
                    position,
                    duration,
                    _now(),
                ),
            )
            job_id = cur.lastrowid
        return self.get(job_id)

    def get(self, job_id: int) -> Job:
        with self._db() as db:
            row = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return _job(row)

    def all(self) -> list[Job]:
        with self._db() as db:
            rows = db.execute("SELECT * FROM jobs ORDER BY position").fetchall()
        return [_job(r) for r in rows]

    def next_queued(self) -> Job | None:
        with self._db() as db:
            row = db.execute(
                "SELECT * FROM jobs WHERE state = 'queued' ORDER BY position LIMIT 1"
            ).fetchone()
        return _job(row) if row else None

    def update(self, job_id: int, **fields) -> None:
        if "state" in fields and fields["state"] not in STATES:
            raise ValueError(fields["state"])
        cols = ", ".join(f"{k} = ?" for k in fields)
        with self._db() as db:
            db.execute(f"UPDATE jobs SET {cols} WHERE id = ?", (*fields.values(), job_id))

    def set_state(self, job_id: int, state: str, **fields) -> None:
        stamps = {}
        if state == "running":
            stamps["started_at"] = _now()
        elif state in ("done", "failed", "cancelled"):
            stamps["finished_at"] = _now()
        self.update(job_id, state=state, **stamps, **fields)

    def move(self, job_id: int, before: int | None) -> None:
        """Put a queued job just before another one, or at the end of the queue."""
        with self._db() as db:
            if before is None:
                pos = db.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM jobs").fetchone()[0]
            else:
                target = db.execute("SELECT position FROM jobs WHERE id = ?", (before,)).fetchone()
                prev = db.execute(
                    "SELECT MAX(position) FROM jobs WHERE position < ? AND id != ?",
                    (target[0], job_id),
                ).fetchone()[0]
                pos = (target[0] + (prev if prev is not None else target[0] - 1)) / 2
            db.execute("UPDATE jobs SET position = ? WHERE id = ?", (pos, job_id))

    def delete(self, job_id: int) -> None:
        with self._db() as db:
            db.execute("DELETE FROM jobs WHERE id = ?", (job_id,))

    def recover(self) -> list[int]:
        """At startup: jobs left `running` by a crash go back to the queue. Returns their ids."""
        with self._db() as db:
            ids = [r[0] for r in db.execute("SELECT id FROM jobs WHERE state = 'running'")]
            db.execute("UPDATE jobs SET state = 'queued' WHERE state = 'running'")
        return ids

    def mark_gpu_unreliable(self, device_id: str, reason: str) -> None:
        with self._db() as db:
            db.execute(
                "INSERT OR REPLACE INTO unreliable_gpus VALUES (?,?,?)", (device_id, reason, _now())
            )

    def unreliable_gpus(self) -> set[str]:
        with self._db() as db:
            return {r[0] for r in db.execute("SELECT device_id FROM unreliable_gpus")}

    def reset_unreliable_gpus(self) -> None:
        with self._db() as db:
            db.execute("DELETE FROM unreliable_gpus")
