# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""The update check: asks GitHub whether a newer release exists. Installing stays manual.

Runs at most once a day (plus "Check now"), and only if enabled in Settings. Offline or
failed checks are silent. Besides model downloads, this is the app's only network call.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from wavematerial import __version__
from wavematerial._fsutil import write_text_atomic

RELEASES_API = "https://api.github.com/repos/s7u512/wavematerial/releases/latest"
RELEASES_PAGE = "https://github.com/s7u512/wavematerial/releases"
INTERVAL = timedelta(days=1)

log = logging.getLogger(__name__)


def _version_key(version: str) -> tuple[tuple[int, ...], int]:
    """(numbers, 1 for a release / 0 for a development build), so 1.0.0.dev0 < 1.0.0."""
    nums = tuple(int(n) for n in re.findall(r"\d+", version.split(".dev")[0])[:3])
    return nums, 0 if ".dev" in version else 1


def is_newer(latest: str, current: str = __version__) -> bool:
    return _version_key(latest.lstrip("v")) > _version_key(current)


@dataclass
class UpdateStatus:
    checked_at: str | None = None
    latest: str | None = None
    url: str | None = None


class UpdateChecker:
    def __init__(self, state_file: Path):
        self.state_file = state_file
        self.checking = False
        self.status = self._load()

    def _load(self) -> UpdateStatus:
        try:
            return UpdateStatus(**json.loads(self.state_file.read_text(encoding="utf-8")))
        except (FileNotFoundError, json.JSONDecodeError, TypeError):
            return UpdateStatus()

    def due(self) -> bool:
        if not self.status.checked_at:
            return True
        return datetime.now(UTC) - datetime.fromisoformat(self.status.checked_at) > INTERVAL

    def check_in_background(self, force: bool = False) -> None:
        if self.checking or not (force or self.due()):
            return
        self.checking = True
        threading.Thread(target=self._check, name="update-check", daemon=True).start()

    def _check(self) -> None:
        try:
            req = urllib.request.Request(
                RELEASES_API,
                headers={
                    "User-Agent": f"WaveMaterial/{__version__}",
                    "Accept": "application/vnd.github+json",
                },
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.load(resp)
            self.status = UpdateStatus(
                checked_at=datetime.now(UTC).isoformat(timespec="seconds"),
                latest=str(data.get("tag_name", "")).lstrip("v") or None,
                url=data.get("html_url") or RELEASES_PAGE,
            )
        except urllib.error.HTTPError as exc:
            if exc.code == 404:  # no release published yet
                self.status = UpdateStatus(
                    checked_at=datetime.now(UTC).isoformat(timespec="seconds")
                )
            else:
                log.info("Update check failed: %s", exc)
        except (OSError, ValueError) as exc:
            log.info("Update check failed (offline?): %s", exc)
        finally:
            self.checking = False
        if self.status.checked_at:
            write_text_atomic(self.state_file, json.dumps(asdict(self.status)))

    def message(self) -> str:
        if self.checking:
            return "Checking…"
        s = self.status
        if s.latest and is_newer(s.latest):
            return f"WaveMaterial {s.latest} is available."
        if s.checked_at:
            return f"You have WaveMaterial {__version__}, the latest version."
        return f"You have WaveMaterial {__version__}. Not checked yet."

    def update_available(self) -> bool:
        return bool(self.status.latest and is_newer(self.status.latest))
