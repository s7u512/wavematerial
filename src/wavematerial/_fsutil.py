# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""Crash-safe file writes."""

import contextlib
import os
import tempfile
from pathlib import Path


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
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


def write_text_once(path: Path, text: str) -> None:
    """Like `write_text_atomic`, but refuse to replace a file that already exists."""
    if path.exists():
        raise FileExistsError(f"{path} already exists and must not be overwritten")
    write_text_atomic(path, text)
