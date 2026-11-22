# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""The worker subprocess: runs one job's pipeline and reports on a private pipe.

Started as `python -m wavematerial.jobs.worker '<json spec>'`. It reports with one JSON
object per line on its original stdout:
    {"event": "progress", "stage": "text", "fraction": 0.4}
    {"event": "warning", "message": "..."}  (shown in the job's log; the job goes on)
    {"event": "done", "duration": 300.0, "speakers": 2, "turns": 9}
    {"event": "error", "kind": "gpu" | "decode" | "source" | "memory" | "runtime" | "other",
     "message": ...}
Native libraries print to stdout too, so the worker first points file descriptor 1 at
stderr (the job's log) and keeps a private copy of the original for these messages.

The worker exits as soon as the app does (its stdin closes, or on Windows its parent exits):
if the app dies, its worker dies with it.
"""

from __future__ import annotations

import faulthandler
import json
import logging
import os
import sys
import threading
import traceback
from pathlib import Path

from wavematerial.preflight import Choice


def _exit_when_parent_goes(parent_pid: int | None) -> None:
    """Exit as soon as the app does, so a crashed app never leaves a worker running.

    On Linux the worker waits for its stdin to close. On Windows it waits on the parent
    process instead: there, a thread blocked reading a pipe makes other calls on that
    handle wait, and loading a DLL checks the standard handles, so the worker froze at its
    first native import (numpy) under the stdin watch.
    """
    if sys.platform == "win32":
        import psutil

        try:  # the app passes its pid (os.getppid() needs a newer API than some systems have)
            parent = psutil.Process(parent_pid or os.getppid())
        except psutil.Error:
            os._exit(3)

        def watch() -> None:
            try:
                parent.wait()
            except psutil.Error:
                pass
            finally:
                os._exit(3)

    else:

        def watch() -> None:
            try:
                while sys.stdin.buffer.read(4096):
                    pass
            finally:
                os._exit(3)

    threading.Thread(target=watch, daemon=True).start()


def main(argv: list[str]) -> int:
    channel = os.fdopen(os.dup(1), "w", buffering=1, encoding="utf-8")
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    faulthandler.enable()  # a crash in native code leaves a Python traceback in the log
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    def emit(**event) -> None:
        channel.write(json.dumps(event) + "\n")

    spec = json.loads(argv[0])
    _exit_when_parent_goes(spec.get("parent_pid"))
    choice = Choice(**spec["choice"])
    source, job_dir = Path(spec["source"]), Path(spec["job_dir"])

    from wavematerial.engine import fake, onnxruntime_check
    from wavematerial.engine.decode import DecodeError
    from wavematerial.engine.pipeline import JobSettings
    from wavematerial.engine.text import GpuFailure

    if fake.options() is not None:
        run, models = fake.run, ()
    else:
        from wavematerial.engine.pipeline import run
        from wavematerial.models.manifest import load_manifest

        models = load_manifest()
    try:
        if fake.options() is None:
            notice = onnxruntime_check.check()
        else:  # tests: "old" or "new", as if Windows' copy were in use
            notice = fake.onnxruntime_notice()
    except onnxruntime_check.OnnxRuntimeMismatch as exc:
        logging.error("%s", exc.detail)
        emit(event="error", kind="runtime", message=str(exc))
        return 1
    if notice:
        logging.warning("%s", notice.detail)
        emit(event="warning", message=notice.text)
    try:
        transcript = run(
            source,
            job_dir,
            choice=choice,
            models=models,
            models_dir=Path(spec["models_dir"]),
            settings=JobSettings(**spec["settings"]),
            progress=lambda stage, fraction: emit(event="progress", stage=stage, fraction=fraction),
        )
    except GpuFailure as exc:
        emit(event="error", kind="gpu", message=str(exc))
        return 2
    except DecodeError as exc:
        emit(event="error", kind="decode", message=str(exc))
        return 1
    except FileNotFoundError as exc:
        emit(event="error", kind="source", message=f"A file is missing: {exc.filename or exc}")
        return 1
    except MemoryError:
        emit(event="error", kind="memory", message="The computer ran out of memory.")
        return 1
    except Exception as exc:
        traceback.print_exc()
        emit(event="error", kind="other", message=f"{type(exc).__name__}: {exc}")
        return 1
    emit(
        event="done",
        duration=transcript.duration,
        speakers=len(transcript.speakers),
        turns=len(transcript.turns),
    )
    return 0


if __name__ == "__main__":
    code = main(sys.argv[1:])
    sys.stderr.flush()
    os._exit(code)  # don't wait on the stdin watcher
