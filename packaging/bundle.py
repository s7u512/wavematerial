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
It ships none of Microsoft's C++ runtime DLLs: Windows must have the Visual C++
Redistributable, at least the version BUILD-INFO.txt names (the installer checks).
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import io
import json
import os
import re
import shutil
import struct
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
VENDORED = HERE / "vendored.toml"

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
    kw.setdefault("check", True)
    return subprocess.run([str(c) for c in cmd], **kw)


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, check=True, capture_output=True, text=True
    ).stdout.strip()


def fetch(name: str, sha256: str, url: str) -> Path:
    """A download in dist/cache, fetched once and checked against its pinned sha256."""
    path = CACHE / name
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
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


def open_tar(archive: Path) -> tarfile.TarFile:
    if archive.suffix == ".zst":
        data = subprocess.run(["zstd", "-dc", archive], check=True, capture_output=True).stdout
        return tarfile.open(fileobj=io.BytesIO(data))
    return tarfile.open(archive)


def untar(archive: Path, dest: Path, keep=lambda name: True) -> None:
    with open_tar(archive) as tf:
        tf.extractall(dest, members=[m for m in tf.getmembers() if keep(m.name)], filter="data")


def read_member(archive: Path, member: str) -> bytes:
    """A file from an archive; "outer!inner" reads from an archive inside the archive."""
    outer, _, inner = member.partition("!")
    with open_tar(archive) as tf:
        f = tf.extractfile(outer) if outer in tf.getnames() else None
        if f is None:
            sys.exit(f"{archive.name} has no {outer}; update {VENDORED.name}.")
        data = f.read()
    if not inner:
        return data
    with tarfile.open(fileobj=io.BytesIO(data)) as tf:
        f = tf.extractfile(inner) if inner in tf.getnames() else None
        if f is None:
            sys.exit(f"{outer} in {archive.name} has no {inner}; update {VENDORED.name}.")
        return f.read()


def vendored(target: Target) -> tuple[list[str], list[dict]]:
    """The covered folders and the vendored libraries for a target (see vendored.toml)."""
    data = tomllib.loads(VENDORED.read_text(encoding="utf-8"))
    return data.get("covered", []), [x for x in data["lib"] if target.os in x["platforms"]]


def vendored_archive(lib: dict) -> Path:
    name = f"{lib['sha256'][:12]}-{lib['url'].rsplit('/', 1)[1]}"
    return fetch(f"vendored/{name}", lib["sha256"], lib["url"])


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def check_vendored(site: Path, covered: list[str], libs: list[dict]) -> None:
    """Every vendored library file is listed in vendored.toml, and every entry is still used."""
    files = sorted(p.relative_to(site).as_posix() for p in site.glob("*.libs/*") if p.is_file())

    def hits(patterns: list[str]) -> list[str]:
        return [f for f in files if any(fnmatch.fnmatchcase(f, pat) for pat in patterns)]

    stale = [x["name"] for x in libs if x["files"] and not hits(x["files"])]
    claimed = set(hits(covered)) | {f for x in libs for f in hits(x["files"])}
    unlisted = [f for f in files if f not in claimed]
    if stale or unlisted:
        sys.exit(
            f"{VENDORED.name} is out of date. Entries matching nothing: {stale}. "
            f"Vendored files it doesn't list: {unlisted}"
        )


def copy_vendored_licences(libs: list[dict], dest: Path) -> None:
    """Each library's licence texts in dest/<slug>/, and components.json for the credits page."""
    listed = []
    for lib in libs:
        if not lib["licence_files"]:  # source-only entries (build scripts)
            continue
        archive = vendored_archive(lib)
        folder = dest / slug(lib["name"])
        folder.mkdir(parents=True)
        for member in lib["licence_files"]:
            (folder / member.rsplit("!", 1)[-1].rsplit("/", 1)[-1]).write_bytes(
                read_member(archive, member)
            )
        if lib.get("credits", True):
            listed.append(
                {k: lib[k] for k in ("name", "version", "licence")} | {"key": slug(lib["name"])}
            )
    (dest / "components.json").write_text(json.dumps(listed, indent=1) + "\n", encoding="utf-8")


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


# Microsoft's C++ runtime, under its own (proprietary) licence, plus wheels' renamed copies
# (delvewheel names them like msvcp140-<hash>.dll).
MSVC_RUNTIME = re.compile(
    r"(vcruntime140(_1)?|msvcp140(_\w+)?|concrt140|vcomp140)(-[0-9a-f]+)?\.dll", re.IGNORECASE
)


def file_version(path: Path) -> tuple[int, int, int, int]:
    """A Windows DLL's file version, from its VS_FIXEDFILEINFO."""
    data = path.read_bytes()
    i = data.find(struct.pack("<I", 0xFEEF04BD))
    if i < 0:
        sys.exit(f"{path} has no version information.")
    ms, ls = struct.unpack_from("<II", data, i + 8)
    return (ms >> 16, ms & 0xFFFF, ls >> 16, ls & 0xFFFF)


def unvendor_msvc(root: Path) -> tuple[int, int, int, int]:
    """Remove Microsoft's C++ runtime DLLs; return the newest version removed.

    A renamed copy is removed too: the binaries that import it are pointed at the system
    DLL instead (the import name is a NUL-terminated string, and the plain name is shorter).
    """
    newest = (0, 0, 0, 0)
    for dll in [p for p in root.rglob("*") if MSVC_RUNTIME.fullmatch(p.name)]:
        newest = max(newest, file_version(dll))
        plain = MSVC_RUNTIME.fullmatch(dll.name)
        if plain.group(4):
            old = dll.name.encode() + b"\0"
            new = dll.name.removesuffix(".dll").removesuffix(plain.group(4)).encode() + b".dll"
            new = new.ljust(len(old), b"\0")
            users = 0
            for pe in root.rglob("*"):
                if pe.suffix.lower() in (".pyd", ".dll") and pe != dll:
                    data = pe.read_bytes()
                    if old in data:
                        if data.count(old) != 1:
                            sys.exit(f"{pe} names {dll.name} more than once; patch it by hand.")
                        pe.write_bytes(data.replace(old, new))
                        users += 1
            if not users:
                sys.exit(f"Nothing imports {dll.name}; check before removing it.")
        dll.unlink()
    return newest


# Windows ships DLLs under these names itself (Windows ML: Windows 11 24H2 has ONNX Runtime
# 1.17 as System32\onnxruntime.dll). A bundled DLL with the same name can lose to Windows'
# copy: then sherpa-onnx gets ONNX Runtime 1.17 and crashes. Bundled copies take a private
# name of the same length or shorter, and the binaries that import them are patched.
PRIVATE_NAMES = {"onnxruntime.dll": "wm-onnxrt.dll"}
WINDOWS_SHIPS = {"onnxruntime.dll", "onnxruntime_providers_shared.dll", "directml.dll"}


def privatise_dlls(root: Path) -> None:
    """Rename bundled DLLs that Windows also ships, and point their importers at the new name."""
    pes = [p for p in root.rglob("*") if p.suffix.lower() in (".pyd", ".dll")]
    for name, private in PRIVATE_NAMES.items():
        old = re.compile(re.escape(name.encode()) + b"\0", re.IGNORECASE)
        new = private.encode().ljust(len(name) + 1, b"\0")
        copies = [p for p in pes if p.name.lower() == name]
        if not copies:
            sys.exit(f"No bundled {name}; update PRIVATE_NAMES.")
        users = 0
        for pe in pes:
            if pe.name.lower() == name:  # its own export name doesn't affect loading
                continue
            data = pe.read_bytes()
            found = len(old.findall(data))
            if found > 1:
                sys.exit(f"{pe} names {name} more than once; patch it by hand.")
            if found:
                pe.write_bytes(old.sub(new, data))
                users += 1
        if not users:
            sys.exit(f"Nothing imports {name}; check before renaming it.")
        for dll in copies:
            dll.rename(dll.with_name(private))
    clash = [str(p.relative_to(root)) for p in root.rglob("*") if p.name.lower() in WINDOWS_SHIPS]
    if clash:
        sys.exit(f"Bundled DLLs named like Windows' own (add them to PRIVATE_NAMES): {clash}")


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
    needs = ""
    if windows:
        # sherpa-onnx-core's copies of its C API libraries, for command-line use; unused.
        remove(site, "Scripts")
        vcredist = ".".join(map(str, unvendor_msvc(root)))
        privatise_dlls(root)
        needs = f"Needs: Microsoft Visual C++ Redistributable (x64) {vcredist} or later\n"

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

    # 5b. Vendored native libraries: all accounted for, with their licence texts.
    covered, libs = vendored(target)
    check_vendored(site, covered, libs)
    copy_vendored_licences(libs, root / "licenses" / "vendored")

    # 6. Build record.
    commit = git("rev-parse", "HEAD") + (" (with uncommitted changes)" if dirty else "")
    (bundle / "BUILD-INFO.txt").write_text(
        f"WaveMaterial {version}\n"
        f"Source commit: {commit}\n"
        f"Python: {PYTHON} (python-build-standalone {PBS_RELEASE}, {target.triple})\n"
        f"Built: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}\n" + needs,
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
