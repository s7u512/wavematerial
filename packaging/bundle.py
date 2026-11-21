# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""Build the shared Linux bundle that every Linux package wraps.

    uv run --no-project --python 3.12.13 packaging/bundle.py [--allow-dirty]

Result: dist/bundle/wavematerial-<version>-linux-x86_64/
    bin/wavematerial    launcher (sets the environment, runs the bundled Python)
    python/             python-build-standalone 3.12.13 with the app and its locked
                        dependencies (including the `export` extra), precompiled
    BUILD-INFO.txt      what went in
plus dist/bundle/wavematerial-<version>-linux-x86_64.components.txt (bundled components
and their licences). The build fails if a component's licence is missing or not allowed.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path

PYTHON = "3.12.13"
PYVER = "3.12"
REPO = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent

# Parts of the standalone runtime the app never uses. `_dbm` is also a licence problem: it
# embeds Berkeley DB 6.0.19, which is AGPL-3.0. `_crypt` needs libcrypt.so.1, which many
# distributions no longer ship.
DROP = [
    "bin/2to3",
    f"bin/2to3-{PYVER}",
    "bin/idle3",
    f"bin/idle3.{PYVER[2:]}",
    "bin/pip",
    "bin/pip3",
    f"bin/pip{PYVER}",
    "bin/pydoc3",
    f"bin/pydoc{PYVER}",
    f"bin/python{PYVER}-config",
    "bin/python3-config",
    "include",
    "share",
    "lib/pkgconfig",
    "lib/itcl4.3.8",
    "lib/tcl9",
    "lib/tcl9.0",
    "lib/tk9.0",
    "lib/thread3.0.6",
    "lib/libtcl9.0.so",
    "lib/libtcl9tk9.0.so",
    f"lib/python{PYVER}/EXTERNALLY-MANAGED",
    f"lib/python{PYVER}/ensurepip",
    f"lib/python{PYVER}/idlelib",
    f"lib/python{PYVER}/tkinter",
    f"lib/python{PYVER}/turtledemo",
    f"lib/python{PYVER}/turtle.py",
    f"lib/python{PYVER}/lib2to3",
    f"lib/python{PYVER}/site-packages/pip",
    f"lib/python{PYVER}/site-packages/pip-*.dist-info",
    f"lib/python{PYVER}/lib-dynload/_dbm.*.so",
    f"lib/python{PYVER}/lib-dynload/_crypt.*.so",
    f"lib/python{PYVER}/lib-dynload/_tkinter.*.so",
    f"lib/python{PYVER}/config-{PYVER}-x86_64-linux-gnu/python.o",
]

LAUNCHER = """\
#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
# WaveMaterial launcher: runs the bundled Python, ignoring any Python set up on this system.
here=$(dirname "$(readlink -f "$0")")
unset PYTHONHOME PYTHONPATH PYTHONSTARTUP PYTHONUSERBASE
# Nothing is written inside the install directory (bytecode is precompiled).
export PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONSAFEPATH=1
exec "$here/../python/bin/python{pyver}" -m wavematerial "$@"
"""


def run(*cmd: str | Path, **kw) -> subprocess.CompletedProcess:
    print("+", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run([str(c) for c in cmd], check=True, **kw)


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, check=True, capture_output=True, text=True
    ).stdout.strip()


def remove(root: Path, pattern: str) -> None:
    matches = list(root.glob(pattern))
    if not matches:
        sys.exit(f"Expected to drop {pattern}, but it is not in the runtime; update DROP.")
    for path in matches:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()


def snapshot(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*")}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--allow-dirty", action="store_true", help="build from uncommitted changes")
    args = ap.parse_args()

    if sys.platform != "linux":
        sys.exit("This script builds the Linux bundle and runs on Linux only.")
    dirty = git("status", "--porcelain")
    if dirty and not args.allow_dirty:
        sys.exit("The working tree has uncommitted changes; commit them or pass --allow-dirty.")

    version = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]
    name = f"wavematerial-{version}-linux-x86_64"
    out = REPO / "dist" / "bundle"
    bundle = out / name
    work = out / "work"
    for d in (bundle, work):
        if d.exists():
            shutil.rmtree(d)
    work.mkdir(parents=True)

    # 1. The standalone runtime (a fresh copy, not the developer's).
    run("uv", "python", "install", PYTHON, "--install-dir", work / "py", "--no-bin")
    (installed,) = (work / "py").glob(f"cpython-{PYTHON}-linux-x86_64-gnu")
    shutil.move(installed, bundle / "python")
    py = bundle / "python" / "bin" / f"python{PYVER}"
    pbs_build = (bundle / "python" / "BUILD").read_text(encoding="utf-8").strip()
    for pattern in DROP:
        remove(bundle / "python", pattern)

    # 2. The app and its locked dependencies, exactly as uv.lock pins them.
    reqs = work / "requirements.txt"
    run(
        "uv", "export", "--frozen", "--no-dev", "--extra", "export", "--no-emit-project",
        "--no-header", "--output-file", reqs, cwd=REPO, stdout=subprocess.DEVNULL,
    )  # fmt: skip
    run("uv", "build", "--wheel", "--out-dir", work / "wheel", cwd=REPO)
    (wheel,) = (work / "wheel").glob("wavematerial-*.whl")
    env = {**os.environ, "UV_NO_CONFIG": "1"}
    run("uv", "pip", "install", "--python", py, "--require-hashes", "--no-deps", "-r", reqs,
        env=env)  # fmt: skip
    run("uv", "pip", "install", "--python", py, "--no-deps", wheel, env=env)

    # 3. Precompile everything. Unchecked-hash bytecode is never re-validated against the
    #    sources, so it stays valid whatever timestamps the package format keeps.
    for cache in list((bundle / "python").rglob("__pycache__")):
        shutil.rmtree(cache)
    run(py, "-m", "compileall", "-q", "-j0", "--invalidation-mode", "unchecked-hash",
        bundle / "python" / "lib" / f"python{PYVER}")  # fmt: skip

    # 4. Launcher and build record.
    (bundle / "bin").mkdir()
    launcher = bundle / "bin" / "wavematerial"
    launcher.write_text(LAUNCHER.format(pyver=PYVER), encoding="utf-8")
    launcher.chmod(0o755)
    commit = git("rev-parse", "HEAD") + (" (with uncommitted changes)" if dirty else "")
    (bundle / "BUILD-INFO.txt").write_text(
        f"WaveMaterial {version}\n"
        f"Source commit: {commit}\n"
        f"Python: {PYTHON} (python-build-standalone {pbs_build})\n"
        f"Built: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}\n",
        encoding="utf-8",
    )

    # 5. Licence guard, run inside the bundle so it sees exactly what ships.
    components = out / f"{name}.components.txt"
    run(py, "-I", "-B", HERE / "licence_check.py", components)

    # 6. Smoke test: it starts, imports the native parts, and writes nothing into itself.
    before = snapshot(bundle)
    run(launcher, "--version")
    run(py, "-B", "-c", "import av, gi, webview, sherpa_onnx, transcribe_cpp, docx, reportlab")
    written = snapshot(bundle) - before
    if written:
        sys.exit(f"Running the bundle wrote into it: {sorted(written)[:10]}")

    shutil.rmtree(work)
    size = sum(p.stat().st_size for p in bundle.rglob("*") if p.is_file() and not p.is_symlink())
    print(f"\nBundle: {bundle} ({size / 1e6:.0f} MB)\nComponents: {components}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
