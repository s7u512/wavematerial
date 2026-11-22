# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""The app's server without a window, for the demo scripts (see make.py).

Runs inside make.py's sandbox, whose home is /home/you, so every path the pages show is a
generic one. The window's native hooks are stubbed: the file picker returns the demo
recordings, the folder picker /home/you/Data, and saving goes to /home/you/Documents.

    python serve.py --port N [--pretend-install tarball|windows]

--pretend-install shows the update buttons as an installed copy would (nothing is ever
installed: the demo never applies an update). Point WAVEMATERIAL_UPDATE_SERVER at a local
stand-in to offer a newer version.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import threading
from pathlib import Path

from waitress import create_server

from wavematerial.config import Paths, load_settings
from wavematerial.jobs.scheduler import Scheduler
from wavematerial.jobs.store import JobStore
from wavematerial.models.installer import Installer
from wavematerial.models.manifest import load_manifest
from wavematerial.preflight import detect_devices, in_wsl, physical_cores
from wavematerial.updater import Install, Updater
from wavematerial.updates import TEST_SERVER, UpdateChecker
from wavematerial.web import create_app
from wavematerial.web.context import AppContext, NativeHooks

HOME = Path.home()
TOKEN = "demo"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--pretend-install", choices=("tarball", "windows"))
    args = ap.parse_args()

    paths = Paths.default()
    manifest = load_manifest()
    store = JobStore(paths.jobs_db)

    def settings():
        return load_settings(paths.settings_file)

    devices = detect_devices()
    scheduler = Scheduler(store, paths, settings, devices, physical_cores(), wsl=in_wsl())
    installer = Installer(manifest, lambda: paths.models_dir(settings()), paths.cache_dir)
    updater, why = None, "This copy runs from source; update it with git."
    if args.pretend_install:
        app_dir = HOME / "Apps" / "wavematerial-linux-x86_64"
        updater, why = Updater(paths.cache_dir, Install(args.pretend_install, app_dir)), ""
    ctx = AppContext(
        paths=paths, store=store, scheduler=scheduler, installer=installer,
        updates=UpdateChecker(paths.state_dir / "update.json"), manifest=manifest,
        devices=devices, cores=physical_cores(), wsl=in_wsl(), token=TOKEN, port=args.port,
        updater=updater, update_why=why,
    )  # fmt: skip
    recordings = sorted(str(p) for p in (HOME / "Recordings").glob("*.mp3"))
    ctx.native = NativeHooks(
        pick_files=lambda: recordings,
        pick_folder=lambda: str(HOME / "Data"),
        toggle_fullscreen=lambda: False,
        save_file=lambda name, folder: str(HOME / "Documents" / name),
    )
    server = create_server(create_app(ctx), host="127.0.0.1", port=args.port, threads=8)
    threading.Thread(target=server.run, name="http", daemon=True).start()
    scheduler.start()
    if os.environ.get(TEST_SERVER):  # only ever the local stand-in, never GitHub
        ctx.updates.check_in_background(force=True)
    print(f"READY {args.port}", flush=True)

    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    stop.wait()
    scheduler.shutdown()
    ctx.playback.shutdown()
    server.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
