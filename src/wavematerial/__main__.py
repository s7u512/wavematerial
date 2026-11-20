# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""Command-line entry point (`wavematerial`)."""

import sys

from wavematerial import __version__


def main() -> int:
    if "--version" in sys.argv[1:]:
        print(f"wavematerial {__version__}")
        return 0
    print(
        f"wavematerial {__version__}: the app is not built yet; nothing to run.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
