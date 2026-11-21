# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""The editor's playback copy: the decoded audio as mono Ogg Opus in the job folder.

The web views can't be relied on to play the original file (WebKitGTK plays only what the
user's GStreamer plugins decode), but Ogg Opus plays in base GStreamer and in WebView2.
The decode stage writes the copy; for jobs finished without one, the web app runs this
module as a subprocess: `python -m wavematerial.engine.playback SOURCE JOB_DIR`.
"""

from __future__ import annotations

import os
import signal
import sys
import tempfile
from pathlib import Path

import av
import numpy as np

from wavematerial._fsutil import replace
from wavematerial.engine.decode import SAMPLE_RATE, DecodeError, decode

PLAYBACK = "playback.opus"
BIT_RATE = 32_000
_FRAME = SAMPLE_RATE // 50  # 20 ms, an Opus frame size


def write_playback(audio: np.ndarray, job_dir: Path) -> Path:
    """Encode 16 kHz mono float32 `audio` to `job_dir/playback.opus`, atomically."""
    path = job_dir / PLAYBACK
    for stale in job_dir.glob(f".{PLAYBACK}.*.tmp"):  # left by a killed run
        stale.unlink(missing_ok=True)
    fd, tmp = tempfile.mkstemp(dir=job_dir, prefix=f".{PLAYBACK}.", suffix=".tmp")
    os.close(fd)
    try:
        pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
        with av.open(tmp, "w", format="ogg") as out:
            stream = out.add_stream("libopus", rate=SAMPLE_RATE, layout="mono")
            stream.bit_rate = BIT_RATE
            for i in range(0, len(pcm), _FRAME):
                frame = av.AudioFrame.from_ndarray(
                    pcm[i : i + _FRAME].reshape(1, -1), format="s16", layout="mono"
                )
                frame.sample_rate = SAMPLE_RATE
                frame.pts = i
                out.mux(stream.encode(frame))
            out.mux(stream.encode(None))
        replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path


def main(argv: list[str]) -> int:
    """Decode SOURCE and write JOB_DIR/playback.opus. Errors go to stderr for the user."""
    source, job_dir = Path(argv[0]), Path(argv[1])
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))  # so the temp file is removed
    try:
        write_playback(decode(source), job_dir)
    except DecodeError as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
