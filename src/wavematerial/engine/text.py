# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""Stage 4: the text, from Qwen3-ASR through transcribe.cpp, one chunk at a time."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

import numpy as np

from wavematerial.engine.vad import slice_chunk
from wavematerial.preflight import Choice


class GpuFailure(Exception):
    """The GPU failed (backend error or out of memory). The job should rerun on the CPU."""


@contextmanager
def _gpu_errors(on_gpu: bool) -> Iterator[None]:
    import transcribe_cpp as tc

    try:
        yield
    except (tc.BackendError, tc.OutOfMemory, tc.ModelLoadError) as exc:
        if on_gpu:
            raise GpuFailure(str(exc)) from exc
        raise


def _device(choice: Choice):
    import transcribe_cpp as tc

    if choice.backend == "cpu":
        return "cpu", None
    for d in tc.backends():
        if d.kind == "vulkan" and d.device_id == choice.device_id:
            return "vulkan", d
    raise GpuFailure(f"the GPU {choice.description} is no longer available")


def transcribe_chunks(
    audio: np.ndarray,
    chunks: Sequence[tuple[float, float]],
    model_path: Path,
    choice: Choice,
    key_terms: Sequence[str],
    start_at: int,
    on_text: Callable[[int, str], None],
) -> None:
    """Call `on_text(i, text)` for each chunk from `start_at` on, as soon as it is done."""
    import transcribe_cpp as tc

    if start_at >= len(chunks):
        return
    on_gpu = choice.backend == "vulkan"
    backend, device = _device(choice)
    with _gpu_errors(on_gpu):
        model = tc.Model(str(model_path), backend=backend, device=device)
        session = model.session(n_threads=choice.threads)
        for i in range(start_at, len(chunks)):
            result = session.run(
                slice_chunk(audio, chunks[i]),
                language="en",
                timestamps="none",
                vocabulary=list(key_terms) or None,
            )
            on_text(i, result.text.strip())
