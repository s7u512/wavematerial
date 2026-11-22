# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""Build the portable Linux .tar.gz.

    uv run --no-project --python 3.12.13 packaging/tarball/build.py [--allow-dirty]

Builds the Linux bundle (packaging/bundle.py) and packs it with the desktop entry, icons,
licence and README into a reproducible tarball, then unpacks it and checks it: it runs,
writes nothing into itself, holds no paths from this machine, and updates itself the way
Self-update does (against a local stand-in for the release page offering the same tarball:
the folders are swapped, the old one is kept as .previous, and the app restarts).

Result: dist/wavematerial-<version>-linux-x86_64.tar.gz
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import sys
import tarfile
import threading
import time
import tomllib
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
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


def update_check(check: Path, unpacked: Path, tarball: Path, version: str) -> None:
    """Self-update the unpacked tarball from a local stand-in for the release page."""
    site = check / "site"
    (site / "releases").mkdir(parents=True)
    (site / "download").mkdir()
    shutil.copy2(tarball, site / "download" / tarball.name)
    digest = hashlib.sha256(tarball.read_bytes()).hexdigest()
    (site / "download" / "SHA256SUMS").write_text(f"{digest}  {tarball.name}\n", encoding="utf-8")
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(site)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    assets = [
        {"name": n, "size": (site / "download" / n).stat().st_size,
         "browser_download_url": f"{base}/download/{n}"}
        for n in (tarball.name, "SHA256SUMS")
    ]  # fmt: skip
    latest = {"tag_name": f"v{version}", "html_url": base, "assets": assets}
    (site / "releases" / "latest").write_text(json.dumps(latest), encoding="utf-8")

    (unpacked / "OLD-COPY").write_text("this folder is the old version\n", encoding="utf-8")
    started = check / "started.txt"
    env = {**os.environ, "WAVEMATERIAL_UPDATE_SERVER": base,
           "WAVEMATERIAL_SELFTEST_STARTED": str(started)}  # fmt: skip
    try:
        run(unpacked / "python" / "bin" / "python3.12", "-B", HERE / "update_selftest.py",
            check / "update-cache", env=env)  # fmt: skip
        for _ in range(60):
            if started.exists():
                break
            time.sleep(0.5)
    finally:
        server.shutdown()
    previous = unpacked.with_name(unpacked.name + ".previous")
    if not (previous / "OLD-COPY").exists() or (unpacked / "OLD-COPY").exists():
        sys.exit("Self-update did not swap the folders (the old one kept as .previous).")
    if not (unpacked / "bin" / "wavematerial").exists():
        sys.exit("Self-update left no app in the folder.")
    if not started.exists():
        sys.exit("Self-update did not restart the app.")
    leftovers = sorted(p.name for p in check.iterdir() if p.name.endswith(".update"))
    if leftovers:
        sys.exit(f"Self-update left its unpacking folder behind: {leftovers}")
    note = started.read_text(encoding="utf-8").strip()
    print(f"Self-update: folders swapped, previous kept, app restarted ({note}).")


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:
        pass


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
    update_check(check, unpacked, tarball, version)
    shutil.rmtree(check)

    print(f"\nTarball: {tarball} ({tarball.stat().st_size / 1e6:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
