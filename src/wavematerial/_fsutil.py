# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""Crash-safe file writes."""

import contextlib
import os
import sys
import tempfile
import time
from pathlib import Path


def replace(src: Path | str, dst: Path | str) -> None:
    """`os.replace`, retried for a moment on Windows.

    There, renaming over a file (or folder) that another process briefly has open, such as
    an antivirus scan or the search indexer, fails with `PermissionError`.
    """
    delay = 0.05
    for attempt in range(6):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if sys.platform != "win32" or attempt == 5:
                raise
            time.sleep(delay)
            delay *= 2


def write_text_atomic(path: Path, text: str) -> None:
    """Write `text` to `path` so a crash leaves either the old file or the new one, never half.

    The text is written to a temporary file in the same folder, flushed to disk, and then
    renamed over `path`. Line endings are always LF.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


def write_text_once(path: Path, text: str) -> None:
    """Like `write_text_atomic`, but refuse to replace a file that already exists."""
    if path.exists():
        raise FileExistsError(f"{path} already exists and must not be overwritten")
    write_text_atomic(path, text)
