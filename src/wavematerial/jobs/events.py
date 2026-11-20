# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""A job's human-readable history (`events.log`) and stage timings (`stages.json`).

The job-details drawer shows both. The worker's technical log is `worker.log`.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

from wavematerial._fsutil import write_text_atomic

EVENTS = "events.log"
STAGES = "stages.json"

# The stages as the user sees them. Rendering is quick and shown as part of assembling.
STAGE_LABELS = {
    "decode": "Read audio",
    "vad": "Find speech",
    "timings": "Word timings",
    "text": "Transcribe text",
    "diarize": "Identify speakers",
    "merge": "Assemble transcript",
}


def log_event(job_dir: Path, text: str) -> None:
    job_dir.mkdir(parents=True, exist_ok=True)
    with (job_dir / EVENTS).open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%H:%M:%S}  {text}\n")


def read_events(job_dir: Path, limit: int = 200) -> list[str]:
    try:
        lines = (job_dir / EVENTS).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    return lines[-limit:]


def stage_times(job_dir: Path) -> dict[str, float]:
    try:
        return json.loads((job_dir / STAGES).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


class StageClock:
    """Times the stages that actually run (skipped, already-saved stages keep their old time)."""

    def __init__(self, job_dir: Path):
        self.job_dir = job_dir
        self._started: dict[str, float] = {}

    def progress(self, stage: str, fraction: float) -> None:
        if fraction < 1.0:
            self._started.setdefault(stage, time.monotonic())
            return
        started = self._started.pop(stage, None)
        if started is None:
            return  # loaded from a saved file: nothing ran
        seconds = round(time.monotonic() - started, 1)
        times = stage_times(self.job_dir)
        times[stage] = seconds
        write_text_atomic(self.job_dir / STAGES, json.dumps(times))
        label = STAGE_LABELS.get(stage)
        if label:
            log_event(self.job_dir, f"{label.lower()} done ({seconds} s)")
