# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""Build the portable Linux .tar.gz.

    uv run --no-project --python 3.12.13 packaging/tarball/build.py [--allow-dirty]

Builds the Linux bundle (packaging/bundle.py) and packs it with the desktop entry, icons,
licence and README into a reproducible tarball, then unpacks it and checks it: it runs,
writes nothing into itself, and holds no paths from this machine.

Result: dist/wavematerial-<version>-linux-x86_64.tar.gz
"""

from __future__ import annotations

import argparse
import gzip
import shutil
import sys
import tarfile
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bundle import REPO, git, leaks, run, snapshot  # noqa: E402 (needs the path above)

HERE = Path(__file__).resolve().parent
APP_ID = "io.github.s7u512.WaveMaterial"
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256, 512)


def extras() -> dict[str, Path]:
    """Files the tarball adds to the bundle: archive path -> source."""
    logo = REPO / "design" / "logo"
    files = {
        "LICENSE.md": REPO / "LICENSE.md",
        "README.txt": HERE / "README.txt",
        f"share/applications/{APP_ID}.desktop": HERE / f"{APP_ID}.desktop",
        f"share/icons/hicolor/scalable/apps/{APP_ID}.svg": logo / "app-icon.svg",
    }
    for size in ICON_SIZES:
        files[f"share/icons/hicolor/{size}x{size}/apps/{APP_ID}.png"] = (
            logo / "png" / f"app-icon-{size}.png"
        )
    return files


def make_tarball(bundle: Path, out: Path, mtime: int) -> None:
    """A reproducible tarball: sorted entries, root-owned, one timestamp (the commit's)."""
    top = bundle.name

    def normalise(info: tarfile.TarInfo) -> tarfile.TarInfo:
        info.uid = info.gid = 0
        info.uname = info.gname = "root"
        info.mtime = mtime
        if info.isfile() and not info.mode & 0o111:
            info.mode = 0o644
        elif info.isdir() or info.mode & 0o111:
            info.mode = 0o755
        return info

    entries = {f"{top}/{p.relative_to(bundle).as_posix()}": p for p in bundle.rglob("*")}
    for name, source in extras().items():
        entries[f"{top}/{name}"] = source
        parent = Path(name).parent
        while parent != Path("."):
            entries.setdefault(f"{top}/{parent.as_posix()}", None)
            parent = parent.parent
    with (
        out.open("wb") as raw,
        gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=mtime, compresslevel=9) as gz,
        tarfile.open(fileobj=gz, mode="w") as tf,
    ):
        tf.add(bundle, arcname=top, recursive=False, filter=normalise)
        for name in sorted(entries):
            source = entries[name]
            if source is None:
                info = tarfile.TarInfo(name)
                info.type = tarfile.DIRTYPE
                tf.addfile(normalise(info))
            else:
                tf.add(source, arcname=name, recursive=False, filter=normalise)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--allow-dirty", action="store_true", help="build from uncommitted changes")
    args = ap.parse_args()

    version = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]
    dirty = ["--allow-dirty"] if args.allow_dirty else []
    run(sys.executable, REPO / "packaging" / "bundle.py", "--target", "linux", *dirty)
    bundle = REPO / "dist" / "bundle" / f"wavematerial-{version}-linux-x86_64"
    dist = REPO / "dist"

    # 1. The tarball.
    mtime = int(git("log", "-1", "--format=%ct"))
    tarball = dist / f"{bundle.name}.tar.gz"
    make_tarball(bundle, tarball, mtime)

    # 2. Check it: unpack it elsewhere, run it, and look for writes and build paths.
    check = dist / "tarball-check"
    if check.exists():
        shutil.rmtree(check)
    check.mkdir()
    run("tar", "-xzf", tarball, "-C", check)
    unpacked = check / bundle.name
    before = snapshot(unpacked)
    run(unpacked / "bin" / "wavematerial", "--version")
    written = snapshot(unpacked) - before
    if written:
        sys.exit(f"Running the tarball's app wrote into it: {sorted(written)[:10]}")
    found = leaks(unpacked, [str(REPO).encode(), str(Path.home()).encode()])
    if found:
        sys.exit(f"Build paths found in the tarball: {found[:20]}")
    if shutil.which("desktop-file-validate"):
        run("desktop-file-validate", HERE / f"{APP_ID}.desktop")
    shutil.rmtree(check)

    print(f"\nTarball: {tarball} ({tarball.stat().st_size / 1e6:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
