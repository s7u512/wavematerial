# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""A fake engine for tests: same stage files and progress as the real one, no models.

The worker uses it when `WAVEMATERIAL_FAKE_ENGINE` is set to a JSON object of options:
- `"sleep"`: seconds to wait in each stage (default 0);
- `"gpu_fails_at"`: a stage name; on a "vulkan" device it raises GpuFailure there.
Each stage that actually runs is appended to `fake-stages.log` in the job folder, so tests
can see which saved stages were skipped on resume.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from wavematerial.engine.text import GpuFailure
from wavematerial.preflight import Choice
from wavematerial.transcript.render import write_outputs
from wavematerial.transcript.schema import Transcript, Turn, Word
from wavematerial.transcript.store import ARTIFACT, read_current, write_artifact

ENV = "WAVEMATERIAL_FAKE_ENGINE"
_FILES = {
    "vad": "chunks.json",
    "timings": "timings.json",
    "text": "text.jsonl",
    "diarize": "diarization.json",
}


def options() -> dict | None:
    raw = os.environ.get(ENV)
    return json.loads(raw) if raw else None


def run(source: Path, job_dir: Path, *, choice: Choice, progress=None, **_) -> Transcript:
    opts = options() or {}
    job_dir.mkdir(parents=True, exist_ok=True)
    if not source.exists():
        raise FileNotFoundError(source)

    def stage(name: str) -> None:
        if opts.get("gpu_fails_at") == name and choice.backend == "vulkan":
            raise GpuFailure("simulated GPU failure")
        with (job_dir / "fake-stages.log").open("a", encoding="utf-8") as f:
            f.write(f"{name}\n")
        for i in range(4):
            time.sleep(opts.get("sleep", 0) / 4)
            if progress:
                progress(name, (i + 1) / 4)

    if (job_dir / ARTIFACT).exists():
        transcript = read_current(job_dir)
    else:
        stage("decode")
        for name, file in _FILES.items():
            if not (job_dir / file).exists():
                stage(name)
                (job_dir / file).write_text("[]\n", encoding="utf-8")
        stage("merge")
        transcript = Transcript(
            language="en",
            duration=10.0,
            speakers=("SPEAKER_00",),
            turns=(Turn("SPEAKER_00", (Word("Contact", 1.0, 1.5), Word("light.", 1.5, 2.0))),),
            engine={"device": f"{choice.backend}: {choice.description}", "fake": "yes"},
        )
        write_artifact(job_dir, transcript)
    stage("render")
    write_outputs(job_dir, transcript)
    return transcript
