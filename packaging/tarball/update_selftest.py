# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""Self-update the unpacked tarball the way the app does (run by build.py, with its Python).

    python update_selftest.py <cache folder>

WAVEMATERIAL_UPDATE_SERVER points at build.py's local stand-in for the release page, which
offers this same tarball; WAVEMATERIAL_SELFTEST_STARTED makes the restarted app note that it
started and exit instead of opening a window.
"""

import sys
import threading
import time
from pathlib import Path

from wavematerial.updater import Updater, current_install
from wavematerial.updates import UpdateChecker

install, why = current_install()
if install is None or install.kind != "tarball":
    sys.exit(f"Not seen as an unpacked tarball: {why}")
checker = UpdateChecker(Path(sys.argv[1]) / "update.json")
checker._check()
if not checker.status.latest or not checker.status.assets:
    sys.exit(f"The update check found nothing: {checker.status}")
updater = Updater(Path(sys.argv[1]), install)
ready = threading.Event()
updater.start(checker.status.latest, checker.status.assets, "self", ready.set)
deadline = time.monotonic() + 120
while updater.state == "downloading" and time.monotonic() < deadline:
    time.sleep(0.2)
if not ready.is_set():
    sys.exit(f"The update didn't get ready: {updater.state}, {updater.error}")
updater.mark_ready()  # what the app does once the queue is held and it quits
updater.apply()
