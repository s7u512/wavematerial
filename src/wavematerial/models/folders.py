# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""Where the models live: choosing the folder, checking it, and removing the models.

A chosen folder always gets a `WaveMaterial models` subfolder (so the models never scatter
over, say, the root of a drive), unless the chosen folder already is one. Partial downloads
live in its `.downloads` folder, so a download only ever needs room on one drive.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from wavematerial.models.manifest import ModelSpec

FOLDER_NAME = "WaveMaterial models"
DOWNLOADS = ".downloads"
POINTER = "models-folder.txt"  # in the data folder; read by the Windows uninstaller
ONEDRIVE_VARS = ("OneDrive", "OneDriveConsumer", "OneDriveCommercial")

CANT_WRITE = "WaveMaterial can't write to this folder. Choose another one."
ONEDRIVE = "WaveMaterial doesn't save its models in folders synced by OneDrive. Choose another one."


def is_models_folder(folder: Path, manifest: tuple[ModelSpec, ...]) -> bool:
    """A `WaveMaterial models` folder, or one that already holds our models."""
    if folder.name == FOLDER_NAME:
        return True
    return any(m.folder(folder).is_dir() for m in manifest)


def models_folder_for(chosen: Path, manifest: tuple[ModelSpec, ...]) -> Path:
    """The models folder for a folder the user picked."""
    return chosen if is_models_folder(chosen, manifest) else chosen / FOLDER_NAME


def in_onedrive(folder: Path, environ: dict[str, str] | None = None) -> bool:
    """Whether `folder` is inside a OneDrive-synced folder (Windows names them in its
    environment; Documents and Desktop are often moved there)."""
    env = os.environ if environ is None else environ
    target = os.path.normcase(os.path.abspath(folder))
    for var in ONEDRIVE_VARS:
        root = env.get(var)
        if root:
            root = os.path.normcase(os.path.abspath(root))
            if target == root or target.startswith(root.rstrip("\\/") + os.sep):
                return True
    return False


def writable(folder: Path) -> bool:
    """Try it: create the folder if needed and write a small file there. Anything that
    needs admin rights (Program Files, /opt, ...) or a read-only drive fails this."""
    created = []
    try:
        for parent in reversed([folder, *folder.parents]):
            if not parent.exists():
                parent.mkdir()
                created.append(parent)
        fd, name = tempfile.mkstemp(prefix=".write-test-", dir=folder)
        os.close(fd)
        os.unlink(name)
        return True
    except OSError:
        for path in reversed(created):  # leave no empty folders behind
            try:
                path.rmdir()
            except OSError:
                pass
        return False


def problem_with(folder: Path) -> str | None:
    """Why the models can't go in `folder`, or None if they can."""
    if in_onedrive(folder):
        return ONEDRIVE
    if not writable(folder):
        return CANT_WRITE
    return None


def unavailable(folder: Path) -> bool:
    """A chosen models folder whose drive is gone (unplugged, unmounted): not even its
    parent exists. A deleted folder on a present drive just means "download again"."""
    return not folder.exists() and not folder.parent.exists()


def space_needed(missing: list[ModelSpec], done: dict[str, int]) -> int:
    """Room a download needs: what is left to download, plus the largest archive's unpacked
    size (it sits beside its download while unpacking), plus 10%, rounded to 100 MB."""
    left = sum(m.size - done.get(m.id, 0) for m in missing)
    unpacked = max((m.installed_size for m in missing if m.archive), default=0)
    return round((left + unpacked) * 1.1 / 1e8) * 100_000_000


def free_space(folder: Path) -> int:
    """Free bytes on the drive that holds (or will hold) `folder`."""
    while not folder.exists() and folder.parent != folder:
        folder = folder.parent
    return shutil.disk_usage(folder).free


def remove_models(folder: Path, manifest: tuple[ModelSpec, ...], default: Path) -> int:
    """Delete the downloaded models (and partial downloads) from `folder`; return the bytes
    freed. The folder itself goes too if it is ours (a `WaveMaterial models` folder or the
    default one) and is then empty; nothing else in it is ever touched."""
    freed = 0
    for path in [m.folder(folder) for m in manifest] + [folder / DOWNLOADS]:
        if path.is_dir():
            freed += sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
            shutil.rmtree(path)
    ours = folder.name == FOLDER_NAME or os.path.normcase(folder) == os.path.normcase(default)
    if ours and folder.is_dir() and not any(folder.iterdir()):
        folder.rmdir()
    return freed


def write_pointer(data_dir: Path, folder: Path) -> None:
    """Note the models folder for the Windows uninstaller (UTF-8 with a byte order mark,
    which Inno Setup reads correctly)."""
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / POINTER).write_text(f"{folder}\n", encoding="utf-8-sig")
    except OSError:
        pass
