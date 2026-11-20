# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""The scheduler: runs queued jobs one at a time, each in its own worker subprocess."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

from wavematerial.config import Paths, Settings
from wavematerial.jobs.events import StageClock, log_event
from wavematerial.jobs.store import Job, JobStore, fingerprint
from wavematerial.preflight import Choice, Device, choose

log = logging.getLogger(__name__)

WORKER = [sys.executable, "-m", "wavematerial.jobs.worker"]


class Scheduler:
    """Owns the queue. Thread-safe: the UI calls the control methods from any thread."""

    def __init__(
        self,
        store: JobStore,
        paths: Paths,
        settings: Callable[[], Settings],
        devices: list[Device],
        cores: int,
        *,
        wsl: bool = False,
    ):
        self.store = store
        self.paths = paths
        self.settings = settings
        self.devices = devices
        self.cores = cores
        self.wsl = wsl
        self.paused = False
        self._wake = threading.Condition()
        self._quit = False
        self._proc: subprocess.Popen | None = None
        self._current: int | None = None
        self._stop_requested = False
        self._thread: threading.Thread | None = None

    # ---- lifecycle -------------------------------------------------------------------

    def start(self) -> None:
        for job_id in self.store.recover():
            log.info("Job %s was interrupted; it will resume from its last saved stage", job_id)
        self._thread = threading.Thread(target=self._loop, name="scheduler", daemon=True)
        self._thread.start()

    def shutdown(self, timeout: float = 10) -> None:
        """Stop the worker (its job goes back to the queue) and end the loop."""
        with self._wake:
            self._quit = True
            self._wake.notify_all()
        self._kill_worker()
        if self._thread:
            self._thread.join(timeout)

    def job_dir(self, job_id: int) -> Path:
        return self.paths.jobs_dir / str(job_id)

    # ---- controls ----------------------------------------------------------------------

    def add(self, source: Path, *, min_speakers: int, max_speakers: int, key_terms=()) -> Job:
        job = self.store.add(
            source,
            min_speakers=min_speakers,
            max_speakers=max_speakers,
            key_terms=key_terms,
            duration=_probe_duration(source),
        )
        log_event(self.job_dir(job.id), "queued")
        self._notify()
        return job

    def pause(self) -> None:
        """Stop the queue after the current job."""
        self.paused = True

    def resume_queue(self) -> None:
        self.paused = False
        self._notify()

    def stop(self, job_id: int) -> None:
        """Kill the running job. It is marked cancelled and keeps its saved stages."""
        if self._current == job_id:
            self._stop_requested = True
            self._kill_worker()

    def resume(self, job_id: int) -> None:
        """Queue a cancelled or failed job again; it continues from its last saved stage."""
        if self.store.get(job_id).state in ("cancelled", "failed"):
            self.store.set_state(job_id, "queued", error=None)
            log_event(self.job_dir(job_id), "queued again")
            self._notify()

    retry = resume

    def remove(self, job_id: int) -> None:
        """Delete a job that is not running: its row and its folder."""
        if self._current == job_id:
            raise RuntimeError("stop the job before deleting it")
        self.store.delete(job_id)
        shutil.rmtree(self.job_dir(job_id), ignore_errors=True)

    def move(self, job_id: int, before: int | None) -> None:
        self.store.move(job_id, before)

    # ---- the loop ------------------------------------------------------------------------

    def _notify(self) -> None:
        with self._wake:
            self._wake.notify_all()

    def _loop(self) -> None:
        while True:
            with self._wake:
                while not self._quit and (self.paused or self.store.next_queued() is None):
                    self._wake.wait(timeout=1)
                if self._quit:
                    return
            job = self.store.next_queued()
            if job:
                try:
                    self._run(job)
                except Exception:
                    log.exception("Job %s failed unexpectedly", job.id)
                    self.store.set_state(job.id, "failed", error="An unexpected error occurred.")

    def _choice(self) -> Choice:
        return choose(
            self.devices,
            self.settings(),
            cores=self.cores,
            wsl=self.wsl,
            unreliable=self.store.unreliable_gpus(),
        )

    def _run(self, job: Job) -> None:
        if not job.source.exists():
            self.store.set_state(
                job.id, "failed", error=f"The file {job.source} is missing or was moved."
            )
            return
        if fingerprint(job.source) != job.fingerprint:
            self.store.set_state(
                job.id,
                "failed",
                error=f"The file {job.source} has changed since it was added. Add it again.",
            )
            return
        while True:  # loops once more only to rerun on the CPU after a GPU failure
            choice = self._choice()
            outcome = self._run_worker(job, choice)
            if outcome == "gpu" and choice.backend == "vulkan" and choice.device_id:
                log.warning(
                    "GPU %s failed on job %s; rerunning on the CPU", choice.device_id, job.id
                )
                self.store.mark_gpu_unreliable(choice.device_id, f"failed on job {job.id}")
                log_event(self.job_dir(job.id), "the GPU failed; continuing on the processor")
                continue
            return

    def _run_worker(self, job: Job, choice: Choice) -> str:
        job_dir = self.job_dir(job.id)
        job_dir.mkdir(parents=True, exist_ok=True)
        settings = self.settings()
        spec = {
            "source": str(job.source),
            "job_dir": str(job_dir),
            "models_dir": str(self.paths.models_dir(settings)),
            "choice": asdict(choice),
            "settings": {
                "min_speakers": job.min_speakers,
                "max_speakers": job.max_speakers,
                "key_terms": list(job.key_terms),
            },
        }
        self._stop_requested = False
        self._current = job.id
        self.store.set_state(
            job.id,
            "running",
            stage=None,
            stage_fraction=0.0,
            error=None,
            device=f"{choice.description} ({choice.backend})",
        )
        log_event(job_dir, f"started on {choice.description} ({choice.backend})")
        clock = StageClock(job_dir)
        result: dict = {}
        with (job_dir / "worker.log").open("ab") as log_file:
            self._proc = subprocess.Popen(
                [*WORKER, json.dumps(spec)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=log_file,
                text=True,
                encoding="utf-8",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            assert self._proc.stdout is not None
            for line in self._proc.stdout:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("event") == "progress":
                    fraction = float(event["fraction"])
                    self.store.update(job.id, stage=event["stage"], stage_fraction=fraction)
                    clock.progress(event["stage"], fraction)
                else:
                    result = event
            code = self._proc.wait()
        self._proc = None
        self._current = None

        if self._quit:
            self.store.set_state(job.id, "queued")  # app closing: resume next launch
            log_event(job_dir, "interrupted by closing the app")
            return "quit"
        if self._stop_requested:
            self.store.set_state(job.id, "cancelled", error=None)
            log_event(job_dir, "stopped")
            return "stopped"
        if result.get("event") == "done":
            self.store.set_state(
                job.id,
                "done",
                duration=result["duration"],
                speakers=result["speakers"],
                stage="render",
                stage_fraction=1.0,
            )
            log_event(job_dir, "done")
            return "done"
        if result.get("kind") == "gpu":
            return "gpu"
        error = result.get("message") or _death(code)
        self.store.set_state(job.id, "failed", error=error)
        log_event(job_dir, f"failed: {error}")
        return "failed"

    def _kill_worker(self) -> None:
        proc = self._proc
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                proc.kill()


def _probe_duration(source: Path) -> float | None:
    """The file's length from its header, without decoding (None if unknown)."""
    try:
        import av

        with av.open(str(source)) as container:
            return container.duration / 1_000_000 if container.duration else None
    except Exception:
        return None


def _death(code: int) -> str:
    """A plain explanation for a worker that died without saying why."""
    if code in (-9, 137):
        return (
            "The transcription was killed, most likely because the computer ran out of "
            "memory. Close other programs and retry."
        )
    return f"The transcription stopped unexpectedly (exit code {code}). Retry, or see the log."
