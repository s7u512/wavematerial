# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""The licences-and-credits page: what WaveMaterial is made of, and under which licences.

Python packages are read from the installed environment (so a release lists exactly what
it bundles); the rest is a short hand-kept list with licence files shipped in `static/`.
"""

from __future__ import annotations

import importlib.metadata as md
import json
import re
import sys
import sysconfig
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

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
    Component(
        f"Python {sys.version.split()[0]} and the libraries built into it",
        "",
        "PSF-2.0; OpenSSL Apache-2.0; others (see text)",
        "python",
    ),
    Component("Pico CSS", "2.1.1", "MIT", "static/vendor/pico/LICENSE.md"),
    Component("htmx", "2.0.11", "0BSD", "static/vendor/htmx/LICENSE"),
    Component("Inter", "", "OFL-1.1", "static/fonts/inter/OFL.txt"),
    Component("Noto Sans", "", "OFL-1.1", "static/fonts/noto-sans/OFL.txt"),
]


# Shown when the runtime has no vendored-library list (a development install).
_FFMPEG_SUMMARY = Component(
    "FFmpeg and codec libraries (inside PyAV)",
    "",
    "LGPL-3.0-or-later; x264 and x265 GPL-2.0-or-later",
    "pkg/av",
)


def _vendored_dir() -> Path:
    return Path(sys.base_prefix) / "licenses" / "vendored"


def vendored() -> list[Component]:
    """Native libraries inside the bundled wheels, as packaging/bundle.py listed them."""
    listing = _vendored_dir() / "components.json"
    if not listing.is_file():
        return []
    entries = json.loads(listing.read_text(encoding="utf-8"))
    return [
        Component(e["name"], e["version"], e["licence"], f"vendored/{e['key']}") for e in entries
    ]


def bundled() -> list[Component]:
    """Everything that isn't a Python package: the runtime, native libraries, front end, fonts."""
    native = vendored() or [_FFMPEG_SUMMARY]
    return BUNDLED[:1] + native + BUNDLED[1:]


def _python_licences() -> str:
    """CPython's licence, plus those of the libraries built into the runtime.

    Packages ship them in `<runtime>/licenses/` (collected by packaging/bundle.py); a
    development runtime has only CPython's own `LICENSE.txt`.
    """
    shipped = Path(sys.base_prefix) / "licenses"
    paths = sorted(
        shipped.glob("LICENSE.*.txt"), key=lambda p: (p.name != "LICENSE.cpython.txt", p.name)
    )
    if not paths:
        own = Path(sysconfig.get_paths()["stdlib"]) / "LICENSE.txt"
        paths = [own] if own.is_file() else []
    texts = [f"== {p.name} ==\n\n{p.read_text(encoding='utf-8', errors='replace')}" for p in paths]
    return "\n\n".join(texts) or (
        "Python is distributed under the Python Software Foundation License Version 2.\n"
        "See https://docs.python.org/3/license.html"
    )


def licence_text(key: str) -> str | None:
    if key == "app":
        for f in md.distribution("wavematerial").files or []:
            if f.name == "LICENSE.md":
                return f.read_text(encoding="utf-8")
        return None
    if key == "python":
        return _python_licences()
    if key.startswith("vendored/"):
        name = key.removeprefix("vendored/")
        folder = _vendored_dir() / name
        if "/" in name or name.startswith(".") or not folder.is_dir():
            return None
        texts = [
            f"== {p.name} ==\n\n{p.read_text(encoding='utf-8', errors='replace')}"
            for p in sorted(folder.iterdir())
            if p.is_file()
        ]
        return "\n\n".join(texts) or None
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
