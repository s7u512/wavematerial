# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""Read the master WaveMaterial logo (design/logo/app-icon.svg, drawn by hand) into parts.

The master is the single source of truth. Everything else (variants, PNGs, the .ico, the
VectorCraft replica, the logo in the FigCraft mock-ups) is derived from it by code.

The master is a 256 × 256 SVG of filled paths that use only absolute M / L / C / Z commands:
  - the tile (the first path, a rounded square in the accent red),
  - five waveform bars and the sickle (all the other paths).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

MASTER = Path(__file__).resolve().parents[1] / "logo" / "app-icon.svg"
SVG_NS = "{http://www.w3.org/2000/svg}"
_NUM = re.compile(r"-?\d*\.?\d+(?:[eE][-+]?\d+)?")


@dataclass
class Part:
    name: str
    d: str
    fill: str


def parts(master: Path = MASTER) -> tuple[float, Part, list[Part]]:
    """Returns (canvas size, tile, mark parts in paint order)."""
    root = ET.parse(master).getroot()
    size = float(root.get("width", "256"))
    paths = [el for el in root.iter(f"{SVG_NS}path")]
    if len(paths) < 2:
        raise SystemExit(f"{master}: expected a tile path plus mark paths")
    if not re.fullmatch(r"[MLCZmlcz0-9.\s,-]+", "".join(p.get("d", "") for p in paths)):
        raise SystemExit(f"{master}: only absolute M/L/C/Z path data is supported")
    tile = Part("Tile", paths[0].get("d", ""), paths[0].get("fill", "#000000").upper())
    mark = []
    bar_n = 0
    for el in paths[1:]:
        fill = el.get("fill", "#000000").upper()
        if fill == "#FFFF00":
            bar_n += 1
            name = f"Wave bar {bar_n}"
        else:
            name = "Sickle"
        mark.append(Part(name, el.get("d", ""), fill))
    return size, tile, mark


def scale_d(d: str, k: float, dx: float = 0.0, dy: float = 0.0) -> str:
    """Scale absolute path data by k, then offset by (dx, dy). Coordinates alternate x, y."""
    out, i = [], 0
    for tok in re.findall(r"[MLCZmlcz]|" + _NUM.pattern, d):
        if tok.isalpha():
            out.append(tok)
            continue
        v = float(tok) * k + (dx if i % 2 == 0 else dy)
        out.append(f"{v:.3f}")
        i += 1
    return " ".join(out)


def bbox(ds: list[str]) -> tuple[float, float, float, float]:
    """Bounding box of every coordinate (anchors and control points) in the path data."""
    xs, ys = [], []
    for d in ds:
        nums = [float(n) for n in _NUM.findall(d)]
        xs += nums[0::2]
        ys += nums[1::2]
    return min(xs), min(ys), max(xs), max(ys)
