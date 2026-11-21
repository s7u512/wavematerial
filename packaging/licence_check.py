# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""Licence guard for a built bundle. Run by the bundle's own Python (`python -I`), so it sees
exactly the components that ship: the same list the app's credits page shows.

    python -I licence_check.py <components.txt>

Writes the component list to the given file, and exits non-zero if any component has no
licence or one that WaveMaterial can't ship (GPL-3.0 only or or-later, any AGPL, proprietary).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from wavematerial.web.credits import BUNDLED, licence_text, software

# Matches GPL-3.0 / GPLv3 (but not LGPL), AGPL in any form, and proprietary licences.
FORBIDDEN = re.compile(
    r"(?<![L\w])GPL-?v?3|(?<!Lesser )General Public License v3|AGPL|Affero|Proprietary",
    re.IGNORECASE,
)


def main() -> int:
    out = Path(sys.argv[1])
    problems = []
    lines = []
    for c in software() + BUNDLED:
        text = licence_text(c.key) or ""
        label = f"{c.name} {c.version}".strip()
        lines.append(f"{label}\t{c.licence}")
        if c.licence == "see licence text" and not text:
            problems.append(f"{label}: no licence found")
        elif FORBIDDEN.search(c.licence):
            problems.append(f"{label}: licence not allowed ({c.licence})")
        elif not text:
            problems.append(f"{label}: no licence text to show")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for p in problems:
        print(f"LICENCE PROBLEM: {p}", file=sys.stderr)
    print(f"{len(lines)} components checked, {len(problems)} problems; list in {out}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
