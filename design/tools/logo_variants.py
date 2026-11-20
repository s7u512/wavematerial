#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""Generate every WaveMaterial logo variant from the hand-made master.

Master: design/logo/app-icon.svg (red tile + yellow waveform + yellow sickle). Outputs go to
design/logo/:

    app-icon.svg              the master itself (untouched)
    logo-mark.svg             mark only (no tile), original yellows, on transparent:
                              for use on the red tile colour or any dark background
    logo-mark-red.svg         mark only, all accent red: for light or neutral backgrounds
    logo-mark-light.svg       mark only, single light grey #ECECEC: monochrome on dark UI
    logo-mark-dark.svg        mark only, single near-black #111214: monochrome on light/print
    png/app-icon-<N>.png      N = 16 24 32 48 64 128 256 512 1024 (Linux icon theme, Flatpak, docs)
    png/logo-mark-<N>.png     N = 32 64 128 256 512
    app-icon.ico              Windows icon, PNG-compressed entries 16-256 px (.exe, shortcuts)

The mark-only variants are cropped to the mark's bounding box plus padding, in a square
viewBox, so they sit centred at any size. PNGs are rendered with vectorcraft-cli.

Usage (from design/):  uv run python tools/logo_variants.py
"""

from __future__ import annotations

import struct
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from logo_source import MASTER, bbox, parts  # noqa: E402

OUT = MASTER.parent
ICON_SIZES = [16, 24, 32, 48, 64, 128, 256, 512, 1024]
MARK_SIZES = [32, 64, 128, 256, 512]
ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]
PAD = 0.06  # padding around the mark, as a fraction of its larger side


def mark_svg(mark, colour: str | None, title: str) -> str:
    x0, y0, x1, y1 = bbox([p.d for p in mark])
    side = max(x1 - x0, y1 - y0) * (1 + 2 * PAD)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    vb = f"{cx - side / 2:.3f} {cy - side / 2:.3f} {side:.3f} {side:.3f}"
    body = "".join(f'<path d="{p.d}" fill="{colour or p.fill}"/>' for p in mark)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="{vb}">'
        f"<title>{title}</title>{body}</svg>\n"
    )


def render(svg: Path, png: Path, px: int) -> None:
    res = subprocess.run(
        ["vectorcraft-cli", "convert", str(svg), str(png), "--scale", f"{px / 256}"],
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        raise SystemExit(f"render {svg.name} at {px}px failed:\n{res.stdout}{res.stderr}")


def write_ico(pngs: list[tuple[int, bytes]], path: Path) -> None:
    """ICO with PNG-compressed entries (supported since Windows Vista)."""
    header = struct.pack("<HHH", 0, 1, len(pngs))
    offset = 6 + 16 * len(pngs)
    entries, data = b"", b""
    for size, blob in pngs:
        dim = 0 if size >= 256 else size  # 0 means 256 in the ICO directory
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(blob), offset + len(data))
        data += blob
    path.write_bytes(header + entries + data)


def main() -> int:
    _, _, mark = parts()
    variants = {
        "logo-mark.svg": (None, "WaveMaterial mark"),
        "logo-mark-red.svg": ("#C81400", "WaveMaterial mark (red)"),
        "logo-mark-light.svg": ("#ECECEC", "WaveMaterial mark (light mono)"),
        "logo-mark-dark.svg": ("#111214", "WaveMaterial mark (dark mono)"),
    }
    for name, (colour, title) in variants.items():
        (OUT / name).write_text(mark_svg(mark, colour, title))

    png_dir = OUT / "png"
    png_dir.mkdir(exist_ok=True)
    for n in ICON_SIZES:
        render(MASTER, png_dir / f"app-icon-{n}.png", n)
    for n in MARK_SIZES:
        render(OUT / "logo-mark.svg", png_dir / f"logo-mark-{n}.png", n)
    write_ico(
        [(n, (png_dir / f"app-icon-{n}.png").read_bytes()) for n in ICO_SIZES], OUT / "app-icon.ico"
    )

    print("wrote:", ", ".join([*variants, "app-icon.ico"]))
    print(f"png/: app-icon {ICON_SIZES}, logo-mark {MARK_SIZES}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
