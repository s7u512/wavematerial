# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""A job's report for "Copy log": what a bug report needs, ready to paste into an issue.

The app's version, the system, the job's settings and outcome, its events, and the end of
its worker log. The user's home folder is replaced by `~`, since issues are public;
recording names stay (they may matter, and the user sees everything before pasting).
"""

from __future__ import annotations

import platform
import re
import sys
from pathlib import Path

from wavematerial import __version__
from wavematerial.jobs.events import read_events
from wavematerial.jobs.store import Job

TAIL_LINES = 200
TAIL_BYTES = 256 * 1024  # enough for 200 lines of any sensible length


def system() -> str:
    """The operating system, as a person would name it."""
    if sys.platform == "win32":
        release, version, _, _ = platform.win32_ver()
        return f"Windows {release} ({version})"
    if sys.platform == "linux":
        name = "Linux"
        try:
            for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
                if line.startswith("PRETTY_NAME="):
                    name = line.split("=", 1)[1].strip().strip('"')
        except OSError:
            pass
        return f"{name} (kernel {platform.release()})"
    return platform.platform()


def tail(path: Path, lines: int = TAIL_LINES) -> list[str]:
    """The last `lines` lines of a text file (empty if it doesn't exist)."""
    try:
        with path.open("rb") as f:
            size = f.seek(0, 2)
            f.seek(max(0, size - TAIL_BYTES))
            text = f.read().decode("utf-8", "replace")
    except OSError:
        return []
    return text.splitlines()[-lines:]


def without_home(text: str, home: Path) -> str:
    """`text` with the home folder replaced by `~` (any slash style; case-insensitive on
    Windows, where paths are)."""
    forms = {str(home), str(home).replace("\\", "/"), str(home).replace("/", "\\")}
    flags = re.IGNORECASE if sys.platform == "win32" else 0
    for form in sorted(forms, key=len, reverse=True):
        if len(form) > 1:  # never replace a bare "/"
            text = re.sub(re.escape(form), "~", text, flags=flags)
    return text


def build(job: Job, job_dir: Path, home: Path | None = None) -> str:
    """The report for one job."""
    duration = f"{job.duration:.0f} s" if job.duration else "unknown length"
    terms = f"{len(job.key_terms)} key terms" if job.key_terms else "no key terms"
    lines = [
        f"WaveMaterial {__version__} · {system()} · Python {platform.python_version()}",
        f"Device: {job.device or 'not started'}",
        f"Recording: {job.source.name} · {duration} · "
        f"{job.min_speakers}–{job.max_speakers} speakers · {terms}",
        f"State: {job.state}" + (f" · {job.error}" if job.error else ""),
        "",
        "--- Events ---",
        *read_events(job_dir),
        "",
        f"--- Worker log (last {TAIL_LINES} lines) ---",
        *tail(job_dir / "worker.log"),
    ]
    return without_home("\n".join(lines) + "\n", home or Path.home())
