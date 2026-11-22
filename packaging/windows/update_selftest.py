# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""Play the app's part in a one-click update, in the installed app (run by build.py).

    python update_selftest.py <setup.exe> <cache folder> <file to write the exit time to>

Holds the app's "running" mutex, starts the installer exactly as the app does on quitting
to update, stays up a while longer, then exits and writes the time. The installer must wait
for that exit, install, and start the app again.
"""

import sys
import time
from pathlib import Path

from wavematerial import app
from wavematerial.updater import Updater, current_install

app._running_marker()
install, why = current_install()
if install is None or install.kind != "windows":
    sys.exit(f"Not seen as an installed Windows copy: {why}")
updater = Updater(Path(sys.argv[2]), install)
updater._file, updater.state, updater.version = Path(sys.argv[1]), "ready", "self-test"
updater.apply()
time.sleep(25)  # longer than an install takes, so an installer that doesn't wait shows
Path(sys.argv[3]).write_text(f"{time.time():.0f}\n", encoding="utf-8")
