# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""Self-update and Manual update: download the new release, check it, and hand it over.

Only the Windows installer and the Linux .tar.gz can do this; running from source only gets
the notice. The file comes from the project's GitHub releases over HTTPS and must match the
release's SHA256SUMS (which catches a damaged download; it is not a signature). Nothing that
closes the app starts while a transcription runs: the app waits for the queue to be free,
holds it, and quits; `apply()` then runs after the app has shut down.

- Windows Self-update: the installer runs with /SILENT /UPDATE=1; it waits for this process
  to exit, installs over the old version, and starts the app again (see wavematerial.iss).
- Windows Manual update: the installer opens normally (/WAIT=1: it first waits for the app
  to exit); the user goes through its steps.
- Linux Self-update: the new folder is unpacked beside the old one, then swapped in by
  rename after the app has quit; the old folder is kept as `<folder>.previous` until the
  next update; the app restarts.
- Linux Manual update: the checked .tar.gz is saved in the Downloads folder (never over an
  existing file); the app keeps running.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
import sys
import tarfile
import threading
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import platformdirs

from wavematerial.models.download import USER_AGENT, DownloadError, _fetch
from wavematerial.updates import download_prefix

log = logging.getLogger(__name__)

SUMS = "SHA256SUMS"


@dataclass(frozen=True)
class Install:
    kind: str  # "windows" or "tarball"
    root: Path  # the folder that holds BUILD-INFO.txt

    def asset(self, version: str) -> str:
        if self.kind == "windows":
            return f"WaveMaterial-{version}-windows-x86_64-setup.exe"
        return f"wavematerial-{version}-linux-x86_64.tar.gz"


def current_install(executable: str = sys.executable) -> tuple[Install | None, str]:
    """How this copy was installed, or None and why it can't update itself."""
    exe = Path(executable).resolve()
    if sys.platform == "win32":
        app = exe.parent.parent  # <app>\python\pythonw.exe
        if (app / "BUILD-INFO.txt").exists() and (app / "unins000.exe").exists():
            return Install("windows", app), ""
    elif sys.platform == "linux" and len(exe.parents) > 2:
        root = exe.parents[2]  # <root>/python/bin/python3.12
        if (root / "BUILD-INFO.txt").exists() and (root / "bin" / "wavematerial").exists():
            if os.access(root, os.W_OK) and os.access(root.parent, os.W_OK):
                return Install("tarball", root), ""
            return None, f"WaveMaterial can't write to {root.parent}, so it can't update itself."
    return None, "This copy runs from source; update it with git."


def parse_sums(text: str) -> dict[str, str]:
    """`<sha256>  <name>` lines, as sha256sum writes them."""
    sums = {}
    for line in text.splitlines():
        digest, _, name = line.strip().partition("  ")
        if len(digest) == 64 and name:
            sums[name.lstrip("*")] = digest.lower()
    return sums


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(1 << 20):
            h.update(block)
    return h.hexdigest()


def unpack(archive: Path, top: str, dest: Path) -> Path:
    """Unpack the release's single top folder `top` into `dest`; return the unpacked folder."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    with tarfile.open(archive, "r:gz") as tf:
        names = tf.getnames()
        if not names or any(n != top and not n.startswith(f"{top}/") for n in names):
            raise DownloadError(f"The update has an unexpected layout (expected {top}/).")
        tf.extractall(dest, filter="data")
    folder = dest / top
    if not (folder / "bin" / "wavematerial").exists():
        raise DownloadError("The update has no bin/wavematerial.")
    return folder


def unique_path(path: Path) -> Path:
    """`path`, or `name (2).ext`, `name (3).ext`, ... if it is taken."""
    if not path.exists():
        return path
    stem, suffix = path.name, ""
    for ext in (".tar.gz", ".exe"):
        if stem.endswith(ext):
            stem, suffix = stem[: -len(ext)], ext
    n = 2
    while (path.with_name(f"{stem} ({n}){suffix}")).exists():
        n += 1
    return path.with_name(f"{stem} ({n}){suffix}")


def _downloads() -> Path:
    return Path(platformdirs.user_downloads_dir())


def swap(root: Path, new: Path) -> Path:
    """Put `new` in place of `root`, keeping the old folder as `<root>.previous`."""
    previous = root.with_name(root.name + ".previous")
    if previous.exists():
        shutil.rmtree(previous)
    root.rename(previous)
    try:
        new.rename(root)
    except OSError:
        previous.rename(root)
        raise
    return previous


class Updater:
    """Downloads one update in the background; `apply()` installs it after shutdown."""

    def __init__(
        self,
        cache_dir: Path,
        install: Install | None,
        downloads: Callable[[], Path] = _downloads,
    ):
        self.dir = cache_dir / "update"
        self.install = install
        self.downloads = downloads
        self.mode = "self"  # "self" or "manual"
        self.saved: Path | None = None  # Linux Manual update: where the file was saved
        # idle, downloading, waiting (for the queue), ready (to apply on quitting),
        # saved (Linux Manual update done), error
        self.state = "idle"
        self.error: str | None = None
        self.version: str | None = None
        self.done = 0
        self.size = 0
        self._file: Path | None = None
        self._cancel = False
        self._thread: threading.Thread | None = None

    def _staging(self) -> Path | None:
        if self.install is None or self.install.kind != "tarball":
            return None
        root = self.install.root
        return root.parent / f".{root.name}.update"

    def clean(self) -> None:
        """Remove what an earlier or abandoned update left behind (call at startup)."""
        shutil.rmtree(self.dir, ignore_errors=True)
        if staging := self._staging():
            shutil.rmtree(staging, ignore_errors=True)

    def closes_app(self, mode: str) -> bool:
        """Whether `mode` ends with the app closing (all but Linux Manual update)."""
        return not (
            mode == "manual" and self.install is not None and self.install.kind == "tarball"
        )

    def start(
        self, version: str, assets: dict[str, dict], mode: str, when_ready: Callable[[], None]
    ) -> None:
        """Download and check `version`; for a mode that closes the app, then call
        `when_ready` (from the download thread), which waits for the queue and quits."""
        if self.install is None or (self._thread and self._thread.is_alive()):
            return
        self.version, self.error, self._cancel = version, None, False
        self.mode, self.saved = mode, None
        self.state, self.done = "downloading", 0
        self._thread = threading.Thread(
            target=self._run, args=(version, assets, when_ready), name="update", daemon=True
        )
        self._thread.start()

    def cancel(self) -> None:
        self._cancel = True
        if self.state == "waiting":
            self.state = "idle"

    @property
    def cancelled(self) -> bool:
        return self._cancel

    def _get(self, assets: dict[str, dict], name: str) -> dict:
        asset = assets.get(name)
        if not asset:
            raise DownloadError(f"The release has no {name}.")
        if not str(asset.get("url", "")).startswith(download_prefix()):
            raise DownloadError(f"{name} is not on WaveMaterial's release page.")
        return asset

    def _run(self, version: str, assets: dict[str, dict], when_ready: Callable[[], None]) -> None:
        assert self.install is not None
        name = self.install.asset(version)
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            asset, sums_asset = self._get(assets, name), self._get(assets, SUMS)
            req = urllib.request.Request(sums_asset["url"], headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=30) as resp:
                expected = parse_sums(resp.read(1 << 16).decode("utf-8", "replace")).get(name)
            if not expected:
                raise DownloadError(f"{SUMS} doesn't list {name}.")
            self.size = int(asset["size"])

            def progress(done: int, total: int) -> None:
                self.done = done
                if self._cancel:
                    raise _Cancelled

            part = self.dir / f"{name}.part"
            _fetch(asset["url"], part, self.size, progress, 3, 2.0, urllib.request.urlopen)
            if _sha256(part) != expected:
                part.unlink()
                raise DownloadError("The download doesn't match the release's checksum.")
            file = self.dir / name
            part.replace(file)
            if not self.closes_app(self.mode):  # Linux Manual update: save it, and done
                folder = self.downloads()
                folder.mkdir(parents=True, exist_ok=True)
                self.saved = unique_path(folder / name)
                shutil.move(file, self.saved)
                self.state = "saved"
                return
            if self.install.kind == "tarball":
                staging = self._staging()
                assert staging is not None
                file = unpack(file, name.removesuffix(".tar.gz"), staging)
            self._file, self.state = file, "waiting"
            when_ready()
        except _Cancelled:
            self.state = "idle"
        except DownloadError as exc:
            self.error, self.state = str(exc), "error"
        except (OSError, ValueError, KeyError, tarfile.TarError) as exc:
            log.exception("Update download failed")
            self.error, self.state = f"The update could not be downloaded: {exc}", "error"

    def mark_ready(self) -> None:
        """The queue is held and the app is quitting: install on the way out."""
        self.state = "ready"

    def apply(self) -> None:
        """After shutdown: start the installer, or swap the folders and restart."""
        if self.state != "ready" or self._file is None or self.install is None:
            return
        log.info("Installing WaveMaterial %s", self.version)
        detached = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
                    "stderr": subprocess.DEVNULL, "close_fds": True}  # fmt: skip
        if self.install.kind == "windows":
            flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            if self.mode == "self":
                args = ["/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/UPDATE=1"]
            else:  # the normal wizard, once the app has gone
                args = ["/WAIT=1"]
            subprocess.Popen([str(self._file), *args], creationflags=flags, **detached)
            return
        root = self.install.root
        swap(root, self._file)
        shutil.rmtree(self._file.parent, ignore_errors=True)  # the now empty staging folder
        subprocess.Popen(
            [str(root / "bin" / "wavematerial")], start_new_session=True, cwd=Path.home(),
            **detached,
        )  # fmt: skip


class _Cancelled(Exception):
    pass
