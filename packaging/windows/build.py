# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""Build the Windows installer, on Linux, with Inno Setup under Wine.

    uv run --no-project --python 3.12.13 packaging/windows/build.py [--allow-dirty]

Builds the Windows bundle (packaging/bundle.py --target windows), installs Inno Setup into
the build bottle if needed, compiles wavematerial.iss, then test-installs the result in the
bottle: it runs, writes nothing into its install folder, and uninstalls cleanly.

Result: dist/WaveMaterial-<version>-windows-x86_64-setup.exe
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bundle import REPO, Wine, fetch, run, snapshot  # noqa: E402 (needs the path above)

HERE = Path(__file__).resolve().parent
INNO = "6.7.4"
INNO_SHA256 = "a549929319f9120716677c685535ca4671e4b937b5fdc87e2585f32d8eb30e8c"
INNO_URL = f"https://github.com/jrsoftware/issrc/releases/download/is-{INNO.replace('.', '_')}"
INNO_DIR = "C:\\wm\\innosetup"


def numeric(version: str) -> str:
    """Windows' four-part version: 0.1.0.dev0 -> 0.1.0.0."""
    parts = [int(re.match(r"\d+", p).group()) for p in version.split(".")[:3]]
    return ".".join(map(str, parts + [0] * (4 - len(parts))))


def ensure_inno(wine: Wine) -> Path:
    iscc = wine.prefix / "drive_c" / "wm" / "innosetup" / "ISCC.exe"
    if not iscc.exists():
        setup = fetch(f"innosetup-{INNO}.exe", INNO_SHA256, f"{INNO_URL}/innosetup-{INNO}.exe")
        wine.run(setup, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/CURRENTUSER", "/NORESTART",
                 "/NOICONS", f"/DIR={INNO_DIR}")  # fmt: skip
    return iscc


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--allow-dirty", action="store_true", help="build from uncommitted changes")
    args = ap.parse_args()

    version = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]
    dirty = ["--allow-dirty"] if args.allow_dirty else []
    run(sys.executable, REPO / "packaging" / "bundle.py", "--target", "windows", *dirty)
    bundle = REPO / "dist" / "bundle" / f"wavematerial-{version}-windows-x86_64"
    out = REPO / "dist"

    wine = Wine()
    iscc = ensure_inno(wine)
    wine.run(
        iscc, "/Q",
        f"/DAppVersion={version}", f"/DNumericVersion={numeric(version)}",
        f"/DBundleDir={Wine.path(bundle)}", f"/DRepoDir={Wine.path(REPO)}",
        f"/DOutputDir={Wine.path(out)}", HERE / "wavematerial.iss",
    )  # fmt: skip
    setup = out / f"WaveMaterial-{version}-windows-x86_64-setup.exe"

    # Test install into the bottle's per-user programs folder, then uninstall.
    users = wine.prefix / "drive_c" / "users"
    (user,) = [d for d in users.iterdir() if d.name not in ("Public", "steamuser")] or [
        users / "steamuser"
    ]
    app = user / "AppData" / "Local" / "Programs" / "WaveMaterial"
    if app.exists():
        shutil.rmtree(app)
    wine.run(setup, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART")
    if not (app / "python" / "pythonw.exe").exists():
        sys.exit(f"The installer did not install into {app}.")
    before = snapshot(app)
    wine.run(app / "python" / "python.exe", "-m", "wavematerial", "--version")
    wine.run(app / "python" / "python.exe", "-c", "import av, webview, sherpa_onnx, docx")
    written = snapshot(app) - before
    if written:
        sys.exit(f"Running the installed app wrote into its folder: {sorted(written)[:10]}")
    wine.run(app / "unins000.exe", "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART")
    subprocess.run([wine.wine.parent / "wineserver", "-w"], env=wine.env, check=False)
    if app.exists() and any(app.iterdir()):
        sys.exit(f"Uninstalling left files in {app}: {sorted(snapshot(app))[:10]}")
    wine.stop()

    print(f"\nInstaller: {setup} ({setup.stat().st_size / 1e6:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
