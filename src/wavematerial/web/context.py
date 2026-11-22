# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""Everything the web layer needs, gathered in one object created at startup."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from wavematerial.config import Paths, Settings, load_settings, save_settings
from wavematerial.jobs.passage import Passages
from wavematerial.jobs.playback import PlaybackCopies
from wavematerial.jobs.scheduler import Scheduler
from wavematerial.jobs.store import JobStore
from wavematerial.models.installer import Installer
from wavematerial.models.manifest import ModelSpec
from wavematerial.preflight import Device
from wavematerial.updater import Updater
from wavematerial.updates import UpdateChecker


@dataclass
class NativeHooks:
    """Things only the app window can do. All None in the browser fallback."""

    pick_files: Callable[[], list[str]] | None = None
    pick_folder: Callable[[], str | None] | None = None
    toggle_fullscreen: Callable[[], bool] | None = None  # returns True if now fullscreen
    # (suggested file name, folder to start in) -> the chosen path, or None if cancelled
    save_file: Callable[[str, str], str | None] | None = None
    close: Callable[[], None] | None = None  # close the window (the app then shuts down)


@dataclass
class AppContext:
    paths: Paths
    store: JobStore
    scheduler: Scheduler
    installer: Installer
    updates: UpdateChecker
    manifest: tuple[ModelSpec, ...]
    devices: list[Device]
    cores: int
    wsl: bool
    token: str
    native: NativeHooks = field(default_factory=NativeHooks)
    updater: Updater | None = None  # None: this copy can't update itself (see update_why)
    update_why: str = ""
    port: int = 0
    fullscreen: bool = False
    playback: PlaybackCopies = field(default_factory=PlaybackCopies)
    passages: Passages = field(default_factory=Passages)
    # Browser mode (no window): Quit sets `quit`; any request from a page updates `last_seen`.
    quit: threading.Event = field(default_factory=threading.Event)
    last_seen: float = field(default_factory=time.monotonic)
    _settings_lock: threading.Lock = field(default_factory=threading.Lock)

    def settings(self) -> Settings:
        with self._settings_lock:
            return load_settings(self.paths.settings_file)

    def save_settings(self, settings: Settings) -> None:
        with self._settings_lock:
            save_settings(self.paths.settings_file, settings)

    def models_dir(self) -> Path:
        return self.paths.models_dir(self.settings())

    @property
    def windowed(self) -> bool:
        return self.native.pick_files is not None


def open_path(path: Path) -> None:
    """Show a file or folder in the system's file manager or default app."""
    if sys.platform == "win32":
        os.startfile(path)
    else:
        subprocess.Popen(["xdg-open", str(path)], start_new_session=True)
