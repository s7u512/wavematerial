# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""The UI icons: 16-unit paths, the same set the mock-ups use (design/tools/build_mockups.py).

Drawn with a 1.6 px round stroke; `FILLED` icons are filled instead.
"""

ICONS = {
    "library": "M3 3h4v10H3z M9 3h4v10H9z",
    "settings": (
        "M8 5.5a2.5 2.5 0 1 0 0 5a2.5 2.5 0 1 0 0-5 M8 1v2 M8 13v2 M1 8h2 M13 8h2 "
        "M3 3l1.5 1.5 M11.5 11.5L13 13 M3 13l1.5-1.5 M11.5 4.5L13 3"
    ),
    "plus": "M8 3v10 M3 8h10",
    "search": "M7 2.5a4.5 4.5 0 1 0 0 9a4.5 4.5 0 1 0 0-9 M10.5 10.5L14 14",
    "chev": "M4 6l4 4 4-4",
    "back": "M10 3L5 8l5 5",
    "pencil": "M3 13l1-3 7-7 2 2-7 7z",
    "export": "M8 2v8 M4.5 5.5L8 2l3.5 3.5 M3 10v4h10v-4",
    "rewind": "M8 4L3 8l5 4z M13 4L8 8l5 4z",
    "speaker": "M8 2.5a2.5 2.5 0 1 0 0 5a2.5 2.5 0 1 0 0-5 M3 14c0-3 2.2-4.5 5-4.5s5 1.5 5 4.5",
    "more": "M2.5 7.2h1.6v1.6h-1.6z M7.2 7.2h1.6v1.6h-1.6z M11.9 7.2h1.6v1.6h-1.6z",
    "x": "M4 4l8 8 M12 4l-8 8",
    "check": "M3 8.5l3 3 7-7",
    "play": "M5 3l8 5-8 5z",
    "pause": "M5 3v10 M11 3v10",
    "upload": "M8 11V3 M4.5 6.5L8 3l3.5 3.5 M3 13h10",
    "folder": "M2 4h4l1.5 1.5H14v7H2z",
    "file": "M4 2h5l3 3v9H4z M9 2v3h3",
    "refresh": "M13 8c0 2.8-2.2 5-5 5s-5-2.2-5-5 2.2-5 5-5c1.6 0 3 .7 3.9 1.9 M13 2.5v3h-3",
    "gpu": "M2 5h12v7H2z M5 5V3 M11 5V3 M5 12v2 M11 12v2 M5.5 7.5h5v2h-5z",
    "alert": "M8 2l6 11H2z M8 6v3 M8 11v.5",
    "trash": "M3 4.5h10 M6.5 4.5V3h3v1.5 M4.5 4.5l.6 8.5h5.8l.6-8.5",
    "up": "M4 10l4-4 4 4",
    "down": "M4 6l4 4 4-4",
}
FILLED = {"play", "more"}
