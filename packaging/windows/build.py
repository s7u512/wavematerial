# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""Build the Windows installer, on Linux, with Inno Setup under Wine.

    uv run --no-project --python 3.12.13 packaging/windows/build.py [--allow-dirty]

Builds the Windows bundle (packaging/bundle.py --target windows), installs Inno Setup into
the build bottle if needed, compiles wavematerial.iss, then test-installs the result in the
bottle: it runs on Microsoft's C++ runtime (not Wine's), writes nothing into its install
folder, runs sherpa-onnx with Windows' older onnxruntime.dll already loaded, and
uninstalls cleanly; and an installer that asks for a newer runtime than the
bottle has refuses to install.

The bottle needs Microsoft's Visual C++ Redistributable (x64), as users' machines do;
the build stops and says how to install it if it is missing.

Result: dist/WaveMaterial-<version>-windows-x86_64-setup.exe
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bundle import REPO, Wine, fetch, run, snapshot  # noqa: E402 (needs the path above)

HERE = Path(__file__).resolve().parent
INNO = "6.7.4"
INNO_SHA256 = "a549929319f9120716677c685535ca4671e4b937b5fdc87e2585f32d8eb30e8c"
INNO_URL = f"https://github.com/jrsoftware/issrc/releases/download/is-{INNO.replace('.', '_')}"
INNO_DIR = "C:\\wm\\innosetup"
VCREDIST_KEY = "HKLM\\SOFTWARE\\Microsoft\\VisualStudio\\14.0\\VC\\Runtimes\\x64"
# Load Microsoft's runtime DLLs (installed by its redistributable), never Wine's own.
MS_RUNTIME = "msvcp140,msvcp140_1,msvcp140_2,vcruntime140,vcruntime140_1,concrt140=n"
# ONNX Runtime 1.17.1, the version Windows 11 24H2 ships as System32\onnxruntime.dll, and
# the voice detector model, for the DLL clash test.
OLD_ORT = "microsoft.ml.onnxruntime.1.17.1.nupkg"
OLD_ORT_SHA256 = "60493669633f99542a0a3e4dd17bfa9542cbfcd9852ef672f8c36ce6a9d2d935"
OLD_ORT_URL = f"https://api.nuget.org/v3-flatcontainer/microsoft.ml.onnxruntime/1.17.1/{OLD_ORT}"
VAD = "silero_vad.onnx"
VAD_SHA256 = "9e2449e1087496d8d4caba907f23e0bd3f78d91fa552479bb9c23ac09cbb1fd6"
VAD_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx"


def old_onnxruntime() -> tuple[Path, Path]:
    """The old onnxruntime.dll and the VAD model, in dist/cache/test."""
    nupkg = fetch(f"test/{OLD_ORT}", OLD_ORT_SHA256, OLD_ORT_URL)
    dll = nupkg.parent / "onnxruntime-1.17.1" / "onnxruntime.dll"
    if not dll.exists():
        dll.parent.mkdir(exist_ok=True)
        with zipfile.ZipFile(nupkg) as z:
            dll.write_bytes(z.read("runtimes/win-x64/native/onnxruntime.dll"))
    return fetch(f"test/{VAD}", VAD_SHA256, VAD_URL), dll


def numeric(version: str) -> str:
    """Windows' four-part version: 1.0.0 -> 1.0.0.0, 1.1.0.dev0 -> 1.1.0.0."""
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

    info = (bundle / "BUILD-INFO.txt").read_text(encoding="utf-8")
    min_vcredist = re.search(r"Redistributable \(x64\) ([\d.]+) or later", info).group(1)

    wine = Wine()
    has = wine.run("reg", "query", VCREDIST_KEY, capture_output=True, text=True, check=False)
    if has.returncode != 0:
        sys.exit(
            "The build bottle lacks Microsoft's Visual C++ Redistributable (x64), which the test "
            f"install needs. Download vc_redist.x64.exe from Microsoft and run it with\n"
            f"  WINEPREFIX={wine.prefix} {wine.wine} vc_redist.x64.exe /install /quiet /norestart"
        )
    iscc = ensure_inno(wine)

    def compile_installer(*defines: str) -> None:
        wine.run(
            iscc, "/Q",
            f"/DAppVersion={version}", f"/DNumericVersion={numeric(version)}",
            f"/DBundleDir={Wine.path(bundle)}", f"/DRepoDir={Wine.path(REPO)}",
            f"/DOutputDir={Wine.path(out)}", *defines, HERE / "wavematerial.iss",
        )  # fmt: skip

    compile_installer(f"/DMinVCRedist={min_vcredist}")
    setup = out / f"WaveMaterial-{version}-windows-x86_64-setup.exe"

    # Test install into the bottle's per-user programs folder, then uninstall.
    users = wine.prefix / "drive_c" / "users"
    (user,) = [d for d in users.iterdir() if d.name not in ("Public", "steamuser")] or [
        users / "steamuser"
    ]
    app = user / "AppData" / "Local" / "Programs" / "WaveMaterial"
    if app.exists():
        shutil.rmtree(app)
    wine.env["WINEDLLOVERRIDES"] += ";" + MS_RUNTIME
    wine.run(setup, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART")
    if not (app / "python" / "pythonw.exe").exists():
        sys.exit(f"The installer did not install into {app}.")
    before = snapshot(app)
    python = app / "python" / "python.exe"
    wine.run(python, "-m", "wavematerial", "--version")
    wine.run(python, "-c", "import av, numpy.fft, webview, sherpa_onnx, transcribe_cpp, docx")
    wine.run(python, "-B", HERE / "onnxruntime_clash.py", *old_onnxruntime())
    written = snapshot(app) - before
    if written:
        sys.exit(f"Running the installed app wrote into its folder: {sorted(written)[:10]}")
    wine.run(app / "unins000.exe", "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART")
    subprocess.run([wine.wine.parent / "wineserver", "-w"], env=wine.env, check=False)
    if app.exists() and any(app.iterdir()):
        sys.exit(f"Uninstalling left files in {app}: {sorted(snapshot(app))[:10]}")

    # An installer that needs a newer runtime than the bottle has must refuse to install.
    probe = f"WaveMaterial-{version}-vcredist-check"
    compile_installer("/DMinVCRedist=99.0.0.0", "/DCompression=none", f"/DOutputName={probe}")
    refused = wine.run(out / f"{probe}.exe", "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                       check=False)  # fmt: skip
    (out / f"{probe}.exe").unlink()
    if refused.returncode == 0 or app.exists() and any(app.iterdir()):
        sys.exit("The installer did not refuse to install without the required C++ runtime.")
    wine.stop()

    print(f"\nInstaller: {setup} ({setup.stat().st_size / 1e6:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
