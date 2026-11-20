# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""Start WaveMaterial: preflight, the job scheduler, the local server, and the window.

The window is pywebview (the system's web view). If it can't open, the app falls back to
the default browser and keeps running until interrupted (Ctrl+C).
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import secrets
import sys
import threading
import time
import webbrowser

from wavematerial import __version__
from wavematerial.config import Paths, load_settings
from wavematerial.jobs.lock import AlreadyRunning, InstanceLock
from wavematerial.jobs.scheduler import Scheduler
from wavematerial.jobs.store import JobStore
from wavematerial.models.installer import Installer
from wavematerial.models.manifest import load_manifest
from wavematerial.preflight import detect_devices, in_wsl, physical_cores
from wavematerial.updates import UpdateChecker
from wavematerial.web import create_app
from wavematerial.web.context import AppContext, NativeHooks

log = logging.getLogger("wavematerial")


def _setup_logging(paths: Paths) -> None:
    paths.logs_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        paths.logs_dir / "app.log", maxBytes=1 << 20, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    logging.getLogger("waitress").setLevel(logging.WARNING)


def _open_window(ctx: AppContext, url: str) -> None:
    """Show the app window; returns when it is closed. Raises if no window can be shown."""
    import webview
    from webview.dom import DOMEventHandler

    window = webview.create_window(
        "WaveMaterial",
        url,
        fullscreen=True,
        min_size=(960, 720),
        background_color="#111214",
        text_select=True,
    )
    state = {"full": True}

    def toggle_fullscreen() -> bool:
        window.toggle_fullscreen()
        state["full"] = not state["full"]
        return state["full"]

    def pick_files() -> list[str]:
        return list(window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=True) or [])

    def pick_folder() -> str | None:
        chosen = window.create_file_dialog(webview.FileDialog.FOLDER)
        return chosen[0] if chosen else None

    def on_drop(event: dict) -> None:
        files = event.get("dataTransfer", {}).get("files", [])
        paths = [f["pywebviewFullPath"] for f in files if f.get("pywebviewFullPath")]
        if paths:
            window.evaluate_js(f"window.wmAddDropped({json.dumps(paths)})")

    def on_loaded() -> None:
        window.dom.document.events.drop += DOMEventHandler(on_drop, True, True)

    window.events.loaded += on_loaded
    ctx.native = NativeHooks(pick_files, pick_folder, toggle_fullscreen)
    ctx.fullscreen = True
    webview.start(private_mode=True)


def main(argv: list[str] | None = None) -> int:
    paths = Paths.default()
    _setup_logging(paths)
    log.info("WaveMaterial %s starting", __version__)

    lock = InstanceLock(paths.state_dir / "instance.lock")
    try:
        lock.acquire()
    except AlreadyRunning:
        print("WaveMaterial is already running.", file=sys.stderr)
        return 1

    started = time.monotonic()
    devices = detect_devices()
    cores, wsl = physical_cores(), in_wsl()
    log.info("Preflight took %.2f s; devices: %s", time.monotonic() - started, devices)

    manifest = load_manifest()
    store = JobStore(paths.jobs_db)

    def settings():
        return load_settings(paths.settings_file)

    scheduler = Scheduler(store, paths, settings, devices, cores, wsl=wsl)
    installer = Installer(manifest, lambda: paths.models_dir(settings()), paths.cache_dir)
    updates = UpdateChecker(paths.state_dir / "update.json")
    ctx = AppContext(
        paths=paths, store=store, scheduler=scheduler, installer=installer, updates=updates,
        manifest=manifest, devices=devices, cores=cores, wsl=wsl,
        token=secrets.token_urlsafe(32),
    )  # fmt: skip

    from waitress import create_server

    server = create_server(create_app(ctx), host="127.0.0.1", port=0, threads=8)
    ctx.port = server.effective_port
    threading.Thread(target=server.run, name="http", daemon=True).start()
    scheduler.start()
    if settings().update_check:
        updates.check_in_background()

    url = f"http://127.0.0.1:{ctx.port}/?token={ctx.token}"
    try:
        try:
            _open_window(ctx, url)
        except Exception:
            log.exception("The app window could not open; using the browser instead")
            ctx.native = NativeHooks()
            print(
                "The WaveMaterial window could not open, so it opened in your browser.\n"
                "Keep this terminal open while you use it; press Ctrl+C to quit.",
                file=sys.stderr,
            )
            webbrowser.open(url)
            try:
                while True:
                    time.sleep(3600)
            except KeyboardInterrupt:
                pass
    finally:
        log.info("Shutting down")
        scheduler.shutdown()
        server.close()
        lock.release()
    return 0
