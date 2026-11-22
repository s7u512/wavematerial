# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""Downloads the missing models in the background, once the user asks on the setup screen."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path

from wavematerial.models import folders
from wavematerial.models.download import DownloadError, install, is_installed
from wavematerial.models.manifest import ModelSpec

log = logging.getLogger(__name__)


class _Paused(Exception):
    pass


class Installer:
    """One background download at a time. Pausing keeps the partial file for later."""

    def __init__(
        self,
        manifest: tuple[ModelSpec, ...],
        models_dir: Callable[[], Path],
        cache_dir: Path,
    ):
        self.manifest = manifest
        self.models_dir = models_dir
        self.cache_dir = cache_dir
        self.state = "idle"  # idle, downloading, paused, error, done
        self.error: str | None = None
        self._done: dict[str, int] = {}
        self._pause = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._rate_start: tuple[float, int] | None = None

    def all_installed(self) -> bool:
        return all(is_installed(m, self.models_dir()) for m in self.manifest)

    def missing(self) -> list[ModelSpec]:
        return [m for m in self.manifest if not is_installed(m, self.models_dir())]

    def downloads_dir(self) -> Path:
        return self.models_dir() / folders.DOWNLOADS

    def space(self) -> tuple[int, int]:
        """(bytes needed, bytes free) on the models folder's drive for what is missing."""
        missing = self.missing()
        done = {m.id: self.bytes_done(m) for m in missing}
        return folders.space_needed(missing, done), folders.free_space(self.models_dir())

    def started(self) -> bool:
        """Whether a download has begun (partial files exist) though not finished."""
        return any(self.bytes_done(m) for m in self.missing())

    def reset(self) -> None:
        """Back to "not started", after the models were removed."""
        if not (self._thread and self._thread.is_alive()):
            self.state, self.error = "idle", None
            with self._lock:
                self._done.clear()

    def bytes_done(self, spec: ModelSpec) -> int:
        if is_installed(spec, self.models_dir()):
            return spec.size
        with self._lock:
            if spec.id in self._done:
                return self._done[spec.id]
        part = self.downloads_dir() / f"{spec.id}.part"
        return part.stat().st_size if part.exists() else 0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._pause = False
        self.error = None
        self.state = "downloading"
        self._rate_start = (time.monotonic(), self.total_done())
        self._thread = threading.Thread(target=self._run, name="model-download", daemon=True)
        self._thread.start()

    def pause(self) -> None:
        self._pause = True

    def total_size(self) -> int:
        return sum(m.size for m in self.manifest)

    def total_done(self) -> int:
        return sum(self.bytes_done(m) for m in self.manifest)

    def seconds_left(self) -> float | None:
        """From the speed since this download session started; None until it is known."""
        if self.state != "downloading" or not self._rate_start:
            return None
        t0, b0 = self._rate_start
        elapsed, got = time.monotonic() - t0, self.total_done() - b0
        if elapsed < 3 or got <= 0:
            return None
        return (self.total_size() - self.total_done()) / (got / elapsed)

    def _run(self) -> None:
        for spec in self.manifest:  # partial downloads from before 1.1.0 lived in the cache
            (self.cache_dir / f"{spec.id}.part").unlink(missing_ok=True)
        try:
            for spec in self.manifest:
                if is_installed(spec, self.models_dir()):
                    continue

                def progress(done: int, total: int, spec: ModelSpec = spec) -> None:
                    with self._lock:
                        self._done[spec.id] = done
                    if self._pause:
                        raise _Paused

                install(spec, self.models_dir(), self.downloads_dir(), progress)
                with self._lock:
                    self._done.pop(spec.id, None)
            self.state = "done"
        except _Paused:
            self.state = "paused"
        except DownloadError as exc:
            self.error, self.state = str(exc), "error"
        except OSError as exc:
            log.exception("Model download failed")
            self.error, self.state = f"Could not save the models: {exc}", "error"
