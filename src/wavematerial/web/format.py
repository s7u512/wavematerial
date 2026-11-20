# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""Small formatting helpers for the templates: lengths, sizes, dates, times left."""

from __future__ import annotations

import re
from datetime import UTC, datetime


def length(seconds: float | None) -> str:
    """18:44, or 1:04:10 past an hour; an em dash when unknown."""
    if seconds is None:
        return "—"
    s = round(seconds)
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def size(n: int) -> str:
    if n >= 1e9:
        return f"{n / 1e9:.2f} GB"
    if n >= 1e6:
        return f"{n / 1e6:.0f} MB"
    if n >= 1e3:
        return f"{n / 1e3:.0f} KB"
    return f"{n} B"


def added(iso: str | None, now: datetime | None = None) -> str:
    """Today, 14:02 · Yesterday · 12 Nov · 12 Nov 2025 (local time)."""
    if not iso:
        return ""
    when = datetime.fromisoformat(iso).astimezone()
    now = (now or datetime.now(UTC)).astimezone()
    days = (now.date() - when.date()).days
    if days == 0:
        return f"Today, {when:%H:%M}"
    if days == 1:
        return "Yesterday"
    if when.year == now.year:
        return f"{when.day} {when:%b}"
    return f"{when.day} {when:%b %Y}"


def time_left(seconds: float | None) -> str:
    if seconds is None:
        return ""
    if seconds < 60:
        return "less than a minute left"
    minutes = round(seconds / 60)
    return f"about {minutes} min left"


def elapsed_since(iso: str | None) -> float | None:
    if not iso:
        return None
    return (datetime.now(UTC) - datetime.fromisoformat(iso)).total_seconds()


def device_label(stored: str | None) -> str:
    """A job's stored device for display: '... (vulkan)' -> 'AMD Radeon 660M · Vulkan'."""
    if not stored:
        return ""
    name, _, backend = stored.rpartition(" (")
    kind = "Vulkan" if backend.rstrip(")") == "vulkan" else "Processor"
    return f"{short_device(name or stored, keep_vendor=True)} · {kind}"


def short_device(description: str, *, keep_vendor: bool = False) -> str:
    """'AMD Radeon 660M (RADV REMBRANDT)' -> 'Radeon 660M' (or 'AMD Radeon 660M')."""
    name = re.sub(r"\s*\(.*?\)", "", description).strip()
    name = re.sub(r"\s+with Radeon Graphics$", "", name)
    if not keep_vendor:
        name = re.sub(r"^(AMD|NVIDIA|Intel\(R\)|Intel)\s+", "", name)
    return name
