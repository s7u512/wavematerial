# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""Command-line entry point (`wavematerial`)."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from wavematerial import __version__
from wavematerial.config import Paths, Settings, load_settings
from wavematerial.models.download import DownloadError, install, is_installed, verify
from wavematerial.models.manifest import load_manifest


def _progress_printer(name: str):
    last = [0.0]

    def show(done: int, total: int) -> None:
        now = time.monotonic()
        if now - last[0] < 0.5 and done < total:
            return
        last[0] = now
        pct = 100 * done / total if total else 100
        print(f"\r  {name}: {done / 1e6:,.0f} / {total / 1e6:,.0f} MB ({pct:.0f}%)", end="")
        if done >= total:
            print()

    return show


def _cmd_models(args: argparse.Namespace) -> int:
    paths = Paths.default()
    models_dir = paths.models_dir(load_settings(paths.settings_file))
    manifest = load_manifest()

    if args.verify:
        problems = [p for m in manifest for p in verify(m, models_dir)]
        for p in problems:
            print(p)
        print("All models are intact." if not problems else f"{len(problems)} problem(s).")
        return 1 if problems else 0

    missing = [m for m in manifest if not is_installed(m, models_dir)]
    if not missing:
        print(f"All {len(manifest)} models are installed in {models_dir}.")
        return 0
    total = sum(m.size for m in missing)
    print(f"Downloading {len(missing)} model(s), {total / 1e9:.1f} GB, into {models_dir}")
    for m in missing:
        try:
            install(m, models_dir, paths.cache_dir, _progress_printer(m.name))
        except DownloadError as exc:
            print(f"\n{exc}", file=sys.stderr)
            return 1
    print("Done.")
    return 0


def _cmd_transcribe(args: argparse.Namespace) -> int:
    from wavematerial.engine.decode import DecodeError
    from wavematerial.engine.pipeline import STAGES, JobSettings, run
    from wavematerial.engine.text import GpuFailure
    from wavematerial.preflight import choose, detect_devices, in_wsl, physical_cores

    paths = Paths.default()
    settings = load_settings(paths.settings_file)
    if args.device:
        settings = Settings(**{**settings.__dict__, "device": args.device})
    models_dir = paths.models_dir(settings)
    manifest = load_manifest()
    if not all(is_installed(m, models_dir) for m in manifest):
        print("The speech models are not installed. Run `wavematerial models` first.")
        return 1

    source = Path(args.file)
    job_dir = Path(args.out) if args.out else Path.cwd() / f"{source.stem}.wavematerial"
    job = JobSettings(
        min_speakers=args.min_speakers or settings.min_speakers,
        max_speakers=args.max_speakers or settings.max_speakers,
        key_terms=tuple(args.key_term or settings.key_terms),
    )
    devices = detect_devices()
    choice = choose(devices, settings, cores=physical_cores(), wsl=in_wsl())
    print(f"{choice.reason} ({choice.description}, {choice.threads} threads)")

    last = [""]

    def progress(stage: str, fraction: float) -> None:
        line = f"[{STAGES.index(stage) + 1}/{len(STAGES)}] {stage}: {fraction:.0%}"
        if line != last[0]:
            print("\r" + line.ljust(40), end="" if fraction < 1 else "\n")
            last[0] = line

    started = time.monotonic()
    try:
        try:
            transcript = run(
                source,
                job_dir,
                choice=choice,
                models=manifest,
                models_dir=models_dir,
                settings=job,
                progress=progress,
            )
        except GpuFailure as exc:
            print(f"\nThe GPU failed ({exc}). Continuing on the CPU from the last saved stage.")
            choice = choose(
                devices, settings, cores=physical_cores(), unreliable={choice.device_id}
            )
            transcript = run(
                source,
                job_dir,
                choice=choice,
                models=manifest,
                models_dir=models_dir,
                settings=job,
                progress=progress,
            )
    except DecodeError as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 1
    elapsed = time.monotonic() - started
    print(
        f"Done in {elapsed:.0f} s ({elapsed / transcript.duration:.2f} x audio length): "
        f"{len(transcript.speakers)} speakers, {len(transcript.turns)} turns. "
        f"Outputs in {job_dir / 'outputs'}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wavematerial")
    parser.add_argument("--version", action="version", version=f"wavematerial {__version__}")
    sub = parser.add_subparsers(dest="command")
    p_models = sub.add_parser("models", help="download the speech models, or check them")
    p_models.add_argument("--verify", action="store_true", help="check every file's checksum")
    p_models.set_defaults(func=_cmd_models)
    p_tr = sub.add_parser("transcribe", help="transcribe one audio or video file")
    p_tr.add_argument("file")
    p_tr.add_argument("--out", help="job folder (default: ./<name>.wavematerial)")
    p_tr.add_argument("--device", help='"auto", "cpu", or "vulkan:<device id>"')
    p_tr.add_argument("--min-speakers", type=int)
    p_tr.add_argument("--max-speakers", type=int)
    p_tr.add_argument("--key-term", action="append", help="a name or term to expect (repeatable)")
    p_tr.set_defaults(func=_cmd_transcribe)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    if args.command is None:
        print(
            f"wavematerial {__version__}: the app is not built yet. "
            "Available: `wavematerial models` and `wavematerial transcribe`.",
            file=sys.stderr,
        )
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
