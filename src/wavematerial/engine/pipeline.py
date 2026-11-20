# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""Run the whole pipeline for one file, saving each stage's result in the job folder.

Stages and their saved files: decode (nothing; re-decoding is cheap), VAD (`chunks.json`),
timings (`timings.json`), text (`text.jsonl`, one line per chunk), diarise
(`diarization.json`), align + merge (`artifact.json`), render (`outputs/`). A rerun skips
every stage whose file exists, and the text stage resumes at the first missing chunk, so a
crash loses at most one chunk of work. Only one model is loaded at a time.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from wavematerial import __version__
from wavematerial._fsutil import write_text_atomic
from wavematerial.engine.align import AlignStats, align_chunk
from wavematerial.engine.decode import SAMPLE_RATE, decode
from wavematerial.engine.diarize import diarize
from wavematerial.engine.merge import SpeakerSegment, merge
from wavematerial.engine.text import transcribe_chunks
from wavematerial.engine.timings import word_timings
from wavematerial.engine.vad import speech_chunks
from wavematerial.models.manifest import ModelSpec, get_model
from wavematerial.preflight import Choice
from wavematerial.transcript.render import write_outputs
from wavematerial.transcript.schema import Transcript, Word
from wavematerial.transcript.store import ARTIFACT, read_current, write_artifact

STAGES = ("decode", "vad", "timings", "text", "diarize", "merge", "render")
CHUNKS, TIMINGS, TEXT, DIARIZATION = "chunks.json", "timings.json", "text.jsonl", "diarization.json"

log = logging.getLogger(__name__)

# Called with (stage name, fraction of that stage done, 0..1).
Progress = Callable[[str, float], None]


@dataclass(frozen=True)
class JobSettings:
    min_speakers: int = 2
    max_speakers: int = 3
    key_terms: tuple[str, ...] = ()


def _save_json(path: Path, data: Any) -> None:
    write_text_atomic(path, json.dumps(data, ensure_ascii=False) + "\n")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_texts(path: Path) -> list[str]:
    """The chunk texts saved so far. A torn last line (from a crash) is dropped."""
    texts: list[str] = []
    if not path.exists():
        return texts
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            break
        if entry.get("i") != len(texts):
            break
        texts.append(entry["text"])
    write_text_atomic(
        path, "".join(json.dumps({"i": i, "text": t}) + "\n" for i, t in enumerate(texts))
    )
    return texts


def _model_path(models: tuple[ModelSpec, ...], models_dir: Path, model_id: str, file: str) -> Path:
    return get_model(models, model_id).file(models_dir, file)


def run(
    source: Path,
    job_dir: Path,
    *,
    choice: Choice,
    models: tuple[ModelSpec, ...],
    models_dir: Path,
    settings: JobSettings = JobSettings(),
    progress: Progress | None = None,
) -> Transcript:
    """Transcribe `source` into `job_dir`. Raises `GpuFailure` if the GPU fails on the way."""
    job_dir.mkdir(parents=True, exist_ok=True)

    def report(stage: str, fraction: float) -> None:
        if progress:
            progress(stage, fraction)

    if (job_dir / ARTIFACT).exists():
        report("render", 0.0)
        transcript = read_current(job_dir)
        write_outputs(job_dir, transcript)
        report("render", 1.0)
        return transcript

    report("decode", 0.0)
    audio = decode(source)
    duration = len(audio) / SAMPLE_RATE
    report("decode", 1.0)

    if (job_dir / CHUNKS).exists():
        chunks = [tuple(c) for c in _load_json(job_dir / CHUNKS)]
    else:
        report("vad", 0.0)
        vad_model = _model_path(models, models_dir, "silero-vad", "silero_vad.onnx")
        chunks = speech_chunks(audio, vad_model, choice.threads)
        _save_json(job_dir / CHUNKS, chunks)
    report("vad", 1.0)
    n = len(chunks)

    if (job_dir / TIMINGS).exists():
        timed = [[Word(*w) for w in ws] for ws in _load_json(job_dir / TIMINGS)]
    else:
        parakeet = get_model(models, "parakeet-tdt-0.6b-v3-int8").folder(models_dir)
        timed = word_timings(
            audio, chunks, parakeet, choice.threads, lambda i: report("timings", (i + 1) / n)
        )
        _save_json(job_dir / TIMINGS, [[[w.text, w.start, w.end] for w in ws] for ws in timed])
    report("timings", 1.0)

    texts = _read_texts(job_dir / TEXT)
    if len(texts) < n:
        report("text", len(texts) / n)
        qwen = _model_path(models, models_dir, "qwen3-asr-1.7b-q8_0", "Qwen3-ASR-1.7B-Q8_0.gguf")
        with (job_dir / TEXT).open("a", encoding="utf-8") as f:

            def save_text(i: int, text: str) -> None:
                f.write(json.dumps({"i": i, "text": text}) + "\n")
                f.flush()
                texts.append(text)
                report("text", (i + 1) / n)

            transcribe_chunks(
                audio, chunks, qwen, choice, settings.key_terms, len(texts), save_text
            )
    report("text", 1.0)

    if (job_dir / DIARIZATION).exists():
        segments = [SpeakerSegment(*s) for s in _load_json(job_dir / DIARIZATION)]
    else:
        report("diarize", 0.0)
        segments = diarize(
            audio,
            _model_path(models, models_dir, "pyannote-segmentation-3.0", "model.onnx"),
            _model_path(models, models_dir, "titanet-small", "nemo_en_titanet_small.onnx"),
            settings.min_speakers,
            settings.max_speakers,
            choice.threads,
        )
        _save_json(job_dir / DIARIZATION, [[s.start, s.end, s.speaker] for s in segments])
    report("diarize", 1.0)
    del audio

    report("merge", 0.0)
    stats = AlignStats()
    words = [w for i in range(n) for w in align_chunk(texts[i], timed[i], chunks[i], stats)]
    speakers, turns = merge(words, segments)
    log.info("Alignment: %s", asdict(stats))
    transcript = Transcript(
        language="en",
        duration=round(duration, 3),
        speakers=speakers,
        turns=turns,
        engine={
            "app": f"wavematerial {__version__}",
            "text": "Qwen3-ASR-1.7B Q8_0 (transcribe.cpp)",
            "timings": "Parakeet TDT 0.6B v3 int8 (sherpa-onnx)",
            "diarization": "pyannote segmentation 3.0 + TitaNet small (sherpa-onnx)",
            "device": f"{choice.backend}: {choice.description}",
            "threads": str(choice.threads),
            "alignment": json.dumps(asdict(stats)),
        },
    )
    write_artifact(job_dir, transcript)
    report("merge", 1.0)

    report("render", 0.0)
    write_outputs(job_dir, transcript)
    report("render", 1.0)
    return transcript
