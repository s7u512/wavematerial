# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""Make the USAGE.md screenshots and the README video (Linux only; maintainers' tool).

    uv run --no-project --python 3.12.13 --with playwright --with pillow \\
        scripts/demo/make.py {check,screenshots,video}

- check: transcribe the two demo recordings once and print the transcripts (to choose
  what the video edits).
- screenshots: the shots listed in SHOTS, into demo/usage/ (1920x1080, 300 ppi).
- video: the README video, dist/demo/wavematerial-demo.webm (VP9, about 60 s).

The app's server (serve.py) runs under bubblewrap with a private /home/you, so every path
on screen is generic; the speech models are mounted read-only from this machine's models
folder (download them first), and the GPU is available. Playwright drives the system
Chromium headless. Sample audio: one minute (3:00-4:00) of Act I of the LibriVox dramatic
reading of Chekhov's "The Seagull" (translated by Marian Fell; LibriVox recordings are in
the public domain), downloaded from archive.org into dist/cache/demo/ and checked against
its SHA-1. Its speakers are known from the LibriVox cast: Masha (read by Philippa),
Medviedenko (Ernst Pattynama), Sorin (Glenn Simonsen), and the stage directions (Hannah
Dowell). Needs: bwrap, chromium, ffmpeg, and the repo's `uv sync` environment.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CACHE = REPO / "dist" / "cache" / "demo"
WORK = REPO / "dist" / "demo" / "work"
OUT_VIDEO = REPO / "dist" / "demo" / "wavematerial-demo.webm"
SHOTS_DIR = REPO / "demo" / "usage"
MODELS = Path.home() / ".local" / "share" / "wavematerial" / "models"
SANDBOX_HOME = Path("/home/you")
CHROMIUM = "/usr/bin/chromium"
ARCHIVE = "https://archive.org/download/seagull_0903_librivox"
# (file on archive.org, its SHA-1, the name it gets in the demo, start and length in seconds)
AUDIO = [
    ("theseagull_1_chekhov_64kb.mp3", "6c7169ed68faffc2ac21b7e1ce6a00f51d12d1e5",
     "The Seagull - Act I, excerpt.mp3", 180, 60),
]  # fmt: skip
SPEAKERS = "2", "4"  # Masha, Medviedenko, Sorin, and the stage directions
KEY_TERM = "Sorin"  # spoken in the excerpt


def log(msg: str) -> None:
    print(f"[demo] {msg}", flush=True)


def fetch_audio() -> list[Path]:
    CACHE.mkdir(parents=True, exist_ok=True)
    out = []
    for name, sha1, *_ in AUDIO:
        path = CACHE / name
        if not path.exists():
            log(f"downloading {name}")
            part = path.with_suffix(".part")
            urllib.request.urlretrieve(f"{ARCHIVE}/{name}", part)
            part.rename(path)
        if hashlib.sha1(path.read_bytes()).hexdigest() != sha1:
            sys.exit(f"{path} doesn't match its SHA-1 on archive.org; delete it.")
        out.append(path)
    return out


def make_home(name: str, fresh: bool = True) -> Path:
    """A home folder for the sandbox, with the recordings in ~/Recordings."""
    home = WORK / name
    if fresh and home.exists():
        shutil.rmtree(home)
    (home / "Recordings").mkdir(parents=True, exist_ok=True)
    (home / "Documents").mkdir(exist_ok=True)
    (home / "Data").mkdir(exist_ok=True)
    for src, (_, _, shown, start, length) in zip(fetch_audio(), AUDIO, strict=True):
        if not (home / "Recordings" / shown).exists():
            subprocess.run(
                ["ffmpeg", "-v", "error", "-y", "-ss", str(start), "-t", str(length), "-i",
                 str(src), "-c", "copy", str(home / "Recordings" / shown)], check=True,
            )  # fmt: skip
    return home


def bwrap(home: Path, models: bool, env: dict[str, str] | None = None) -> list[str]:
    """The sandbox: the system read-only, /home/you private, the GPU and this repo visible."""
    python = Path(os.path.realpath(REPO / ".venv" / "bin" / "python"))
    uv_python = python.parents[1]  # the uv-managed Python the venv points at
    cmd = [
        "bwrap", "--ro-bind", "/", "/", "--dev-bind", "/dev", "/dev", "--ro-bind", "/sys",
        "/sys", "--proc", "/proc", "--tmpfs", "/tmp", "--tmpfs", "/home",
        "--bind", str(home), str(SANDBOX_HOME), "--ro-bind", str(REPO), str(REPO),
        "--ro-bind", str(uv_python), str(uv_python), "--chdir", str(SANDBOX_HOME),
        "--setenv", "HOME", str(SANDBOX_HOME), "--setenv", "USER", "you",
        "--setenv", "PYTHONDONTWRITEBYTECODE", "1", "--die-with-parent",
    ]  # fmt: skip
    for var in [v for v in os.environ if v.startswith("XDG_") and v.endswith(("_HOME", "_DIR"))]:
        cmd += ["--unsetenv", var]
    if models:
        target = SANDBOX_HOME / ".local" / "share" / "wavematerial" / "models"
        cmd += ["--ro-bind", str(MODELS), str(target)]
    for key, value in (env or {}).items():
        cmd += ["--setenv", key, value]
    return cmd


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server:
    """serve.py in the sandbox; `url` opens a page with the access token."""

    def __init__(self, home: Path, models: bool = True, env=None, pretend: str | None = None):
        self.port = free_port()
        args = ["--port", str(self.port)] + (["--pretend-install", pretend] if pretend else [])
        python = str(REPO / ".venv" / "bin" / "python")
        self.proc = subprocess.Popen(
            [*bwrap(home, models, env), python, "-B", str(HERE / "serve.py"), *args],
            stdout=subprocess.PIPE, text=True,
        )  # fmt: skip
        assert self.proc.stdout is not None
        line = self.proc.stdout.readline()
        if not line.startswith("READY"):
            self.stop()
            sys.exit(f"The demo server didn't start: {line!r}")

    def url(self, path: str = "/") -> str:
        sep = "&" if "?" in path else "?"
        return f"http://127.0.0.1:{self.port}{path}{sep}token=demo"

    def stop(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()


def check() -> int:
    """Transcribe both recordings once (with the CLI, in the sandbox) and print them."""
    if not MODELS.is_dir():
        sys.exit(f"No models in {MODELS}; download them first (`wavematerial models`).")
    home = make_home("check", fresh=False)
    python = str(REPO / ".venv" / "bin" / "python")
    for _, _, shown, *_ in AUDIO:
        out = SANDBOX_HOME / "out" / Path(shown).stem
        if (home / "out" / Path(shown).stem / "outputs" / "transcript.txt").exists():
            continue
        log(f"transcribing {shown}")
        audio = str(SANDBOX_HOME / "Recordings" / shown)
        cmd = [python, "-B", "-m", "wavematerial", "transcribe", audio, "--out", str(out),
               "--min-speakers", SPEAKERS[0], "--max-speakers", SPEAKERS[1],
               "--key-term", KEY_TERM]  # fmt: skip
        started = time.monotonic()
        subprocess.run([*bwrap(home, True), *cmd], check=True)
        log(f"took {time.monotonic() - started:.0f} s")
    for _, _, shown, *_ in AUDIO:
        text = (home / "out" / Path(shown).stem / "outputs" / "transcript.txt").read_text("utf-8")
        print(f"\n===== {shown} =====\n{text}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("what", choices=("check", "screenshots", "video"))
    args = ap.parse_args()
    if sys.platform != "linux" or not shutil.which("bwrap"):
        sys.exit("This needs Linux with bubblewrap (bwrap).")
    if args.what == "check":
        return check()
    from demo_shots import screenshots, video  # noqa: PLC0415 (needs playwright)

    return screenshots() if args.what == "screenshots" else video()


if __name__ == "__main__":
    sys.exit(main())
