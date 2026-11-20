# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""Stage 1: decode any audio or video file to 16 kHz mono float32, in memory.

Uses PyAV and the FFmpeg bundled in its wheel; no system ffmpeg and no temporary WAV.
"""

from __future__ import annotations

from pathlib import Path

import av
import numpy as np

SAMPLE_RATE = 16_000


class DecodeError(Exception):
    """The file can't be decoded. The message is shown to the user."""


def decode(path: Path) -> np.ndarray:
    """The file's first audio stream as a 1-D float32 array at 16 kHz."""
    try:
        with av.open(str(path)) as container:
            stream = next((s for s in container.streams if s.type == "audio"), None)
            if stream is None:
                raise DecodeError(f"{path.name} has no audio track.")
            resampler = av.AudioResampler(format="flt", layout="mono", rate=SAMPLE_RATE)
            parts = []
            for frame in container.decode(stream):
                parts.extend(f.to_ndarray().reshape(-1) for f in resampler.resample(frame))
            parts.extend(f.to_ndarray().reshape(-1) for f in resampler.resample(None))
    except FileNotFoundError:
        raise DecodeError(f"{path} no longer exists.") from None
    except av.FFmpegError as exc:
        raise DecodeError(f"{path.name} could not be read as audio or video ({exc}).") from exc
    if not parts:
        raise DecodeError(f"{path.name} contains no audio.")
    return np.concatenate(parts).astype(np.float32, copy=False)
