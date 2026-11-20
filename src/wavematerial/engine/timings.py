# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""Stage 3: word timings from Parakeet TDT (sherpa-onnx). Its text is used only for alignment."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

import numpy as np

from wavematerial.engine.decode import SAMPLE_RATE
from wavematerial.engine.vad import slice_chunk
from wavematerial.transcript.schema import Word


def tokens_to_words(
    tokens: Sequence[str], starts: Sequence[float], durations: Sequence[float], offset: float
) -> list[Word]:
    """Group sub-word tokens into timed words.

    A token starting with a space begins a new word; a bare space token marks a boundary
    (Parakeet emits one before digits); punctuation joins the word before it.
    """
    words: list[list] = []
    boundary = True
    for tok, start, dur in zip(tokens, starts, durations, strict=True):
        if tok == " ":
            boundary = True
            continue
        text = tok.strip()
        if not text:
            continue
        punctuation_only = not any(ch.isalnum() for ch in text)
        if words and punctuation_only:
            words[-1][0] += text
            words[-1][2] = start + dur
        elif boundary or tok.startswith(" ") or not words:
            words.append([text, start, start + dur])
        else:
            words[-1][0] += text
            words[-1][2] = start + dur
        boundary = False
    return [Word(t, round(offset + s, 3), round(offset + e, 3)) for t, s, e in words]


def word_timings(
    audio: np.ndarray,
    chunks: Sequence[tuple[float, float]],
    model_dir: Path,
    threads: int,
    on_chunk: Callable[[int], None] | None = None,
) -> list[list[Word]]:
    """Parakeet's timed words for every chunk."""
    import sherpa_onnx

    recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=str(model_dir / "encoder.int8.onnx"),
        decoder=str(model_dir / "decoder.int8.onnx"),
        joiner=str(model_dir / "joiner.int8.onnx"),
        tokens=str(model_dir / "tokens.txt"),
        num_threads=threads,
        model_type="nemo_transducer",
    )
    out = []
    for i, chunk in enumerate(chunks):
        stream = recognizer.create_stream()
        stream.accept_waveform(SAMPLE_RATE, slice_chunk(audio, chunk))
        recognizer.decode_stream(stream)
        r = stream.result
        out.append(tokens_to_words(r.tokens, r.timestamps, r.durations, chunk[0]))
        if on_chunk:
            on_chunk(i)
    return out
