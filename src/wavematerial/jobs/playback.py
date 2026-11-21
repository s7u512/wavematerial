# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""Playback copies for jobs finished without one, made in a subprocess on first request.

The decode stage writes `playback.opus` for every new job. Older jobs get theirs the first
time the editor asks: `python -m wavematerial.engine.playback` decodes the source again in
its own process, so the web server never does the work. A failure (say, the original was
moved) is remembered until the app restarts, so the editor doesn't retry in a loop.
"""

from __future__ import annotations

import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

from wavematerial.engine.playback import PLAYBACK

MAKER = [sys.executable, "-m", "wavematerial.engine.playback"]


@dataclass(frozen=True)
class PlaybackState:
    state: str  # "ready", "making", or "failed"
    message: str = ""


@dataclass
class PlaybackCopies:
    _running: dict[int, subprocess.Popen] = field(default_factory=dict)
    _failed: dict[int, str] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def ensure(self, job_id: int, source: Path, job_dir: Path) -> PlaybackState:
        """The copy's state, starting to make it if there is none yet."""
        with self._lock:
            if (job_dir / PLAYBACK).exists():
                return PlaybackState("ready")
            if job_id in self._failed:
                return PlaybackState("failed", self._failed[job_id])
            if job_id not in self._running:
                if not source.exists():
                    self._failed[job_id] = (
                        f"The original file is no longer at {source}, so the audio can't be played."
                    )
                    return PlaybackState("failed", self._failed[job_id])
                proc = subprocess.Popen(
                    [*MAKER, str(source), str(job_dir)],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                self._running[job_id] = proc
                threading.Thread(
                    target=self._wait, args=(job_id, proc), name=f"playback-{job_id}", daemon=True
                ).start()
            return PlaybackState("making")

    def _wait(self, job_id: int, proc: subprocess.Popen) -> None:
        _, err = proc.communicate()
        with self._lock:
            self._running.pop(job_id, None)
            if proc.returncode != 0:
                lines = [line for line in (err or "").strip().splitlines() if line.strip()]
                self._failed[job_id] = (
                    lines[-1] if lines else "The audio for playback could not be made."
                )

    def shutdown(self) -> None:
        with self._lock:
            procs = list(self._running.values())
        for proc in procs:
            proc.terminate()
        for proc in procs:
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                proc.kill()
