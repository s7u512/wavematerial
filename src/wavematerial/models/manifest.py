# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""The model manifest (`manifest.toml`): what to download, how to check it, and whom to credit."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA_VERSION = 1
_SHA256 = re.compile(r"[0-9a-f]{64}")


class ManifestError(ValueError):
    """The manifest is malformed. This is a packaging bug, not a user problem."""


@dataclass(frozen=True)
class FileSpec:
    path: str  # relative to the model's folder, using `/`
    size: int
    sha256: str


@dataclass(frozen=True)
class ModelSpec:
    id: str
    name: str
    role: str
    licence: str
    creator: str
    model_card: str
    changes: str
    url: str
    size: int
    sha256: str
    files: tuple[FileSpec, ...]
    archive: str | None = None  # only "tar.bz2" so far
    archive_root: str = ""

    @property
    def installed_size(self) -> int:
        return sum(f.size for f in self.files)

    def folder(self, models_dir: Path) -> Path:
        return models_dir / self.id

    def file(self, models_dir: Path, path: str) -> Path:
        """The installed location of one of this model's files."""
        return self.folder(models_dir) / path


def _checked_sha(value: Any, where: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ManifestError(f"{where}: sha256 must be 64 lowercase hex digits")
    return value


def _checked_size(value: Any, where: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ManifestError(f"{where}: size must be a positive integer")
    return value


def _checked_path(value: Any, where: str) -> str:
    p = PurePosixPath(value) if isinstance(value, str) else None
    if p is None or p.is_absolute() or ".." in p.parts or not p.parts:
        raise ManifestError(f"{where}: path must be relative and stay inside the model folder")
    return str(p)


def parse_manifest(data: dict[str, Any]) -> tuple[ModelSpec, ...]:
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ManifestError(f"unsupported manifest schema {data.get('schema_version')!r}")
    models = []
    for i, m in enumerate(data.get("model", [])):
        where = f"model {m.get('id', i)!r}"
        try:
            spec = ModelSpec(
                id=_checked_path(m["id"], where),
                name=m["name"],
                role=m["role"],
                licence=m["licence"],
                creator=m["creator"],
                model_card=m["model_card"],
                changes=m["changes"],
                url=m["url"],
                size=_checked_size(m["size"], where),
                sha256=_checked_sha(m["sha256"], where),
                files=tuple(
                    FileSpec(
                        _checked_path(f["path"], where),
                        _checked_size(f["size"], where),
                        _checked_sha(f["sha256"], where),
                    )
                    for f in m["files"]
                ),
                archive=m.get("archive"),
                archive_root=m.get("archive_root", ""),
            )
        except KeyError as exc:
            raise ManifestError(f"{where}: missing {exc}") from exc
        if not spec.url.startswith("https://"):
            raise ManifestError(f"{where}: url must be https")
        if spec.archive not in (None, "tar.bz2"):
            raise ManifestError(f"{where}: unsupported archive type {spec.archive!r}")
        if spec.archive is None and len(spec.files) != 1:
            raise ManifestError(f"{where}: a single-file model lists exactly one file")
        models.append(spec)
    if len({m.id for m in models}) != len(models):
        raise ManifestError("model ids must be unique")
    return tuple(models)


def load_manifest() -> tuple[ModelSpec, ...]:
    """The manifest shipped with this version of the app."""
    text = files("wavematerial.models").joinpath("manifest.toml").read_text(encoding="utf-8")
    return parse_manifest(tomllib.loads(text))


def get_model(models: tuple[ModelSpec, ...], model_id: str) -> ModelSpec:
    for m in models:
        if m.id == model_id:
            return m
    raise KeyError(model_id)
