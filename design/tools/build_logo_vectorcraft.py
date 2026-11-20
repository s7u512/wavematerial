#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""Rebuild the WaveMaterial logo in VectorCraft from code, then prove it matches the master.

Reads design/logo/app-icon.svg (the hand-made master), generates a VectorCraft command
script that draws every shape as a named path with its fill (no import, no tracing), runs it
headless, and writes:

    design/logo/wavematerial-logo.vectorcraft    editable VectorCraft document (layers named)
    design/logo/replica/app-icon.svg              the replica exported as SVG
    design/logo/replica/app-icon@4x.png           the replica rendered at 1024 px

Then it renders the master the same way and asks VectorCraft to compare the two
(document.compare): it prints the RMSE and the number of differing pixels.

Usage (from design/):  uv run python tools/build_logo_vectorcraft.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from logo_source import MASTER, parts  # noqa: E402

LOGO_DIR = MASTER.parent
OUT_DOC = LOGO_DIR / "wavematerial-logo.vectorcraft"
REPLICA = LOGO_DIR / "replica"


def script(size: float, tile, mark) -> list[dict]:
    steps: list[dict] = [
        {
            "command": "file.new",
            "params": {
                "name": "WaveMaterial logo",
                "width": size,
                "height": size,
                "units": "Pixels",
                "backgroundContents": "transparent",
            },
        }
    ]
    for part in [tile, *mark]:
        n = len(steps)  # index of the path.create step, referenced as "$n.id"
        steps += [
            {"command": "path.create", "params": {"d": part.d}},
            {"command": "paint.setFill", "params": {"id": f"${n}.id", "color": part.fill}},
            {"command": "paint.setStroke", "params": {"id": f"${n}.id", "none": True}},
            {"command": "object.setProps", "params": {"id": f"${n}.id", "name": part.name}},
        ]
    return steps


def run(cmd: list[str]) -> str:
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise SystemExit(f"{' '.join(cmd[:3])} failed:\n{res.stdout}\n{res.stderr}")
    return res.stdout


def main() -> int:
    size, tile, mark = parts()
    REPLICA.mkdir(parents=True, exist_ok=True)
    steps_file = REPLICA / "steps.json"
    steps_file.write_text(json.dumps(script(size, tile, mark), indent=1))

    run(
        [
            "vectorcraft-cli",
            "run",
            "--commands",
            str(steps_file),
            "--export",
            str(OUT_DOC),
            "--export",
            str(REPLICA / "app-icon.svg"),
        ]
    )
    run(
        [
            "vectorcraft-cli",
            "run",
            "--in",
            str(OUT_DOC),
            "--export",
            str(REPLICA / "app-icon@4x.png"),
            "--scale",
            "4",
        ]
    )
    # the master rendered by the same engine, then compared against the replica document
    master_png = REPLICA / "master@4x.png"
    run(["vectorcraft-cli", "convert", str(MASTER), str(master_png), "--scale", "4"])
    out = run(
        [
            "vectorcraft-cli",
            "run",
            "--in",
            str(OUT_DOC),
            "--cmd",
            "document.compare",
            "--params",
            json.dumps(
                {
                    "path": str(master_png),
                    "diffPath": str(REPLICA / "diff.png"),
                    "background": "#000000",
                }
            ),
        ]
    )
    result = json.loads(out.strip().splitlines()[-1])["result"]
    print(
        f"replica: {OUT_DOC.relative_to(LOGO_DIR.parent)} ({1 + len(mark)} paths: tile, "
        f"{sum(p.name.startswith('Wave') for p in mark)} wave bars, sickle)"
    )
    print(
        f"compare vs master @4x: rmse {result['rmse']}, "
        f"differing pixels {result['over']} of {result['total']}"
    )
    steps_file.unlink()
    return 0 if result["over"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
