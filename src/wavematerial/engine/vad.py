# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""Stage 2: split the audio into speech chunks of at most about 20 s (Silero VAD)."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from wavematerial.engine.decode import SAMPLE_RATE

MAX_CHUNK_SECONDS = 20.0
MIN_SILENCE_SECONDS = 0.4  # a pause this long ends a chunk (Silero's default is 0.5)
PAD_SECONDS = 0.2  # widen each chunk by up to this much, but only into silence


def pad_chunks(
    chunks: list[tuple[float, float]], duration: float, pad: float = PAD_SECONDS
) -> list[tuple[float, float]]:
    """Widen each chunk into the silence around it, never past halfway to its neighbours.

    Silero marks speech a little late, which clips the first sounds of a chunk; the padding
    gives the recognisers those sounds back without overlapping the next chunk.
    """
    out = []
    for i, (start, end) in enumerate(chunks):
        lo = (chunks[i - 1][1] + start) / 2 if i > 0 else 0.0
        hi = (end + chunks[i + 1][0]) / 2 if i + 1 < len(chunks) else duration
        out.append((round(max(start - pad, lo), 3), round(min(end + pad, hi), 3)))
    return out


def speech_chunks(audio: np.ndarray, model: Path, threads: int) -> list[tuple[float, float]]:
    """Padded speech chunks, in seconds."""
    import sherpa_onnx

    config = sherpa_onnx.VadModelConfig()
    config.silero_vad.model = str(model)
    config.silero_vad.max_speech_duration = MAX_CHUNK_SECONDS
    config.silero_vad.min_silence_duration = MIN_SILENCE_SECONDS
    config.sample_rate = SAMPLE_RATE
    config.num_threads = threads
    duration = len(audio) / SAMPLE_RATE
    vad = sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=duration + 1)
    window = config.silero_vad.window_size
    for i in range(0, len(audio), window):
        vad.accept_waveform(audio[i : i + window])
    vad.flush()
    chunks = []
    while not vad.empty():
        seg = vad.front
        chunks.append((seg.start / SAMPLE_RATE, (seg.start + len(seg.samples)) / SAMPLE_RATE))
        vad.pop()
    return pad_chunks(chunks, duration)


def slice_chunk(audio: np.ndarray, chunk: tuple[float, float]) -> np.ndarray:
    return audio[int(chunk[0] * SAMPLE_RATE) : int(chunk[1] * SAMPLE_RATE)]
