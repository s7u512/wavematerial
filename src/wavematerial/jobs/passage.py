# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""Runs "Transcribe again" on a passage: one at a time, in a subprocess, with the queue held.

Only one model runs at a time, so a passage can start only when no job is being
transcribed, and while it runs the scheduler starts nothing (`Scheduler.try_hold`).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path

from wavematerial.jobs.scheduler import Scheduler

RUNNER = [sys.executable, "-m", "wavematerial.engine.passage"]


@dataclass
class PassageRun:
    job_id: int
    state: str = "running"  # "running", "done", or "failed"
    words: list = field(default_factory=list)
    message: str = ""
    proc: subprocess.Popen | None = None


@dataclass
class Passages:
    current: PassageRun | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def start(
        self, scheduler: Scheduler, job, start: float, end: float, key_terms: list[str]
    ) -> str:
        """Start one; returns "" or why it can't start."""
        with self._lock:
            if self.current and self.current.state == "running":
                return "Another passage is being transcribed."
            if not scheduler.try_hold():
                return "A recording is being transcribed. Try again when it's done."
            job_dir = scheduler.job_dir(job.id)
            fd, name = tempfile.mkstemp(prefix=".passage.", suffix=".json", dir=job_dir)
            os.close(fd)
            out = Path(name)
            settings = scheduler.settings()
            spec = {
                "source": str(job.source),
                "job_dir": str(job_dir),
                "start": start,
                "end": end,
                "models_dir": str(scheduler.paths.models_dir(settings)),
                "choice": asdict(scheduler._choice()),
                "key_terms": key_terms,
                "out": str(out),
            }
            run = PassageRun(job.id)
            log_file = (job_dir / "worker.log").open("ab")
            try:
                run.proc = subprocess.Popen(
                    [*RUNNER, json.dumps(spec)],
                    stdin=subprocess.DEVNULL,
                    stdout=log_file,
                    stderr=log_file,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except OSError:
                log_file.close()
                scheduler.release_hold()
                raise
            self.current = run
            threading.Thread(
                target=self._wait, args=(run, scheduler, out, log_file), daemon=True
            ).start()
            return ""

    def _wait(self, run: PassageRun, scheduler: Scheduler, out: Path, log_file) -> None:
        try:
            code = run.proc.wait()
            try:
                result = json.loads(out.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                result = {}
            if code == 0 and "words" in result:
                run.words, run.state = result["words"], "done"
            else:
                run.message = result.get("error") or "The passage could not be transcribed."
                run.state = "failed"
        finally:
            out.unlink(missing_ok=True)
            log_file.close()
            scheduler.release_hold()

    def cancel(self) -> None:
        run = self.current
        if run and run.state == "running" and run.proc:
            run.proc.terminate()
