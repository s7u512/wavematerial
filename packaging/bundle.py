# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""Build the shared bundle that every package wraps, for Linux or Windows.

    uv run --no-project --python 3.12.13 packaging/bundle.py [--target windows] [--allow-dirty]

Result: dist/bundle/wavematerial-<version>-<linux|windows>-x86_64/
    python/             python-build-standalone 3.12.13 with the app and its locked
                        dependencies (including the `export` extra), precompiled, and the
                        licence texts of the libraries built into the runtime (`licenses/`)
    bin/wavematerial    Linux: launcher (sets the environment, runs the bundled Python)
    wavematerial.ico    Windows: the icon for shortcuts (they run `python\\pythonw.exe -m
                        wavematerial`; `python312._pth` isolates the runtime instead)
    BUILD-INFO.txt      what went in
plus dist/bundle/wavematerial-<version>-<os>-x86_64.components.txt (bundled components and
their licences). The build fails if a component's licence is missing or not allowed, or if
the build machine's paths end up in the bundle.

Everything runs on Linux. The Windows bundle is assembled here (uv installs Windows wheels
on Linux); its compile, licence and smoke steps run its own Python under Wine (see `Wine`).
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tomllib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

PYTHON = "3.12.13"
PYVER = "3.12"
PBS_RELEASE = "20260807"
PBS_URL = "https://github.com/astral-sh/python-build-standalone/releases/download"
REPO = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
CACHE = REPO / "dist" / "cache"

# Listed in PYTHON.json but not shipped: the runtimes link OpenSSL 3, not 1.1 (the smoke test
# checks); zlib-ng's file is missing from the archive (it is under the zlib licence, which
# asks for its notice only in source distributions).
PBS_SKIP = {"licenses/LICENSE.openssl-1.1.txt", "licenses/LICENSE.zlib-ng.txt"}

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

# Windows: a ._pth file next to python.exe fixes sys.path and makes Python ignore PYTHONPATH,
# PYTHONHOME and the registry, for the app and every worker it starts. `import site` keeps
# site-packages (and runs sitecustomize, which turns bytecode writing off).
WIN_PTH = f"python{PYVER.replace('.', '')}.zip\nDLLs\nLib\nLib\\site-packages\nimport site\n"
WIN_SITECUSTOMIZE = """\
# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
# Part of WaveMaterial's bundled runtime: nothing is written inside the install directory
# (bytecode is precompiled).
import sys

sys.dont_write_bytecode = True
"""


@dataclass(frozen=True)
class Target:
    os: str
    triple: str
    runtime_sha256: str  # install_only_stripped archive
    full: str  # suffix of the "full" archive, fetched only for its licence texts
    full_sha256: str
    stdlib: str  # inside python/
    keep_bin: frozenset[str] = field(default_factory=frozenset)
    # Parts of the runtime the app never uses (globs inside python/).
    drop: tuple[str, ...] = ()

    def archive(self, kind: str) -> str:
        return f"cpython-{PYTHON}+{PBS_RELEASE}-{self.triple}-{kind}"


LINUX = Target(
    os="linux",
    triple="x86_64-unknown-linux-gnu",
    runtime_sha256="506191be3ee7bd190a8834dcdc1b3bc70aab50608deccc711935aa007239cabd",
    full="pgo+lto-full.tar.zst",
    full_sha256="5e69a659d2c126e0760ef951d052509f845a9d55f119ab03a3863811c58a5f49",
    stdlib=f"lib/python{PYVER}",
    keep_bin=frozenset({"python", "python3", f"python{PYVER}"}),
    # `_dbm` embeds Berkeley DB 6.0.19 (Sleepycat licence), whose binaries must come with an
    # offer of its source; leaving it out avoids that. `_crypt` needs libcrypt.so.1, which
    # many distributions no longer ship.
    drop=(
        "include",
        "share",
        "lib/pkgconfig",
        "lib/itcl*",
        "lib/tcl9*",
        "lib/tk9*",
        "lib/thread*",
        "lib/libtcl*.so",
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
    ),
)

WINDOWS = Target(
    os="windows",
    triple="x86_64-pc-windows-msvc",
    runtime_sha256="18bcc65b17921806b72cdc88bcf000bf67a2c99a8fc381fe1629f2b9ba56858d",
    full="pgo-full.tar.zst",
    full_sha256="98a0c5295bd53bef39147ffeb0a50d45df12b407e145c1799411cca53dcef90c",
    stdlib="Lib",
    drop=(
        "include",
        "libs",
        "tcl",
        "Scripts",
        "DLLs/_tkinter.pyd",
        "DLLs/tcl86t.dll",
        "DLLs/tk86t.dll",
        "DLLs/_test*.pyd",
        "DLLs/_ctypes_test.pyd",
        "Lib/ensurepip",
        "Lib/idlelib",
        "Lib/tkinter",
        "Lib/turtledemo",
        "Lib/turtle.py",
        "Lib/lib2to3",
        "Lib/site-packages/pip",
        "Lib/site-packages/pip-*.dist-info",
    ),
)

TARGETS = {"linux": LINUX, "windows": WINDOWS}


class Wine:
    """Runs Windows programs in the build bottle (see plan notes; Bottles, runner wine-adobe).

    WM_WINE (the runner's `wine`) and WM_WINEPREFIX (the bottle) override the defaults.
    """

    def __init__(self) -> None:
        bottles = Path.home() / ".local/share/bottles"
        self.wine = Path(os.environ.get("WM_WINE", bottles / "runners/wine-adobe/bin/wine"))
        prefix = os.environ.get("WM_WINEPREFIX", bottles / "bottles/wavematerial-win")
        self.prefix = Path(prefix)
        if not self.wine.exists() or not self.prefix.is_dir():
            sys.exit(f"Wine runner {self.wine} or bottle {self.prefix} not found.")
        # No .NET or Internet Explorer prompts, and no browser tabs opened on the host.
        self.env = {
            **os.environ,
            "WINEPREFIX": str(self.prefix),
            "WINEDEBUG": "-all",
            "WINEDLLOVERRIDES": "mscoree,mshtml=;winebrowser.exe=d",
        }

    @staticmethod
    def path(p: Path) -> str:
        """A Linux path as Wine sees it (drive Z: is /)."""
        return "Z:" + str(p).replace("/", "\\")

    def run(self, exe: Path | str, *args: str | Path, **kw) -> subprocess.CompletedProcess:
        exe = self.path(exe) if isinstance(exe, Path) else exe
        args = [self.path(a) if isinstance(a, Path) else a for a in args]
        return run(self.wine, exe, *args, env=self.env, **kw)

    def stop(self) -> None:
        subprocess.run([self.wine.parent / "wineserver", "-k"], env=self.env, check=False)


def run(*cmd: str | Path, **kw) -> subprocess.CompletedProcess:
    print("+", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run([str(c) for c in cmd], check=True, **kw)


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, check=True, capture_output=True, text=True
    ).stdout.strip()


def fetch(name: str, sha256: str, url: str) -> Path:
    """A download in dist/cache, fetched once and checked against its pinned sha256."""
    path = CACHE / name
    if not path.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        part = path.with_name(path.name + ".part")
        run("curl", "-fsSL", "--output", part, url)
        part.rename(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != sha256:
        sys.exit(f"{path} has sha256 {digest}, expected {sha256}; delete it.")
    return path


def pbs(target: Target, kind: str, sha256: str) -> Path:
    name = target.archive(kind)
    return fetch(name, sha256, f"{PBS_URL}/{PBS_RELEASE}/{name.replace('+', '%2B')}")


def untar(archive: Path, dest: Path, keep=lambda name: True) -> None:
    if archive.suffix == ".zst":
        data = subprocess.run(["zstd", "-dc", archive], check=True, capture_output=True).stdout
        tf = tarfile.open(fileobj=io.BytesIO(data))
    else:
        tf = tarfile.open(archive)
    with tf:
        tf.extractall(dest, members=[m for m in tf.getmembers() if keep(m.name)], filter="data")


def remove(root: Path, pattern: str) -> None:
    matches = list(root.glob(pattern))
    if not matches:
        sys.exit(f"Expected to drop {pattern}, but it is not in the runtime; update drop.")
    for path in matches:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()


def licence_paths(full: Path, present: list[str]) -> list[str]:
    """CPython's licence, and those of the libraries in the extension modules present."""
    info = json.loads((full / "PYTHON.json").read_text(encoding="utf-8"))
    paths = {info["license_path"]}
    for name in present:
        for variant in info["build_info"]["extensions"].get(name, []):
            paths.update(variant.get("license_paths") or [])
    return sorted(paths - PBS_SKIP)


def snapshot(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*")}


def leaks(root: Path, needles: list[bytes]) -> list[str]:
    """Files under root that contain any of the needles (the build machine's paths)."""
    found = []
    for p in root.rglob("*"):
        if p.is_file() and not p.is_symlink():
            data = p.read_bytes()
            if any(n in data for n in needles):
                found.append(str(p.relative_to(root)))
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--target", choices=sorted(TARGETS), default="linux")
    ap.add_argument("--allow-dirty", action="store_true", help="build from uncommitted changes")
    args = ap.parse_args()
    target = TARGETS[args.target]
    windows = target is WINDOWS

    if sys.platform != "linux":
        sys.exit("This script runs on Linux (it builds the Windows bundle there too).")
    dirty = git("status", "--porcelain")
    if dirty and not args.allow_dirty:
        sys.exit("The working tree has uncommitted changes; commit them or pass --allow-dirty.")
    wine = Wine() if windows else None

    version = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]
    name = f"wavematerial-{version}-{target.os}-x86_64"
    out = REPO / "dist" / "bundle"
    bundle = out / name
    work = out / f"work-{target.os}"
    for d in (bundle, work):
        if d.exists():
            shutil.rmtree(d)
    work.mkdir(parents=True)
    bundle.mkdir()
    root = bundle / "python"
    stdlib = root / target.stdlib
    site = stdlib / "site-packages"

    # 1. The standalone runtime, straight from its pinned archive.
    untar(pbs(target, "install_only_stripped.tar.gz", target.runtime_sha256), bundle)
    for pattern in target.drop:
        remove(root, pattern)

    # 2. The app and its locked dependencies, exactly as uv.lock pins them.
    reqs = work / "requirements.txt"
    run(
        "uv", "export", "--frozen", "--no-dev", "--extra", "export", "--no-emit-project",
        "--no-header", "--output-file", reqs, cwd=REPO, stdout=subprocess.DEVNULL,
    )  # fmt: skip
    run("uv", "build", "--wheel", "--out-dir", work / "wheel", cwd=REPO)
    (wheel,) = (work / "wheel").glob("wavematerial-*.whl")
    env = {**os.environ, "UV_NO_CONFIG": "1"}
    if windows:
        into = ["--target", site, "--python-platform", target.triple, "--python-version", PYTHON]
    else:
        into = ["--python", root / "bin" / f"python{PYVER}"]
    run("uv", "pip", "install", *into, "--require-hashes", "--no-deps", "-r", reqs, env=env)
    run("uv", "pip", "install", *into, "--no-deps", wheel, env=env)
    # Console scripts carry the build path in their shebangs; the launcher replaces them.
    # direct_url.json records where the wheel was installed from.
    for script in (root / "bin").iterdir() if not windows else (site / "bin").glob("*"):
        if script.name not in target.keep_bin:
            script.unlink()
    if windows and (site / "bin").exists():
        (site / "bin").rmdir()
    for record in site.glob("*.dist-info/direct_url.json"):
        record.unlink()

    # 3. Isolation and launch.
    if windows:
        (root / f"python{PYVER.replace('.', '')}._pth").write_text(WIN_PTH, encoding="utf-8")
        (stdlib / "sitecustomize.py").write_text(WIN_SITECUSTOMIZE, encoding="utf-8")
        shutil.copy2(REPO / "design" / "logo" / "app-icon.ico", bundle / "wavematerial.ico")

        def py(*a: str | Path, **kw) -> subprocess.CompletedProcess:
            return wine.run(root / "python.exe", *a, **kw)
    else:
        (bundle / "bin").mkdir()
        launcher = bundle / "bin" / "wavematerial"
        launcher.write_text(LAUNCHER.format(pyver=PYVER), encoding="utf-8")
        launcher.chmod(0o755)

        def py(*a: str | Path, **kw) -> subprocess.CompletedProcess:
            return run(root / "bin" / f"python{PYVER}", *a, **kw)

    # 4. Precompile everything. Unchecked-hash bytecode is never re-validated against the
    #    sources, so it stays valid whatever timestamps the package format keeps. The build
    #    path is stripped from the recorded file names (Python fills in the real one on import).
    for cache in list(root.rglob("__pycache__")):
        shutil.rmtree(cache)
    strip = Wine.path(bundle) if windows else str(bundle)
    py("-B", "-m", "compileall", "-q", "-f", "-j0", "--invalidation-mode", "unchecked-hash",
       "-s", strip, "-p", "", stdlib)  # fmt: skip

    # 5. Licence texts for what the runtime has built in (OpenSSL, SQLite, libffi, ...).
    full = work / "pbs-full"
    untar(
        pbs(target, target.full, target.full_sha256),
        full,
        lambda n: n == "python/PYTHON.json" or n.startswith("python/licenses/"),
    )
    info = json.loads((full / "python" / "PYTHON.json").read_text(encoding="utf-8"))
    probe = "import importlib.util as u, sys; print(*(m for m in sys.argv[1:] if u.find_spec(m)))"
    present = py("-I", "-B", "-c", probe, *info["build_info"]["extensions"],
                 capture_output=True, text=True).stdout.split()  # fmt: skip
    (root / "licenses").mkdir()
    for rel in licence_paths(full / "python", present):
        shutil.copy2(full / "python" / rel, root / "licenses" / Path(rel).name)

    # 6. Build record.
    commit = git("rev-parse", "HEAD") + (" (with uncommitted changes)" if dirty else "")
    (bundle / "BUILD-INFO.txt").write_text(
        f"WaveMaterial {version}\n"
        f"Source commit: {commit}\n"
        f"Python: {PYTHON} (python-build-standalone {PBS_RELEASE}, {target.triple})\n"
        f"Built: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}\n",
        encoding="utf-8",
    )

    # 7. Licence guard, run inside the bundle so it sees exactly what ships.
    components = out / f"{name}.components.txt"
    py("-I", "-B", HERE / "licence_check.py", components)

    # 8. Smoke test: it starts, imports the native parts, and writes nothing into itself.
    before = snapshot(bundle)
    if windows:
        py("-m", "wavematerial", "--version")
        native = "import av, webview, sherpa_onnx, transcribe_cpp, docx, reportlab, clr_loader"
    else:
        run(launcher, "--version")
        native = "import av, gi, webview, sherpa_onnx, transcribe_cpp, docx, reportlab"
    py("-c", native)
    py("-c", "import ssl; assert ssl.OPENSSL_VERSION.startswith('OpenSSL 3'), ssl.OPENSSL_VERSION")
    if windows:  # the ._pth file isolates the runtime from the environment
        check = "import sys; assert 'nowhere' not in str(sys.path) and sys.dont_write_bytecode"
        wine.env["PYTHONPATH"] = "C:\\nowhere"
        py("-c", check)
        del wine.env["PYTHONPATH"]
        wine.stop()
    written = snapshot(bundle) - before
    if written:
        sys.exit(f"Running the bundle wrote into it: {sorted(written)[:10]}")

    # 9. The build machine's paths must not ship.
    needles = [str(REPO).encode(), str(Path.home()).encode()]
    needles += [Wine.path(REPO).encode(), Wine.path(REPO).encode("utf-16-le")]
    found = leaks(bundle, needles)
    if found:
        sys.exit(f"Build paths found in the bundle: {found[:20]}")

    shutil.rmtree(work)
    size = sum(p.stat().st_size for p in bundle.rglob("*") if p.is_file() and not p.is_symlink())
    print(f"\nBundle: {bundle} ({size / 1e6:.0f} MB)\nComponents: {components}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
