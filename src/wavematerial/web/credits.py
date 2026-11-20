# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""The licences-and-credits page: what WaveMaterial is made of, and under which licences.

Python packages are read from the installed environment (so a release lists exactly what
it bundles); the rest is a short hand-kept list with licence files shipped in `static/`.
"""

from __future__ import annotations

import importlib.metadata as md
import re
import sys
from dataclasses import dataclass
from importlib.resources import files

_LICENCE_FILE = re.compile(r"(^|/)(LICEN[CS]E|COPYING|NOTICE|AUTHORS)[^/]*$", re.IGNORECASE)


@dataclass(frozen=True)
class Component:
    name: str
    version: str
    licence: str
    key: str  # what /credits/licence/<key> shows


def _licence_of(dist: md.Distribution) -> str:
    meta = dist.metadata
    if meta.get("License-Expression"):
        return meta["License-Expression"]
    classifiers = [c.split(" :: ")[-1] for c in meta.get_all("Classifier") or [] if "License" in c]
    if classifiers:
        return ", ".join(classifiers)
    first = (meta.get("License") or "").strip().splitlines()
    return first[0][:80] if first else "see licence text"


def software() -> list[Component]:
    """Every installed Python distribution except WaveMaterial itself, by name."""
    seen: dict[str, Component] = {}
    for dist in md.distributions():
        name = dist.metadata["Name"]
        if not name or name.lower() == "wavematerial":
            continue
        seen[name.lower()] = Component(name, dist.version, _licence_of(dist), f"pkg/{name}")
    return sorted(seen.values(), key=lambda c: c.name.lower())


# Not Python packages, or bundled inside one; their licence files ship in static/.
BUNDLED = [
    Component(f"Python {sys.version.split()[0]}", "", "PSF-2.0", "python"),
    Component(
        "FFmpeg and codec libraries (inside PyAV)",
        "",
        "LGPL-3.0-or-later; x264 and x265 GPL-2.0-or-later",
        "pkg/av",
    ),
    Component("Pico CSS", "2.1.1", "MIT", "static/vendor/pico/LICENSE.md"),
    Component("htmx", "2.0.11", "0BSD", "static/vendor/htmx/LICENSE"),
    Component("Inter", "", "OFL-1.1", "static/fonts/inter/OFL.txt"),
    Component("Noto Sans", "", "OFL-1.1", "static/fonts/noto-sans/OFL.txt"),
]


def licence_text(key: str) -> str | None:
    if key == "app":
        for f in md.distribution("wavematerial").files or []:
            if f.name == "LICENSE.md":
                return f.read_text(encoding="utf-8")
        return None
    if key == "python":
        return (
            "Python is distributed under the Python Software Foundation License Version 2.\n"
            "See https://docs.python.org/3/license.html"
        )
    if key.startswith("static/"):
        rel = key.removeprefix("static/")
        if ".." in rel.split("/"):
            return None
        path = files("wavematerial.web").joinpath("static", *rel.split("/"))
        return path.read_text(encoding="utf-8") if path.is_file() else None
    if key.startswith("pkg/"):
        try:
            dist = md.distribution(key.removeprefix("pkg/"))
        except md.PackageNotFoundError:
            return None
        texts = []
        for f in dist.files or []:
            if _LICENCE_FILE.search(str(f)):
                try:
                    texts.append(f"== {f.name} ==\n\n{f.read_text(encoding='utf-8')}")
                except (OSError, UnicodeDecodeError):
                    continue
        if texts:
            return "\n\n".join(texts)
        meta = dist.metadata.get("License")
        return meta or f"{dist.metadata['Name']} is licensed under {_licence_of(dist)}."
    return None
