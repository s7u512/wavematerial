# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""Where WaveMaterial keeps its data, and the user's settings (`config.toml`)."""

from __future__ import annotations

import logging
import re
import tomllib
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

import platformdirs
import tomli_w

from wavematerial._fsutil import write_text_atomic

APP_NAME = "wavematerial"

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Paths:
    """The app's folders. Nothing is ever written inside the install folder."""

    config_dir: Path
    data_dir: Path
    state_dir: Path
    cache_dir: Path

    @classmethod
    def default(cls) -> Paths:
        """The per-user locations from `platformdirs` (Flatpak's XDG folders included)."""
        data = Path(platformdirs.user_data_dir(APP_NAME, appauthor=False))
        cache = Path(platformdirs.user_cache_dir(APP_NAME, appauthor=False, opinion=False))
        if cache == data:  # Windows: both are %LOCALAPPDATA%\wavematerial
            cache = data / "cache"
        return cls(
            config_dir=Path(platformdirs.user_config_dir(APP_NAME, appauthor=False, roaming=True)),
            data_dir=data,
            state_dir=Path(platformdirs.user_state_dir(APP_NAME, appauthor=False)),
            cache_dir=cache,
        )

    @classmethod
    def under(cls, root: Path) -> Paths:
        """Every location inside one folder, for tests and development."""
        return cls(root / "config", root / "data", root / "state", root / "cache")

    @property
    def settings_file(self) -> Path:
        return self.config_dir / "config.toml"

    @property
    def jobs_db(self) -> Path:
        return self.data_dir / "jobs.db"

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"

    @property
    def default_models_dir(self) -> Path:
        return self.data_dir / "models"

    @property
    def logs_dir(self) -> Path:
        return self.state_dir / "logs"

    def models_dir(self, settings: Settings) -> Path:
        """The models folder: the one chosen in Settings, or the default."""
        return Path(settings.models_dir) if settings.models_dir else self.default_models_dir


_DEVICE = re.compile(r"auto|cpu|vulkan:\S+")


@dataclass
class Settings:
    """User settings. An empty string means "not set" (TOML has no null)."""

    device: str = "auto"  # "auto", "cpu", or "vulkan:<stable device id, e.g. PCI bus id>"
    threads: int = 0  # 0 means physical cores - 1
    min_speakers: int = 2
    max_speakers: int = 3
    key_terms: list[str] = field(default_factory=list)
    update_check: bool = True
    models_dir: str = ""
    export_dir: str = ""


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


_VALID = {
    "device": lambda v: isinstance(v, str) and _DEVICE.fullmatch(v) is not None,
    "threads": lambda v: _is_int(v) and 0 <= v <= 1024,
    "min_speakers": lambda v: _is_int(v) and 1 <= v <= 20,
    "max_speakers": lambda v: _is_int(v) and 1 <= v <= 20,
    "key_terms": lambda v: isinstance(v, list) and all(isinstance(t, str) for t in v),
    "update_check": lambda v: isinstance(v, bool),
    "models_dir": lambda v: isinstance(v, str),
    "export_dir": lambda v: isinstance(v, str),
}


def load_settings(path: Path) -> Settings:
    """Read the settings file. A missing, unreadable, or invalid value falls back to its default.

    Problems are logged, never raised: a bad settings file must not stop the app starting.
    """
    settings = Settings()
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return settings
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        log.warning("Ignoring settings file %s, using defaults: %s", path, exc)
        return settings

    known = {f.name for f in fields(Settings)}
    for key, value in raw.items():
        if key not in known:
            log.warning("Ignoring unknown setting %r in %s", key, path)
        elif not _VALID[key](value):
            log.warning("Ignoring invalid value for %r in %s: %r", key, path, value)
        else:
            setattr(settings, key, value)

    if settings.min_speakers > settings.max_speakers:
        log.warning("min_speakers is above max_speakers in %s; using the defaults", path)
        settings.min_speakers, settings.max_speakers = Settings.min_speakers, Settings.max_speakers
    settings.key_terms = [t.strip() for t in settings.key_terms if t.strip()]
    return settings


def save_settings(path: Path, settings: Settings) -> None:
    write_text_atomic(path, tomli_w.dumps(asdict(settings)))
