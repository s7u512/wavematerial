# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""Transcribe one passage of a recording again: the editor's "Transcribe again" on a selection.

Run as `python -m wavematerial.engine.passage '<json spec>'` (never in the web server). It
decodes the source (or the playback copy, if the original has moved), finds the speech in
the selected stretch plus a little padding, and runs the same stages as a job: word
timings, text, alignment. Speakers are not re-identified; the editor keeps the turns' own.
The words that fall inside the selection are written to the spec's `out` file as JSON.
Native libraries print to stdout, so the result goes to a file, not to stdout.
"""

from __future__ import annotations

import json
import signal
import sys
from pathlib import Path

PAD = 0.6  # seconds of context on each side, so words at the edges aren't cut


def transcribe_passage(spec: dict) -> list[list]:
    from wavematerial.engine.align import align_chunk, drop_cjk
    from wavematerial.engine.decode import SAMPLE_RATE, decode
    from wavematerial.engine.playback import PLAYBACK
    from wavematerial.engine.text import GpuFailure, transcribe_chunks
    from wavematerial.engine.timings import word_timings
    from wavematerial.engine.vad import speech_chunks
    from wavematerial.models.manifest import get_model, load_manifest
    from wavematerial.preflight import Choice

    source, job_dir = Path(spec["source"]), Path(spec["job_dir"])
    audio = decode(source if source.exists() else job_dir / PLAYBACK)
    start, end = float(spec["start"]), float(spec["end"])
    lo = max(0.0, start - PAD)
    hi = min(len(audio) / SAMPLE_RATE, end + PAD)

    models, models_dir = load_manifest(), Path(spec["models_dir"])
    choice = Choice(**spec["choice"])
    vad = get_model(models, "silero-vad").file(models_dir, "silero_vad.onnx")
    piece = audio[int(lo * SAMPLE_RATE) : int(hi * SAMPLE_RATE)]
    chunks = [(a + lo, b + lo) for a, b in speech_chunks(piece, vad, choice.threads)]
    if not chunks:
        return []
    parakeet = get_model(models, "parakeet-tdt-0.6b-v3-int8").folder(models_dir)
    timed = word_timings(audio, chunks, parakeet, choice.threads)
    qwen = get_model(models, "qwen3-asr-1.7b-q8_0").file(models_dir, "Qwen3-ASR-1.7B-Q8_0.gguf")
    texts: list[str] = []

    def run(c: Choice) -> None:
        texts.clear()
        transcribe_chunks(
            audio, chunks, qwen, c, spec["key_terms"], 0, lambda i, t: texts.append(t)
        )

    try:
        run(choice)
    except GpuFailure:
        if choice.backend == "cpu":
            raise
        run(Choice("cpu", None, "processor", choice.threads, "the graphics card failed"))
    words = [w for i, c in enumerate(chunks) for w in align_chunk(drop_cjk(texts[i]), timed[i], c)]
    # Keep what lies inside the selection; the padding was only context.
    return [
        [w.text, w.start, w.end]
        for w in words
        if start <= (w.start + w.end) / 2 <= end  # a word counts if its middle is inside
    ]


def main(argv: list[str]) -> int:
    spec = json.loads(argv[0])
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    out = Path(spec["out"])
    try:
        words = transcribe_passage(spec)
    except Exception as exc:  # reported to the user; details go to stderr (the app log)
        import traceback

        traceback.print_exc()
        out.write_text(json.dumps({"error": str(exc) or type(exc).__name__}), encoding="utf-8")
        return 1
    out.write_text(json.dumps({"words": words}, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
