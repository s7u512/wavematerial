# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""WCAG 2.x contrast checks for the WaveMaterial dark palette.

Finds the reddest accent that still passes, and audits every text/background pair the
mock-ups use. Run: uv run python tools/contrast.py
"""

from __future__ import annotations


def lum(hex_: str) -> float:
    h = hex_.lstrip("#")[:6]
    c = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in c]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def ratio(a: str, b: str) -> float:
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


if __name__ == "__main__":
    import build_mockups as t  # tokens

    print(
        f"accent {t.ACCENT} on bg: {ratio(t.ACCENT, t.BG):.2f}:1 "
        "(graphics need 3:1; text uses accent-text)"
    )
    pairs = [
        ("accent fill/border/icon on bg (graphic, needs 3:1)", t.ACCENT, t.BG),
        ("accent fill/border/icon on surface (graphic, needs 3:1)", t.ACCENT, t.SURFACE),
        ("accent-text on bg", t.ACCENT_TEXT, t.BG),
        ("accent-text on surface", t.ACCENT_TEXT, t.SURFACE),
        ("accent-text on sidebar", t.ACCENT_TEXT, t.SIDEBAR),
        ("accent-text on accent-soft (pills, chips)", t.ACCENT_TEXT, t.ACCENT_SOFT),
        ("accent-text on accent-tint (playing turn)", t.ACCENT_TEXT, t.ACCENT_TINT),
        ("text on selection (selection across turns)", t.TEXT, t.SELECTION),
        ("white on accent (primary buttons)", t.ON_ACCENT, t.ACCENT),
        ("text on bg", t.TEXT, t.BG),
        ("text-2 on surface", t.TEXT_2, t.SURFACE),
        ("text-3 on surface", t.TEXT_3, t.SURFACE),
        ("text-3 on bg", t.TEXT_3, t.BG),
        ("warn on warn-soft", t.WARN, t.WARN_SOFT),
        ("ok on ok-soft", t.OK, t.OK_SOFT),
        ("danger on danger-soft", t.DANGER, t.DANGER_SOFT),
        ("danger on surface (Remove downloaded models)", t.DANGER, t.SURFACE),
        ("text on surface-2 (help tips, the update notice)", t.TEXT, t.SURFACE_2),
        ("text-2 on surface-2 (the help tip's ?)", t.TEXT_2, t.SURFACE_2),
        ("logo yellow on logo red (graphic, needs 3:1)", t.LOGO_YELLOW, t.LOGO_RED),
    ]
    for name, fg, bg in pairs:
        r = ratio(fg, bg)
        need = 3.0 if "graphic" in name else 4.5
        print(f"{'PASS' if r >= need else 'FAIL'}  {r:5.2f}:1  {name}  ({fg} on {bg})")
