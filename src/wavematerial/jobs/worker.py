# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""The worker subprocess: runs one job's pipeline and reports on a private pipe.

Started as `python -m wavematerial.jobs.worker '<json spec>'`. It reports with one JSON
object per line on its original stdout:
    {"event": "progress", "stage": "text", "fraction": 0.4}
    {"event": "done", "duration": 300.0, "speakers": 2, "turns": 9}
    {"event": "error", "kind": "gpu" | "decode" | "source" | "memory" | "other", "message": ...}
Native libraries print to stdout too, so the worker first points file descriptor 1 at
stderr (the job's log) and keeps a private copy of the original for these messages.

The worker exits as soon as its stdin closes: if the app dies, its worker dies with it.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import traceback
from pathlib import Path

from wavematerial.preflight import Choice


def _exit_when_parent_goes() -> None:
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
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    _exit_when_parent_goes()

    def emit(**event) -> None:
        channel.write(json.dumps(event) + "\n")

    spec = json.loads(argv[0])
    choice = Choice(**spec["choice"])
    source, job_dir = Path(spec["source"]), Path(spec["job_dir"])

    from wavematerial.engine import fake
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
