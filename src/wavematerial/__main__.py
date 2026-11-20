# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""Command-line entry point (`wavematerial`)."""

from __future__ import annotations

import argparse
import logging
import sys
import time

from wavematerial import __version__
from wavematerial.config import Paths, load_settings
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wavematerial")
    parser.add_argument("--version", action="version", version=f"wavematerial {__version__}")
    sub = parser.add_subparsers(dest="command")
    p_models = sub.add_parser("models", help="download the speech models, or check them")
    p_models.add_argument("--verify", action="store_true", help="check every file's checksum")
    p_models.set_defaults(func=_cmd_models)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    if args.command is None:
        print(
            f"wavematerial {__version__}: the app is not built yet. "
            "Available: `wavematerial models`.",
            file=sys.stderr,
        )
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
