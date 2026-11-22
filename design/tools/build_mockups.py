#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""Generate the WaveMaterial mock-ups as a FigCraft script.

Usage (from design/):
    uv run python tools/build_mockups.py      # writes tools/mockups.json
    figcraft-cli run tools/mockups.json --out wavematerial.figcraft
    figcraft-cli export wavematerial.figcraft -o exports/ --page Screens

Everything is built with auto layout, so layout fixes are edits to this file, not
pixel-pushing. "WaveMaterial" is a placeholder product name.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import logo_source  # noqa: E402  (the hand-made master logo)

# ---------------------------------------------------------------------------
# Design tokens (dark theme -- the only theme in 1.0.0). Mirrored in DESIGN.md.
# ---------------------------------------------------------------------------
BG = "#111214"  # app background
SURFACE = "#151518"  # cards, panels, table (dark enough for red text: 4.56:1)
SURFACE_2 = "#202328"  # inputs, chips, table header, footers
SIDEBAR = "#0B0C0E"
BORDER = "#2A2D33"
BORDER_STRONG = "#3B3F46"
TEXT = "#ECECEC"
TEXT_2 = "#A8ACB3"
TEXT_3 = "#858A91"  # darkest grey passing 4.5:1 on bg, surface, surface-2, tint
ACCENT = (
    "#C81400"  # rgb(200, 20, 0): fills, borders, icons, logo tile (3.2:1 on BG: fine for graphics)
)
ACCENT_TEXT = "#D75647"  # same hue, lighter: for red TEXT (>= 4.5:1 on every dark background)
ON_ACCENT = "#FFFFFF"  # text/icons on red fills (5.9:1)
ACCENT_SOFT = "#2A0D08"  # accent-text on it: 4.58:1
ACCENT_TINT = "#1C1210"  # playing turn; accent-text on it: 4.65:1
SELECTION = "#2D4F7C"  # a Shift+click selection across turns (the editor)
WARN = "#F0B04A"
WARN_SOFT = "#33270F"
DANGER = "#FF8A80"  # errors: lighter salmon + icon, so they don't read as "brand red"
DANGER_SOFT = "#3A1717"
OK = "#4CC38A"
OK_SOFT = "#11291D"
SPK = [
    "#4FB8C0",
    "#E0A04A",
    "#A08CEB",
    "#6FA3F2",
    "#A8C36A",
    "#D58BD5",
]  # no reds: red is the accent

LOGO_RED = "#C81400"  # from design/logo/app-icon.svg
LOGO_YELLOW = "#FFE600"  # the sickle; the wave bars are #FFFF00

UI = "Inter 18pt"
READ = "Noto Sans"
W, H = 1920, 1080  # native: 16:9 1080p fullscreen
CW, CH = 960, 720  # minimum supported: 4:3 720p
SIDEBAR_W = 248

SHADOW_SM = [{"type": "dropShadow", "color": "#00000066", "offset": [0, 1], "radius": 2}]
SHADOW_LG = [{"type": "dropShadow", "color": "#000000B3", "offset": [0, 16], "radius": 40}]

# ---------------------------------------------------------------------------
# Tiny script builder
# ---------------------------------------------------------------------------
steps: list[dict] = []
_n = 0


def _ref(prefix: str = "n") -> str:
    global _n
    _n += 1
    return f"{prefix}{_n}"


def R(name: str) -> dict:
    return {"$ref": name}


def cmd(command: str, params: dict, as_: str | None = None) -> str | None:
    step = {"command": command, "params": params}
    if as_:
        step["as"] = as_
    steps.append(step)
    return as_


def frame(parent: str | None, name: str = "Frame", w: float = 10, h: float = 10, **props) -> str:
    r = _ref("f")
    p = {"type": "frame", "name": name, "width": w, "height": h, "props": {"fill": None, **props}}
    if parent:
        p["parent"] = R(parent)
    cmd("node.create", p, r)
    return r


def screen(name: str, x: float, y: float, w: float = W, h: float = H, **props) -> str:
    r = _ref("s")
    cmd(
        "frame.create",
        {
            "name": name,
            "x": x,
            "y": y,
            "width": w,
            "height": h,
            "props": {"fill": BG, "clip": True, **props},
        },
        r,
    )
    return r


def text(
    parent: str,
    s: str,
    size: float = 14,
    weight: str = "Regular",
    color: str = TEXT,
    family: str = UI,
    **props,
) -> str:
    r = _ref("t")
    fam = props.pop("fontFamily", family)
    family = fam
    cmd(
        "text.create",
        {
            "parent": R(parent),
            "text": s,
            "x": 0,
            "y": 0,
            "props": {
                "fontFamily": family,
                "fontStyle": weight,
                "fontSize": size,
                "fill": color,
                **props,
            },
        },
        r,
    )
    return r


def para(
    parent: str,
    s: str,
    size: float = 14,
    color: str = TEXT,
    family: str = UI,
    lh: str | float = "150%",
    **props,
) -> str:
    """Wrapping paragraph that fills its parent's width."""
    return text(
        parent,
        s,
        size,
        props.pop("weight", "Regular"),
        color,
        family,
        sizingH="fill",
        textAutoResize="height",
        lineHeight=lh,
        **props,
    )


def style_range(t: str, start: int, end: int, **st) -> None:
    cmd("text.style", {"id": R(t), "start": start, "end": end, **st})


def style_word(t: str, full: str, word: str, occurrence: int = 0, **st) -> None:
    i = -1
    for _ in range(occurrence + 1):
        i = full.index(word, i + 1)
    style_range(t, i, i + len(word), **st)


def rect(parent: str, w: float, h: float, fill: str, **props) -> str:
    r = _ref("r")
    cmd(
        "node.create",
        {
            "type": "rectangle",
            "parent": R(parent),
            "width": w,
            "height": h,
            "props": {"fill": fill, **props},
        },
        r,
    )
    return r


def dot(parent: str, d: float, fill: str, **props) -> str:
    r = _ref("d")
    cmd(
        "node.create",
        {
            "type": "ellipse",
            "parent": R(parent),
            "width": d,
            "height": d,
            "props": {"fill": fill, **props},
        },
        r,
    )
    return r


def vec(
    parent: str,
    path: str,
    w: float,
    h: float,
    stroke: str | None = None,
    fill: str | None = None,
    sw: float = 1.6,
    **props,
) -> str:
    r = _ref("v")
    p: dict = {"fill": fill}
    if stroke:
        p.update(stroke=stroke, strokeWeight=sw, strokeCap="round", strokeJoin="round")
    x0, y0, x1, y1 = path_bbox(path)
    size = max(w, h)  # fit the longer side, keep proportions
    dims = {"width": size} if x1 - x0 >= y1 - y0 else {"height": size}
    cmd(
        "node.create",
        {"type": "vector", "parent": R(parent), "path": path, **dims, "props": {**p, **props}},
        r,
    )
    return r


def edge(side: str, color: str = BORDER, w: float = 1) -> dict:
    """A border on one side only (setting one side's weight alone leaves the others at 1)."""
    d = {f"stroke{k}Weight": 0 for k in ("Top", "Right", "Bottom", "Left")}
    d[f"stroke{side.capitalize()}Weight"] = w
    return {"stroke": color, **d}


def spacer(parent: str, horizontal: bool = True) -> str:
    return frame(
        parent, "spacer", 1, 1, **({"sizingH": "fill"} if horizontal else {"sizingV": "fill"})
    )


def hstack(
    parent: str, name: str = "Row", gap: float = 8, pad=0, align: str = "center", **props
) -> str:
    return frame(
        parent,
        name,
        10,
        10,
        layout="horizontal",
        gap=gap,
        padding=pad,
        crossAlign=align,
        sizingH=props.pop("sizingH", "hug"),
        sizingV=props.pop("sizingV", "hug"),
        **props,
    )


def vstack(parent: str, name: str = "Column", gap: float = 8, pad=0, **props) -> str:
    return frame(
        parent,
        name,
        10,
        10,
        layout="vertical",
        gap=gap,
        padding=pad,
        sizingH=props.pop("sizingH", "hug"),
        sizingV=props.pop("sizingV", "hug"),
        **props,
    )


# ---------------------------------------------------------------------------
# Icons (16 px stroked paths)
# ---------------------------------------------------------------------------
ICON = {
    "library": "M3 3h4v10H3z M9 3h4v10H9z",
    "inbox": "M2 9l2-6h8l2 6v4H2z M2 9h4l1 2h2l1-2h4",
    "review": "M8 2l6 11H2z M8 6v3 M8 11v.5",
    "settings": (
        "M8 5.5a2.5 2.5 0 1 0 0 5a2.5 2.5 0 1 0 0-5 M8 1v2 M8 13v2 M1 8h2 M13 8h2 "
        "M3 3l1.5 1.5 M11.5 11.5L13 13 M3 13l1.5-1.5 M11.5 4.5L13 3"
    ),
    "plus": "M8 3v10 M3 8h10",
    "search": "M7 2.5a4.5 4.5 0 1 0 0 9a4.5 4.5 0 1 0 0-9 M10.5 10.5L14 14",
    "back": "M10 3L5 8l5 5",
    "chev": "M4 6l4 4 4-4",
    "more": "M2.5 7.2h1.6v1.6h-1.6z M7.2 7.2h1.6v1.6h-1.6z M11.9 7.2h1.6v1.6h-1.6z",
    "x": "M4 4l8 8 M12 4l-8 8",
    "check": "M3 8.5l3 3 7-7",
    "play": "M5 3l8 5-8 5z",
    "pause": "M5 3v10 M11 3v10",
    "rewind": "M8 4L3 8l5 4z M13 4L8 8l5 4z",
    "upload": "M8 11V3 M4.5 6.5L8 3l3.5 3.5 M3 13h10",
    "folder": "M2 4h4l1.5 1.5H14v7H2z",
    "file": "M4 2h5l3 3v9H4z M9 2v3h3",
    "speaker": "M8 2.5a2.5 2.5 0 1 0 0 5a2.5 2.5 0 1 0 0-5 M3 14c0-3 2.2-4.5 5-4.5s5 1.5 5 4.5",
    "export": "M8 2v8 M4.5 5.5L8 2l3.5 3.5 M3 10v4h10v-4",
    "pencil": "M3 13l1-3 7-7 2 2-7 7z",
    "refresh": "M13 8c0 2.8-2.2 5-5 5s-5-2.2-5-5 2.2-5 5-5c1.6 0 3 .7 3.9 1.9 M13 2.5v3h-3",
    "trash": "M3 4.5h10 M6.5 4.5V3h3v1.5 M4.5 4.5l.6 8.5h5.8l.6-8.5",
    "gpu": "M2 5h12v7H2z M5 5V3 M11 5V3 M5 12v2 M11 12v2 M5.5 7.5h5v2h-5z",
}


def path_bbox(d: str) -> tuple[float, float, float, float]:
    """Bounding box of the path's points (endpoints and control points). Good enough for icons."""
    toks = re.findall(r"[A-Za-z]|-?\d*\.?\d+", d)
    i, cx, cy, sx, sy, cmd_ = 0, 0.0, 0.0, 0.0, 0.0, "M"
    xs: list[float] = []
    ys: list[float] = []
    nargs = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7, "Z": 0}

    def num() -> float:
        nonlocal i
        v = float(toks[i])
        i += 1
        return v

    while i < len(toks):
        if toks[i].isalpha():
            cmd_ = toks[i]
            i += 1
            if cmd_ in "Zz":
                cx, cy = sx, sy
                continue
        up, rel = cmd_.upper(), cmd_.islower()
        n = nargs[up]
        args = [num() for _ in range(n)]
        if up == "H":
            cx = cx + args[0] if rel else args[0]
        elif up == "V":
            cy = cy + args[0] if rel else args[0]
        elif up == "A":
            cx, cy = (cx + args[5], cy + args[6]) if rel else (args[5], args[6])
        else:
            pts = list(zip(args[0::2], args[1::2], strict=False))
            for px, py in pts[:-1]:
                xs.append(cx + px if rel else px)
                ys.append(cy + py if rel else py)
            ex, ey = pts[-1]
            cx, cy = (cx + ex, cy + ey) if rel else (ex, ey)
        if up == "M":
            sx, sy = cx, cy
            cmd_ = "l" if rel else "L"
        xs.append(cx)
        ys.append(cy)
    return min(xs), min(ys), max(xs), max(ys)


def icon(parent: str, name: str, color: str = TEXT_2, size: float = 16, sw: float = 1.6) -> str:
    """Icons are drawn on a 16-unit grid; scaled to `size` keeping proportions."""
    holder = frame(parent, f"icon/{name}", size, size)
    filled = name in ("play", "more")
    x0, y0, x1, y1 = path_bbox(ICON[name])
    k = size / 16
    r = _ref("v")
    props: dict = {"fill": color if filled else None, "absolute": True, "x": x0 * k, "y": y0 * k}
    if not filled:
        props.update(stroke=color, strokeWeight=sw, strokeCap="round", strokeJoin="round")
    params = {"type": "vector", "parent": R(holder), "path": ICON[name], "props": props}
    if x1 - x0 >= y1 - y0:
        params["width"] = (x1 - x0) * k
    else:
        params["height"] = (y1 - y0) * k
    cmd("node.create", params, r)
    return holder


# ---------------------------------------------------------------------------
# Components
# ---------------------------------------------------------------------------
def logo_mark(parent: str, size: float = 28, tile: bool = True) -> str:
    """The WaveMaterial logo, drawn from the master SVG (logo/app-icon.svg) scaled to `size`."""
    canvas, tile_part, mark = logo_source.parts()
    box = frame(parent, "Logo", size, size)
    for part in ([tile_part] if tile else []) + mark:
        cmd(
            "node.create",
            {
                "type": "vector",
                "parent": R(box),
                "path": logo_source.scale_d(part.d, size / canvas),
                "x": 0,
                "y": 0,
                "props": {"fill": part.fill, "name": part.name},
            },
        )
    return box


def button(
    parent: str,
    label: str,
    kind: str = "secondary",
    icon_name: str | None = None,
    small: bool = False,
) -> str:
    styles = {
        "primary": dict(fill=ACCENT, stroke=None, color=ON_ACCENT),
        "secondary": dict(fill=SURFACE, stroke=BORDER_STRONG, color=TEXT),
        "ghost": dict(fill=None, stroke=None, color=TEXT_2),
        "danger": dict(fill=SURFACE, stroke="#6B2A2E", color=DANGER),
        "ghost-danger": dict(fill=None, stroke=None, color=DANGER),
    }[kind]
    pad = [5, 10, 5, 10] if small else [8, 14, 8, 14]
    b = hstack(
        parent,
        f"Button/{label}",
        gap=6,
        pad=pad,
        fill=styles["fill"],
        cornerRadius=6,
        **({"stroke": styles["stroke"], "strokeWeight": 1} if styles["stroke"] else {}),
        **({"effects": SHADOW_SM} if kind in ("secondary", "primary") else {}),
    )
    if icon_name:
        icon(b, icon_name, styles["color"], 14 if small else 16)
    if label:
        text(b, label, 12.5 if small else 13.5, "Medium", styles["color"])
    return b


def chip(
    parent: str,
    label: str,
    color: str = TEXT_2,
    fill: str = SURFACE,
    stroke: str | None = BORDER,
    removable: bool = False,
    count: str | None = None,
    active: bool = False,
) -> str:
    c = hstack(
        parent,
        f"Chip/{label}",
        gap=6,
        pad=[4, 10, 4, 10],
        cornerRadius=999,
        fill=ACCENT_SOFT if active else fill,
        **({"stroke": ACCENT if active else stroke, "strokeWeight": 1} if stroke else {}),
    )
    text(c, label, 12.5, "Medium", ACCENT_TEXT if active else color)
    if count:
        text(c, count, 12, "Regular", ACCENT_TEXT if active else TEXT_3, features={"tnum": True})
    if removable:
        icon(c, "x", TEXT_3, 12)
    return c


def pill(parent: str, label: str, fg: str, bg: str, dot_color: str | None = None) -> str:
    p = hstack(parent, f"Pill/{label}", gap=6, pad=[3, 8, 3, 8], cornerRadius=999, fill=bg)
    if dot_color:
        dot(p, 6, dot_color)
    text(p, label, 12, "Medium", fg)
    return p


def progress(
    parent: str, frac: float, width: float = 160, color: str = ACCENT, height: float = 6
) -> str:
    track = frame(parent, "Progress", width, height, fill=BORDER, cornerRadius=999, clip=True)
    cmd(
        "node.create",
        {
            "type": "rectangle",
            "parent": R(track),
            "width": max(width * frac, 1),
            "height": height,
            "props": {"fill": color, "cornerRadius": 999, "absolute": True, "x": 0, "y": 0},
        },
    )
    return track


def field(
    parent: str,
    value: str,
    width: float | None = None,
    placeholder: bool = False,
    icon_name: str | None = None,
    trailing: str | None = None,
) -> str:
    f = hstack(
        parent,
        "Input",
        gap=8,
        pad=[7, 10, 7, 10],
        fill=SURFACE,
        stroke=BORDER_STRONG,
        strokeWeight=1,
        cornerRadius=6,
        **({"sizingH": "fixed"} if width else {"sizingH": "fill"}),
    )
    if width:
        cmd("node.set", {"ids": [R(f)], "props": {"width": width}})
    if icon_name:
        icon(f, icon_name, TEXT_3, 15)
    text(f, value, 13.5, "Regular", TEXT_3 if placeholder else TEXT, sizingH="fill")
    if trailing:
        icon(f, trailing, TEXT_3, 14)
    return f


def divider(parent: str, vertical: bool = False) -> str:
    if vertical:
        return rect(parent, 1, 10, BORDER, sizingV="fill")
    return rect(parent, 10, 1, BORDER, sizingH="fill")


def section_label(parent: str, s: str) -> str:
    return text(parent, s.upper(), 11, "SemiBold", TEXT_3, letterSpacing="6%")


# ---------------------------------------------------------------------------
# App shell
# ---------------------------------------------------------------------------
def sidebar(win: str, active: str, compact: bool = False, update: str | None = None) -> None:
    if compact:  # icon rail for small windows
        sb = vstack(
            win,
            "Sidebar",
            gap=6,
            pad=[14, 10, 14, 10],
            fill=SIDEBAR,
            sizingV="fill",
            sizingH="fixed",
            crossAlign="center",
            **edge("right"),
        )
        cmd("node.set", {"ids": [R(sb)], "props": {"width": 60}})
        logo_mark(sb, 30)
        frame(sb, "gap", 1, 12)
        for key, ic in [("library", "library"), ("add", "plus")]:
            it = frame(
                sb,
                f"Rail/{key}",
                38,
                38,
                cornerRadius=8,
                fill=SURFACE if key == active else None,
                layout="vertical",
                mainAlign="center",
                crossAlign="center",
            )
            icon(it, ic, ACCENT if key == active else TEXT_2, 18)
        spacer(sb, horizontal=False)
        dot(sb, 10, OK)
        it = frame(
            sb,
            "Rail/settings",
            38,
            38,
            cornerRadius=8,
            layout="vertical",
            mainAlign="center",
            crossAlign="center",
        )
        icon(it, "settings", TEXT_2, 18)
        return
    sb = vstack(
        win,
        "Sidebar",
        gap=2,
        pad=[18, 12, 14, 12],
        fill=SIDEBAR,
        sizingV="fill",
        sizingH="fixed",
        **edge("right"),
    )
    cmd("node.set", {"ids": [R(sb)], "props": {"width": SIDEBAR_W}})
    brand = hstack(sb, "Brand", gap=10, pad=[0, 6, 18, 6])
    logo_mark(brand, 30)
    text(brand, "WaveMaterial", 17, "SemiBold", TEXT, letterSpacing="-1%")
    is_lib = active == "library"
    item = hstack(
        sb,
        "Nav/Library",
        gap=10,
        pad=[8, 10, 8, 10],
        cornerRadius=6,
        sizingH="fill",
        fill=SURFACE if is_lib else None,
    )
    icon(item, "library", ACCENT if is_lib else TEXT_2)
    text(
        item,
        "Library",
        13.5,
        "Medium" if is_lib else "Regular",
        TEXT if is_lib else TEXT_2,
        sizingH="fill",
    )
    text(item, "12", 12, "Regular", TEXT_3, features={"tnum": True})
    frame(sb, "gap", 1, 14)
    rl = hstack(sb, "Recent label", gap=0, pad=[0, 10, 4, 10], sizingH="fill")
    section_label(rl, "Recent")
    for name, _spk_c in [
        ("apollo11_landing_1969", SPK[0]),
        ("apollo8_christmas_eve_1968", SPK[1]),
        ("gemini4_spacewalk_1965", SPK[2]),
        ("nixon_moon_call_1969", SPK[3]),
    ]:
        r = hstack(sb, f"Recent/{name}", gap=10, pad=[6, 10, 6, 10], cornerRadius=6, sizingH="fill")
        icon(r, "file", TEXT_3, 15)
        text(r, name, 13, "Regular", TEXT_2, sizingH="fill")
    spacer(sb, horizontal=False)
    if update:  # a newer version exists: a small notice that leads to Settings
        note = hstack(
            sb, "Update notice", gap=10, pad=[8, 10, 8, 10], fill=SURFACE_2, cornerRadius=6,
            sizingH="fill",
        )  # fmt: skip
        icon(note, "refresh", TEXT)
        text(note, f"Version {update} is available", 12.5, "Medium", TEXT, sizingH="fill")
    # engine card
    card = vstack(
        sb,
        "Engine",
        gap=8,
        pad=12,
        fill=SURFACE,
        cornerRadius=8,
        stroke=BORDER,
        strokeWeight=1,
        sizingH="fill",
    )
    top = hstack(card, "Engine status", gap=8, sizingH="fill")
    dot(top, 8, OK)
    text(top, "Transcribing", 13, "SemiBold", TEXT, sizingH="fill")
    text(top, "1 of 2", 12, "Regular", TEXT_3)
    dev = hstack(card, "Device", gap=6)
    icon(dev, "gpu", TEXT_3, 14)
    text(dev, "Radeon 660M · Vulkan", 12, "Regular", TEXT_2)
    button(card, "Pause queue", "secondary", "pause", small=True)
    settings_item = hstack(
        sb,
        "Nav/Settings",
        gap=10,
        pad=[8, 10, 8, 10],
        cornerRadius=6,
        sizingH="fill",
        fill=SURFACE if active == "settings" else None,
    )
    cmd("node.set", {"ids": [R(settings_item)], "props": {"paddingTop": 12}})
    icon(settings_item, "settings", ACCENT if active == "settings" else TEXT_2)
    text(
        settings_item,
        "Settings",
        13.5,
        "Medium" if active == "settings" else "Regular",
        TEXT if active == "settings" else TEXT_2,
    )


def f11_hint(parent: str, label: str = "Exit full screen") -> str:
    h = hstack(parent, "F11 hint", gap=6)
    kb = hstack(
        h,
        "Kbd",
        gap=0,
        pad=[2, 6, 2, 6],
        fill=SURFACE_2,
        cornerRadius=4,
        stroke=BORDER,
        strokeWeight=1,
    )
    text(kb, "F11", 11.5, "Medium", TEXT_2)
    text(h, label, 12, "Regular", TEXT_3)
    return h


def page_header(main: str, title: str, subtitle: str | None = None) -> str:
    hdr = hstack(main, "Header", gap=12, pad=[20, 28, 16, 28], sizingH="fill")
    col = vstack(hdr, "Titles", gap=2, sizingH="fill")
    text(col, title, 22, "SemiBold", TEXT, letterSpacing="-1%")
    if subtitle:
        text(col, subtitle, 13, "Regular", TEXT_3)
    return hdr


def shell(
    name: str,
    x: float,
    y: float,
    active: str,
    h: float = H,
    w: float = W,
    compact: bool = False,
    update: str | None = None,
) -> tuple[str, str]:
    win = screen(name, x, y, w=w, h=h, layout="horizontal")
    sidebar(win, active, compact, update)
    main = vstack(win, "Main", gap=0, sizingH="fill", sizingV="fill")
    return win, main


# ---------------------------------------------------------------------------
# Screens
# ---------------------------------------------------------------------------
ROWS = [
    # Sample library: US-government (public-domain) recordings from 1950-1990.
    # name, duration, speakers, status kind, status detail, added, progress
    ("apollo13_problem_1970.mp3", "18:44", "2–4", "running", "Transcribing", "Today, 14:02", 0.58),
    ("jfk_rice_university_1962.mp3", "17:47", "1", "queued", "Queued · next", "Today, 14:03", 0),
    (
        "apollo11_landing_1969.mp3",
        "12:31",
        "3",
        "done",
        "Ready · speakers named",
        "Today, 11:40",
        1,
    ),
    ("eisenhower_farewell_1961.mp3", "15:31", "1", "done", "Ready", "Yesterday", 1),
    ("gemini4_spacewalk_1965.mp3", "21:05", "2–3", "done", "Ready · speakers named", "12 Nov", 1),
    ("reagan_berlin_1987.wav", "26:30", "1", "failed", "Source file not found", "11 Nov", 0),
    ("apollo8_christmas_eve_1968.mp3", "11:18", "3", "done", "Ready · edited", "8 Nov", 1),
    ("friendship7_glenn_1962.mp3", "34:50", "2", "done", "Ready", "3 Nov", 1),
    ("nixon_moon_call_1969.mp3", "2:52", "3", "done", "Ready · speakers named", "1 Nov", 1),
    ("voyager2_neptune_briefing_1989.mp3", "48:12", "3–6", "done", "Ready", "29 Oct", 1),
    ("skylab_crew_downlink_1973.mp3", "27:40", "3–4", "done", "Ready · edited", "27 Oct", 1),
    ("mercury_freedom7_1961.mp3", "15:22", "2", "done", "Ready", "22 Oct", 1),
]


def library_table(main: str, selected: int | None = None) -> None:
    bar = hstack(main, "Toolbar", gap=8, pad=[0, 28, 14, 28], sizingH="fill")
    for label, count, act in [
        ("All", "12", True),
        ("In progress", "2", False),
        ("Done", "9", False),
        ("Failed", "1", False),
    ]:
        chip(bar, label, count=count, active=act)
    spacer(bar)
    field(bar, "Search transcripts", width=240, placeholder=True, icon_name="search")

    wrap = vstack(main, "Table wrap", gap=0, pad=[0, 28, 0, 28], sizingH="fill", sizingV="fill")
    table = vstack(
        wrap,
        "Table",
        gap=0,
        fill=SURFACE,
        cornerRadius=10,
        stroke=BORDER,
        strokeWeight=1,
        sizingH="fill",
        clip=True,
        effects=SHADOW_SM,
    )
    cols = [
        ("Name", None),
        ("Length", 86),
        ("Speakers", 86),
        ("Status", 300),
        ("Added", 104),
        ("", 40),
    ]
    head = hstack(
        table,
        "Head",
        gap=16,
        pad=[10, 18, 10, 18],
        sizingH="fill",
        fill=SURFACE_2,
        **edge("bottom"),
    )
    for label, w in cols:
        t = text(
            head,
            label.upper(),
            11,
            "SemiBold",
            TEXT_3,
            letterSpacing="6%",
            **({"sizingH": "fill"} if w is None else {}),
        )
        if w:
            cmd("node.set", {"ids": [R(t)], "props": {"textAutoResize": "height", "width": w}})
    for i, (name, dur, spk, kind, detail, added, frac) in enumerate(ROWS):
        row = hstack(
            table,
            f"Row/{name}",
            gap=16,
            pad=[12, 18, 12, 18],
            sizingH="fill",
            fill=ACCENT_TINT if selected == i else None,
            **({"strokeBottomWeight": 1, "stroke": BORDER} if i < len(ROWS) - 1 else {}),
        )
        ncol = hstack(row, "Name", gap=10, sizingH="fill")
        icon(ncol, "file", TEXT_3, 16)
        text(ncol, name, 13.5, "Medium", TEXT, sizingH="fill")
        for val, w in [(dur, 86), (spk, 86)]:
            t = text(row, val, 13, "Regular", TEXT_2, features={"tnum": True})
            cmd("node.set", {"ids": [R(t)], "props": {"textAutoResize": "height", "width": w}})
        st = frame(row, "Status", 300, 10, layout="vertical", gap=6, sizingV="hug")
        if kind == "running":
            line = hstack(st, "Line", gap=8)
            pill(line, "Transcribing", ON_ACCENT, ACCENT, ON_ACCENT)
            text(line, "58%", 12, "Medium", TEXT_2, features={"tnum": True})
            progress(st, frac, 280)
            text(st, "Text · chunk 37 of 64 · about 4 min left", 12, "Regular", TEXT_3)
        elif kind == "queued":
            pill(st, "Queued · next", TEXT_2, BORDER)
        elif kind == "review":
            line = hstack(st, "Line", gap=8)
            pill(line, "Ready", OK, OK_SOFT, OK)
            pill(line, detail.replace(" spots", ""), WARN, WARN_SOFT)
        elif kind == "done":
            line = hstack(st, "Line", gap=8)
            pill(line, "Ready", OK, OK_SOFT, OK)
            if "·" in detail:
                text(line, detail.split("· ")[1], 12, "Regular", TEXT_3)
        elif kind == "failed":
            line = hstack(st, "Line", gap=8)
            pill(line, "Failed", DANGER, DANGER_SOFT, DANGER)
            text(line, detail, 12, "Regular", TEXT_2)
        t = text(row, added, 13, "Regular", TEXT_2)
        cmd("node.set", {"ids": [R(t)], "props": {"textAutoResize": "height", "width": 104}})
        icon(row, "more", TEXT_3, 18)


def library(x: float, y: float, name: str = "02 Library", selected: int | None = None) -> str:
    win, main = shell(name, x, y, "library")
    hdr = page_header(main, "Library", "12 recordings · 2 in progress")
    button(hdr, "Add recordings", "primary", "plus")
    frame(hdr, "gap", 8, 1)
    f11_hint(hdr)
    library_table(main, selected)
    return win


def overlay(win: str) -> str:
    return frame(win, "Scrim", W, H, fill="#000000A6", absolute=True, x=0, y=0)


def add_dialog(x: float, y: float) -> None:
    win = library(x, y, "03 Add recordings")
    overlay(win)
    dlg = vstack(
        win,
        "Dialog",
        gap=0,
        fill=SURFACE,
        cornerRadius=12,
        effects=SHADOW_LG,
        sizingH="fixed",
        absolute=True,
        x=(W - 720) / 2,
        y=120,
        clip=True,
    )
    cmd("node.set", {"ids": [R(dlg)], "props": {"width": 720}})
    head = hstack(dlg, "Head", gap=8, pad=[18, 22, 14, 22], sizingH="fill")
    text(head, "Add recordings", 17, "SemiBold", TEXT, sizingH="fill")
    icon(head, "x", TEXT_3, 18)
    body = vstack(dlg, "Body", gap=18, pad=[4, 22, 20, 22], sizingH="fill")
    drop = vstack(
        body,
        "Dropzone",
        gap=8,
        pad=[22, 16, 22, 16],
        sizingH="fill",
        crossAlign="center",
        fill=SURFACE_2,
        stroke=BORDER_STRONG,
        strokeWeight=1.2,
        dashes=[5, 4],
        cornerRadius=10,
    )
    icon(drop, "upload", ACCENT, 24)
    text(drop, "Drop audio or video files, or a whole folder", 14, "Medium", TEXT)
    acts = hstack(drop, "Actions", gap=8)
    button(acts, "Choose files…", "secondary", "file", small=True)
    button(acts, "Choose folder…", "secondary", "folder", small=True)
    lst = vstack(
        body,
        "Files",
        gap=0,
        sizingH="fill",
        stroke=BORDER,
        strokeWeight=1,
        cornerRadius=8,
        clip=True,
    )
    for i, (n, d, sz) in enumerate(
        [
            ("apollo12_landing_1969.mp3", "14:02", "13 MB"),
            ("apollo14_eva_1971.mp3", "52:30", "48 MB"),
            ("apollo15_rover_1971.mp3", "1:04:10", "59 MB"),
        ]
    ):
        r = hstack(
            lst,
            f"File/{n}",
            gap=10,
            pad=[9, 12, 9, 12],
            sizingH="fill",
            **(edge("bottom", BORDER) if i < 2 else {}),
        )
        icon(r, "file", TEXT_3, 16)
        text(r, n, 13.5, "Regular", TEXT, sizingH="fill")
        text(r, d, 12.5, "Regular", TEXT_2, features={"tnum": True})
        text(r, sz, 12.5, "Regular", TEXT_3)
        icon(r, "x", TEXT_3, 14)
    opts = hstack(body, "Options", gap=20, align="min", sizingH="fill")
    spk = vstack(opts, "Speakers", gap=8)
    text(spk, "Speakers", 13, "SemiBold", TEXT)
    srow = hstack(spk, "Range", gap=8)
    text(srow, "Between", 13, "Regular", TEXT_2)
    field(srow, "2", width=52, trailing="chev")
    text(srow, "and", 13, "Regular", TEXT_2)
    field(srow, "3", width=52, trailing="chev")
    kt = vstack(opts, "Key terms", gap=8, sizingH="fill")
    lbl = hstack(kt, "Label", gap=6)
    text(lbl, "Key terms", 13, "SemiBold", TEXT)
    text(lbl, "optional", 12, "Regular", TEXT_3)
    box = hstack(
        kt,
        "Chips input",
        gap=6,
        pad=[6, 8, 6, 8],
        sizingH="fill",
        fill=SURFACE,
        stroke=BORDER_STRONG,
        strokeWeight=1,
        cornerRadius=6,
        wrap=True,
    )
    for term in ["Houston", "CAPCOM", "Antares"]:
        chip(box, term, TEXT, SURFACE_2, None, removable=True)
    text(box, "Add a name, place or term…", 13, "Regular", TEXT_3)
    para(kt, "Spell names the way they should appear. Used as hints, not guaranteed.", 12, TEXT_3)
    foot = hstack(
        dlg, "Footer", gap=10, pad=[14, 22, 14, 22], sizingH="fill", fill=SURFACE_2, **edge("top")
    )
    cb = frame(foot, "Checkbox", 16, 16, fill=ACCENT, cornerRadius=4)
    vec(cb, ICON["check"], 11, 11, stroke=ON_ACCENT, sw=2, absolute=True, x=2.5, y=2.5)
    text(foot, "Save speakers and key terms as my defaults", 13, "Regular", TEXT_2, sizingH="fill")
    button(foot, "Cancel", "secondary")
    button(foot, "Add 3 recordings", "primary")


# --- Transcript editor ------------------------------------------------------
# Sample transcript: Apollo 11 lunar landing, 20 July 1969 (NASA air-to-ground; public domain).
TURNS = [
    ("Duke (CAPCOM)", 0, "08:54", "60 seconds."),
    (
        "Aldrin",
        1,
        "08:57",
        "Lights on. Down two and a half. Forward. Forward. Good. 40 feet, down two and a "
        "half. Picking up some dust. 30 feet, two and a half down. Faint shadow. Four "
        "forward. Four forward, drifting to the right a little. 20 feet, down a half.",
    ),
    ("Duke (CAPCOM)", 0, "09:29", "30 seconds."),
    ("Aldrin", 1, "09:32", "Drifting forward just a little bit. That's good. Contact light."),
    ("Armstrong", 2, "09:40", "Shutdown."),
    ("Aldrin", 1, "09:41", "Okay. Engine stop."),
    ("Duke (CAPCOM)", 0, "09:45", "We copy you down, Eagle."),
    (
        "Armstrong",
        2,
        "09:52",
        "Engine arm is off. Houston, Tranquility Base here. The Eagle has landed.",
    ),
    (
        "Duke (CAPCOM)",
        0,
        "10:04",
        "Roger, Twan… Tranquility, we copy you on the ground. You got a bunch of guys "
        "about to turn blue. We're breathing again. Thanks a lot.",
    ),
    ("Aldrin", 1, "10:17", "Thank you."),
    ("Duke (CAPCOM)", 0, "10:19", "You're looking good here."),
]
ACTIVE_TURN = 8


def turn_block(
    parent: str, idx: int, who: str, spk: int, ts: str, body: str, active: bool = False
) -> str:
    # Accent edge drawn as a left border: a fill-height child inside a hug-height row collapses it.
    t = hstack(
        parent,
        f"Turn {idx}",
        gap=0,
        align="min",
        sizingH="fill",
        pad=[10, 12, 10, 0],
        cornerRadius=8,
        fill=ACCENT_TINT if active else None,
        **(edge("left", ACCENT, 3) if active else {}),
    )
    gut = vstack(t, "Gutter", gap=6, pad=[3, 0, 0, 0], sizingH="fixed")
    cmd("node.set", {"ids": [R(gut)], "props": {"width": 70, "paddingLeft": 14}})
    text(gut, ts, 12, "Medium", ACCENT_TEXT if active else TEXT_3, features={"tnum": True})
    if active:
        icon(gut, "pause", ACCENT, 14)
    col = vstack(t, "Body", gap=6, sizingH="fill")
    who_row = hstack(col, "Speaker", gap=6)
    dot(who_row, 8, SPK[spk])
    text(who_row, who, 12.5, "SemiBold", SPK[spk])
    icon(who_row, "chev", TEXT_3, 12)
    p = para(col, body, 16.5, TEXT, READ, lh=27)
    return p


def player(main: str, track_w: float = 1230, compact: bool = False) -> None:
    bar = hstack(
        main, "Player", gap=14, pad=[12, 24, 12, 24], sizingH="fill", fill=SURFACE, **edge("top")
    )
    icon(bar, "rewind", TEXT_2, 18)
    pb = frame(bar, "Play", 38, 38, fill=ACCENT, cornerRadius=999)
    vec(pb, ICON["pause"], 14, 14, stroke=ON_ACCENT, sw=2.4, absolute=True, x=12, y=12)
    text(bar, "10:09", 13, "SemiBold", TEXT, features={"tnum": True})
    tl = frame(bar, "Timeline", 10, 28, sizingH="fill", fill=SURFACE_2, cornerRadius=6, clip=True)
    # speaker segments across a 5-minute track (rough real pattern of the test file)
    segs = [
        (0, 0.06, 0),
        (0.07, 0.19, 1),
        (0.20, 0.24, 2),
        (0.25, 0.37, 1),
        (0.38, 0.42, 0),
        (0.43, 0.52, 1),
        (0.53, 0.57, 2),
        (0.58, 0.66, 1),
        (0.67, 0.70, 0),
        (0.71, 0.76, 1),
        (0.77, 0.80, 2),
        (0.81, 0.84, 0),
        (0.85, 0.90, 1),
        (0.91, 0.95, 2),
        (0.96, 1.0, 0),
    ]
    for a, b, s in segs:
        cmd(
            "node.create",
            {
                "type": "rectangle",
                "parent": R(tl),
                "width": max((b - a) * track_w - 2, 2),
                "height": 10,
                "props": {
                    "fill": SPK[s],
                    "opacity": 0.55,
                    "cornerRadius": 3,
                    "absolute": True,
                    "x": a * track_w,
                    "y": 9,
                },
            },
        )
    # the current selection's time range, shown as a band on the timeline
    cmd(
        "node.create",
        {
            "type": "rectangle",
            "parent": R(tl),
            "width": max(0.012 * track_w, 6),
            "height": 28,
            "props": {
                "fill": ACCENT,
                "opacity": 0.35,
                "absolute": True,
                "x": 0.803 * track_w,
                "y": 0,
            },
        },
    )
    cmd(
        "node.create",
        {
            "type": "rectangle",
            "parent": R(tl),
            "width": 2,
            "height": 28,
            "props": {"fill": TEXT, "absolute": True, "x": 0.811 * track_w, "y": 0},
        },
    )
    text(bar, "12:31", 13, "Regular", TEXT_3, features={"tnum": True})
    chip(bar, "1.0×", TEXT)
    if compact:
        return
    follow = hstack(bar, "Follow", gap=6)
    tg = frame(follow, "Toggle", 28, 16, fill=ACCENT, cornerRadius=999)
    dot(tg, 12, "#FFFFFF", absolute=True, x=14, y=2)
    text(follow, "Follow", 12.5, "Regular", TEXT_2)


def editor_panel(body: str) -> None:
    panel = vstack(
        body,
        "Side panel",
        gap=18,
        pad=[16, 18, 16, 18],
        fill=SURFACE,
        sizingV="fill",
        sizingH="fixed",
        **edge("left"),
    )
    cmd("node.set", {"ids": [R(panel)], "props": {"width": 340}})
    tabs = hstack(panel, "Tabs", gap=4, pad=3, fill=SURFACE_2, cornerRadius=8, sizingH="fill")
    for label, act in [("Speakers", True), ("Details", False)]:
        tab = hstack(
            tabs,
            f"Tab/{label}",
            gap=0,
            pad=[6, 8, 6, 8],
            cornerRadius=6,
            sizingH="fill",
            mainAlign="center",
            fill=SURFACE if act else None,
            **({"effects": SHADOW_SM} if act else {}),
        )
        text(tab, label, 12.5, "Medium" if act else "Regular", TEXT if act else TEXT_2)
    for name, spk, turns, share in [
        ("Duke (CAPCOM)", 0, "58 turns", 0.41),
        ("Aldrin", 1, "49 turns", 0.38),
        ("Armstrong", 2, "31 turns", 0.21),
    ]:
        card = vstack(
            panel,
            f"Speaker/{name}",
            gap=10,
            pad=12,
            stroke=BORDER,
            strokeWeight=1,
            cornerRadius=8,
            sizingH="fill",
        )
        top = hstack(card, "Top", gap=8, sizingH="fill")
        dot(top, 10, SPK[spk])
        field(top, name)
        r2 = hstack(card, "Sample", gap=8, sizingH="fill")
        button(r2, "Play sample", "secondary", "play", small=True)
        spacer(r2)
        text(r2, f"{turns} · {int(share * 100)}%", 12, "Regular", TEXT_3, features={"tnum": True})
        progress(card, share, 278, SPK[spk], 4)
    merge = hstack(panel, "Merge", gap=8)
    icon(merge, "speaker", ACCENT, 15)
    text(merge, "Merge or split speakers…", 13, "Medium", ACCENT_TEXT)
    divider(panel)
    section_label(panel, "Key terms")
    kt = hstack(panel, "Terms", gap=6, wrap=True, sizingH="fill")
    for term in ["Tranquility", "Eagle", "CAPCOM"]:
        chip(kt, term, TEXT, SURFACE_2, None)
    section_label(panel, "Keys")
    keys = vstack(panel, "Shortcuts", gap=6, sizingH="fill")
    for k, d in [
        ("Ctrl+Space", "Play / pause"),
        ("Ctrl+J", "Jump to playing"),
        ("Enter", "Split turn here"),
        ("Alt+↑ / ↓", "Change speaker"),
        ("Select words", "Listen and replace"),
    ]:
        row = hstack(keys, k, gap=8, sizingH="fill")
        text(row, d, 12.5, "Regular", TEXT_2, sizingH="fill")
        kb = hstack(
            row,
            "Kbd",
            gap=0,
            pad=[2, 6, 2, 6],
            fill=SURFACE_2,
            cornerRadius=4,
            stroke=BORDER,
            strokeWeight=1,
        )
        text(kb, k, 11.5, "Medium", TEXT_2)


def editor(x: float, y: float, compact: bool = False, pop_xy: tuple[float, float] = (0, 0)) -> None:
    name = "07 Transcript editor (960×720 minimum)" if compact else "04 Transcript editor"
    win, main = shell(
        name, x, y, "library", w=CW if compact else W, h=CH if compact else H, compact=compact
    )
    top = hstack(
        main, "Topbar", gap=12, pad=[14, 24, 14, 20], sizingH="fill", **edge("bottom"), fill=BG
    )
    back = hstack(top, "Back", gap=4)
    icon(back, "back", TEXT_2, 16)
    text(back, "Library", 13, "Regular", TEXT_2)
    divider(top, vertical=True)
    tcol = vstack(top, "Title", gap=1, sizingH="fill")
    trow = hstack(tcol, "Name", gap=6)
    text(trow, "apollo11_landing_1969", 16, "SemiBold", TEXT)
    icon(trow, "pencil", TEXT_3, 14)
    text(tcol, "12:31 · 3 speakers · English · saved 2 min ago", 12, "Regular", TEXT_3)
    if compact:
        button(top, "", "secondary", "export", small=True)
        button(top, "", "secondary", "speaker", small=True)  # opens the side panel as an overlay
    else:
        button(top, "Undo", "ghost")
        button(top, "Export", "secondary", "export")
    icon(top, "more", TEXT_2, 18)
    f11_hint(top, "Full screen" if compact else "Exit full screen")

    body = hstack(main, "Body", gap=0, align="min", sizingH="fill", sizingV="fill")
    doc = vstack(
        body,
        "Transcript",
        gap=6,
        pad=[20, 24, 20, 16] if compact else [24, 40, 24, 40],
        sizingH="fill",
        sizingV="fill",
        clip=True,
        crossAlign="center",
    )
    # reading column: capped width so lines stay readable at 1080p
    col = vstack(doc, "Column", gap=6, sizingH="fill" if compact else "fixed")
    if not compact:
        cmd("node.set", {"ids": [R(col)], "props": {"width": 900}})
    doc = col
    find = hstack(doc, "Find", gap=8, sizingH="fill", pad=[0, 0, 8, 0])
    field(find, "Find in transcript", placeholder=True, icon_name="search")
    chip(find, "Show timestamps", TEXT_2)
    for i, (who, spk, ts, body_text) in enumerate(TURNS):
        if compact and i < 3:
            continue
        p = turn_block(doc, i, who, spk, ts, body_text, active=(i == ACTIVE_TURN))
        if i == ACTIVE_TURN:
            # playing word, and a user selection ("Twan… Tranquility") being listened to
            style_word(p, body_text, "breathing", textFills=[ACCENT_TEXT], fontStyle="SemiBold")
            style_word(
                p,
                body_text,
                "Twan… Tranquility",
                textFills=[TEXT],
                textDecoration="underline",
                textDecorationColor=ACCENT,
                textDecorationThickness=3,
                textDecorationOffset=4,
            )
    # select-and-listen popover: select any words, replay exactly that audio, type a replacement
    pop = vstack(
        win,
        "Selection popover",
        gap=10,
        pad=14,
        fill=SURFACE,
        cornerRadius=10,
        effects=SHADOW_LG,
        stroke=BORDER,
        strokeWeight=1,
        sizingH="fixed",
        absolute=True,
        x=pop_xy[0],
        y=pop_xy[1],
    )
    cmd("node.set", {"ids": [R(pop)], "props": {"width": 320}})
    ph = hstack(pop, "Head", gap=8, sizingH="fill")
    text(ph, "2 words selected", 13, "SemiBold", TEXT, sizingH="fill")
    text(ph, "10:05.1 – 10:06.3", 12, "Regular", TEXT_3, features={"tnum": True})
    ctr = hstack(pop, "Listen", gap=8, sizingH="fill")
    button(ctr, "Play selection", "secondary", "play", small=True)
    chip(ctr, "Loop", TEXT_2)
    chip(ctr, "0.75×", TEXT_2)
    lab = vstack(pop, "Replace", gap=6, sizingH="fill")
    text(lab, "Replace with", 12, "Medium", TEXT_2)
    field(lab, "Twan… Tranquility")
    acts = hstack(pop, "Actions", gap=8, sizingH="fill")
    text(acts, "Space plays · Enter replaces", 12, "Regular", TEXT_3, sizingH="fill")
    button(acts, "Cancel", "secondary", small=True)
    button(acts, "Replace", "primary", small=True)

    if not compact:
        editor_panel(body)
    player(main, track_w=470 if compact else 1230, compact=compact)


def details_drawer(x: float, y: float) -> None:
    win = library(x, y, "05 Job details", selected=0)
    overlay(win)
    dr = vstack(
        win,
        "Drawer",
        gap=18,
        pad=[18, 22, 18, 22],
        fill=SURFACE,
        effects=SHADOW_LG,
        sizingH="fixed",
        sizingV="fixed",
        absolute=True,
        x=W - 480,
        y=0,
    )
    cmd("node.set", {"ids": [R(dr)], "props": {"width": 480, "height": H}})
    head = hstack(dr, "Head", gap=8, sizingH="fill")
    col = vstack(head, "Title", gap=3, sizingH="fill")
    text(col, "apollo13_problem_1970.mp3", 16, "SemiBold", TEXT)
    text(col, "18:44 · 17 MB · added today 14:02", 12, "Regular", TEXT_3)
    icon(head, "x", TEXT_3, 18)
    st = hstack(dr, "Status", gap=8, sizingH="fill")
    pill(st, "Transcribing", ON_ACCENT, ACCENT, ON_ACCENT)
    text(st, "58% · about 4 min left", 12.5, "Regular", TEXT_2)
    section_label(dr, "Stages")
    stages = vstack(
        dr,
        "Stages",
        gap=0,
        sizingH="fill",
        stroke=BORDER,
        strokeWeight=1,
        cornerRadius=8,
        clip=True,
    )
    data = [
        ("Read audio", "0.5 s", "done"),
        ("Find speech", "5.6 s", "done"),
        ("Word timings", "1 min 08 s", "done"),
        ("Transcribe text", "37 of 64 chunks", "run"),
        ("Identify speakers", "", "todo"),
        ("Assemble transcript", "", "todo"),
    ]
    for i, (lab, val, s) in enumerate(data):
        r = hstack(
            stages,
            lab,
            gap=10,
            pad=[10, 12, 10, 12],
            sizingH="fill",
            fill=ACCENT_TINT if s == "run" else None,
            **(edge("bottom", BORDER) if i < len(data) - 1 else {}),
        )
        if s == "done":
            c = frame(r, "Done", 18, 18, fill=OK_SOFT, cornerRadius=999)
            vec(c, ICON["check"], 10, 10, stroke=OK, sw=2, absolute=True, x=4, y=4)
        elif s == "run":
            c = frame(
                r, "Running", 18, 18, fill=None, cornerRadius=999, stroke=ACCENT, strokeWeight=2
            )
            dot(c, 6, ACCENT, absolute=True, x=6, y=6)
        else:
            frame(
                r,
                "Todo",
                18,
                18,
                fill=None,
                cornerRadius=999,
                stroke=BORDER_STRONG,
                strokeWeight=1.5,
            )
        text(
            r,
            lab,
            13.5,
            "Medium" if s == "run" else "Regular",
            TEXT if s != "todo" else TEXT_3,
            sizingH="fill",
        )
        text(r, val, 12.5, "Regular", TEXT_2, features={"tnum": True})
    grid = vstack(dr, "Facts", gap=8, sizingH="fill")
    for k, v in [
        ("Device", "AMD Radeon 660M · Vulkan"),
        ("Speakers", "between 2 and 4"),
        ("Key terms", "Odyssey, Aquarius, Houston"),
        ("Language", "English"),
    ]:
        r = hstack(grid, k, gap=8, sizingH="fill")
        t = text(r, k, 12.5, "Regular", TEXT_3)
        cmd("node.set", {"ids": [R(t)], "props": {"textAutoResize": "height", "width": 90}})
        text(r, v, 12.5, "Regular", TEXT, sizingH="fill")
    section_label(dr, "Log")
    log = vstack(
        dr, "Log", gap=3, pad=12, fill="#0B0C0E", cornerRadius=8, sizingH="fill", sizingV="fill"
    )
    for ln in [
        "14:02:11  queued",
        "14:04:37  started on Vulkan0 (Radeon 660M)",
        "14:04:38  read audio: 1124.3 s",
        "14:04:43  64 speech chunks",
        "14:05:51  word timings done (68 s)",
        "14:05:53  text model loaded (Qwen3-ASR 1.7B Q8)",
        "14:07:41  chunk 37/64",
    ]:
        text(log, ln, 11.5, "Regular", "#C9D1D9", fontFamily="Liberation Mono")
    acts = hstack(dr, "Actions", gap=8, sizingH="fill")
    button(acts, "Stop", "danger", "pause")
    spacer(acts)
    button(acts, "Copy log", "ghost")
    button(acts, "Open log file", "ghost")


def settings(x: float, y: float) -> None:
    hh = 1240 if H < 1240 else H
    win, main = shell("06 Settings", x, y, "settings", h=hh, update="1.1.1")
    f11_hint(page_header(main, "Settings"))
    col = vstack(main, "Sections", gap=16, pad=[0, 28, 28, 28], sizingH="fixed")
    cmd("node.set", {"ids": [R(col)], "props": {"width": 900}})

    def card(title: str, sub: str | None = None) -> str:
        c = vstack(
            col,
            title,
            gap=14,
            pad=18,
            fill=SURFACE,
            cornerRadius=10,
            stroke=BORDER,
            strokeWeight=1,
            sizingH="fill",
            effects=SHADOW_SM,
        )
        hc = vstack(c, "Head", gap=2, sizingH="fill")
        text(hc, title, 15, "SemiBold", TEXT)
        if sub:
            text(hc, sub, 12.5, "Regular", TEXT_3)
        return c

    def row(c: str, label: str, hint: str | None, control) -> None:
        r = hstack(c, label, gap=16, sizingH="fill", align="center")
        lc = vstack(r, "Label", gap=2, sizingH="fill")
        text(lc, label, 13.5, "Medium", TEXT)
        if hint:
            para(lc, hint, 12, TEXT_3)
        control(r)

    c = card("Processing", "Where transcription runs.")
    row(
        c,
        "Device",
        "Falls back to the processor automatically if the graphics card fails.",
        lambda r: field(r, "Automatic — Radeon 660M (Vulkan)", width=300, trailing="chev"),
    )
    row(
        c,
        "Processor threads",
        "Used when running on the processor. Automatic = physical cores − 1.",
        lambda r: field(r, "Automatic (5)", width=300, trailing="chev"),
    )

    c = card("New recordings", "Defaults for the Add recordings dialog.")

    def spk_ctrl(r: str) -> None:
        h = hstack(r, "Range", gap=8)
        field(h, "2", width=52, trailing="chev")
        text(h, "to", 13, "Regular", TEXT_2)
        field(h, "3", width=52, trailing="chev")

    row(c, "Speakers", "The usual number of people in your recordings.", spk_ctrl)

    def kt_ctrl(r: str) -> None:
        box = hstack(
            r,
            "Chips",
            gap=6,
            pad=[6, 8, 6, 8],
            fill=SURFACE,
            stroke=BORDER_STRONG,
            strokeWeight=1,
            cornerRadius=6,
            sizingH="fixed",
            wrap=True,
        )
        cmd("node.set", {"ids": [R(box)], "props": {"width": 300}})
        chip(box, "Houston", TEXT, SURFACE_2, None, removable=True)
        text(box, "Add…", 13, "Regular", TEXT_3)

    row(c, "Key terms", "Names and jargon added to every new recording.", kt_ctrl)

    c = card("Speech models", "Downloaded once. Everything runs on this computer.")
    tbl = vstack(
        c, "Models", gap=0, sizingH="fill", stroke=BORDER, strokeWeight=1, cornerRadius=8, clip=True
    )
    models = [
        ("Qwen3-ASR 1.7B", "Transcription text", "2.19 GB"),
        ("Parakeet TDT 0.6B v3", "Word timings", "640 MB"),
        ("Speaker models", "Segmentation + voice embeddings", "47 MB"),
        ("Silero VAD", "Speech detection", "0.6 MB"),
    ]
    for i, (n, role, sz) in enumerate(models):
        r = hstack(
            tbl,
            n,
            gap=10,
            pad=[9, 12, 9, 12],
            sizingH="fill",
            **({"strokeBottomWeight": 1, "stroke": BORDER} if i < len(models) - 1 else {}),
        )
        nc = vstack(r, "Name", gap=1, sizingH="fill")
        text(nc, n, 13, "Medium", TEXT)
        text(nc, role, 12, "Regular", TEXT_3)
        text(r, sz, 12.5, "Regular", TEXT_2, features={"tnum": True})
        pill(r, "Verified", OK, OK_SOFT, OK)
    fr = hstack(c, "Folder", gap=8, sizingH="fill")
    field(fr, "~/.local/share/wavematerial/models", icon_name="folder")
    button(fr, "Change…", "secondary", small=True)
    ar = hstack(c, "Actions", gap=8)
    button(ar, "Verify all", "secondary", "check", small=True)
    button(ar, "Remove downloaded models", "ghost-danger", "trash", small=True)

    c = card("Updates")

    def toggle_ctrl(r: str) -> None:
        tg = frame(r, "Toggle", 36, 20, fill=ACCENT, cornerRadius=999)
        dot(tg, 16, "#FFFFFF", absolute=True, x=18, y=2)

    row(
        c,
        "Check for new versions once a day",
        "Only asks GitHub whether a newer release exists.",
        toggle_ctrl,
    )
    ur = hstack(c, "Version", gap=10, sizingH="fill")
    vt = hstack(ur, "Message", gap=8, sizingH="fill")
    text(vt, "WaveMaterial 1.1.1 is available.", 13, "Regular", TEXT_2)
    text(vt, "Open the release page", 13, "Medium", ACCENT_TEXT)
    button(ur, "Check now", "secondary", "refresh", small=True)
    # The open tooltip sits above the buttons, so the row must not clip it (frames clip by
    # default in FigCraft).
    acts = hstack(c, "Update actions", gap=18, pad=[8, 0, 8, 0], clip=False)

    def help_tip(parent: str) -> str:
        q = frame(
            parent, "Help tip", 18, 18, fill=SURFACE_2, stroke=BORDER_STRONG, strokeWeight=1,
            cornerRadius=999, layout="horizontal", mainAlign="center", crossAlign="center",
        )  # fmt: skip
        text(q, "?", 11, "SemiBold", TEXT_2)
        return q

    for label, kind in [("Self-update", "primary"), ("Manual update", "secondary")]:
        a = hstack(acts, label, gap=6)
        button(a, label, kind, small=True)
        help_tip(a)
    tip = vstack(
        acts, "Tooltip (Self-update)", gap=0, pad=[9, 11, 9, 11], fill=SURFACE_2,
        stroke=BORDER_STRONG, strokeWeight=1, cornerRadius=6, effects=SHADOW_LG,
        absolute=True, x=-10, y=-104, sizingH="fixed",
    )  # fmt: skip
    cmd("node.set", {"ids": [R(tip)], "props": {"width": 300}})
    para(
        tip,
        "Installs the update for you and reopens WaveMaterial. It downloads and checks the new "
        "version, waits for any transcription to finish, then closes, installs, and opens again.",
        12,
        TEXT,
        lh="145%",
    )

    c = card("About")
    para(
        c,
        "WaveMaterial 1.1.0 · Licensed GPL-2.0-only WITH Universal-FOSS-exception-1.0. "
        "Speech models by Alibaba Qwen and NVIDIA (CC-BY-4.0), pyannote, and Silero.",
        12.5,
        TEXT_2,
    )
    lk = hstack(c, "Links", gap=16)
    text(lk, "Licences and credits", 13, "Medium", ACCENT_TEXT)
    text(lk, "Open data folder", 13, "Medium", ACCENT_TEXT)
    text(lk, "Open logs", 13, "Medium", ACCENT_TEXT)


def first_run(x: float, y: float) -> None:
    win = screen("01 First run", x, y, layout="vertical", mainAlign="center", crossAlign="center")
    hint_box = hstack(win, "Corner", gap=0, absolute=True, x=W - 170, y=22)
    f11_hint(hint_box)
    card = vstack(
        win,
        "Card",
        gap=20,
        pad=32,
        fill=SURFACE,
        cornerRadius=14,
        stroke=BORDER,
        strokeWeight=1,
        effects=SHADOW_LG,
        sizingH="fixed",
    )
    cmd("node.set", {"ids": [R(card)], "props": {"width": 620}})
    head = hstack(card, "Head", gap=14)
    logo_mark(head, 52, tile=True)
    hc = vstack(head, "Titles", gap=2)
    text(hc, "Welcome to WaveMaterial", 22, "SemiBold", TEXT, letterSpacing="-1%")
    text(hc, "Transcripts with speakers, made entirely on this computer.", 13.5, "Regular", TEXT_2)
    para(
        card,
        "One step before you start: download the speech models. After that WaveMaterial "
        "works offline.",
        13.5,
        TEXT_2,
    )
    cta = vstack(card, "Download", gap=8, sizingH="fill", crossAlign="center")
    big = hstack(cta, "Button/Download models", gap=0, pad=[12, 32, 12, 32], fill=ACCENT,
                 cornerRadius=6, effects=SHADOW_SM)  # fmt: skip
    text(big, "Download models", 15, "SemiBold", ON_ACCENT)
    text(cta, "2.9 GB on disk (a 2.7 GB download)", 12, "Regular", TEXT_2)
    fold = vstack(card, "Saving to", gap=6, sizingH="fill")
    text(fold, "Saving to", 13, "Medium", TEXT)
    fr = hstack(fold, "Folder", gap=8, sizingH="fill")
    field(fr, "/home/you/.local/share/wavematerial/models", icon_name="folder")
    button(fr, "Change folder", "secondary", small=True)
    section_label(card, "What will be downloaded")
    lst = vstack(
        card, "Models", gap=0, sizingH="fill", stroke=BORDER, strokeWeight=1, cornerRadius=8,
        clip=True,
    )  # fmt: skip
    models = [
        ("Qwen3-ASR 1.7B (Q8_0 GGUF)", "Text · Apache-2.0 · from huggingface.co", "2.19 GB"),
        ("Parakeet TDT 0.6B v3 (int8)", "Word timings · CC-BY-4.0 · from github.com", "487 MB"),
        ("Silero VAD", "Speech chunks · MIT · from github.com", "644 KB"),
        (
            "pyannote segmentation 3.0",
            "Diarisation: who speaks when · MIT · from github.com",
            "7 MB",
        ),
        ("TitaNet small", "Diarisation: voice embeddings · CC-BY-4.0 · from github.com", "40 MB"),
    ]
    for n, (name, info, size) in enumerate(models):
        r = hstack(
            lst, name, gap=10, pad=[7, 12, 7, 12], sizingH="fill",
            **({"strokeBottomWeight": 1, "stroke": BORDER} if n < len(models) - 1 else {}),
        )  # fmt: skip
        nc = vstack(r, "Name", gap=1, sizingH="fill")
        text(nc, name, 13, "Regular", TEXT_2)
        text(nc, info, 12, "Regular", TEXT_3)
        text(r, size, 12.5, "Regular", TEXT_2, features={"tnum": True})
    gpu = hstack(card, "Device", gap=6)
    icon(gpu, "check", OK, 13)
    text(gpu, "Fast mode available", 12, "SemiBold", TEXT_2)
    text(gpu, "· Using your AMD Radeon 660M graphics (Vulkan).", 12, "Regular", TEXT_2)


# --- Design system ---------------------------------------------------------
def design_system() -> None:
    cmd("page.add", {"name": "Design system"})
    pass  # page.add switches to the new page
    pg = screen("Design system", 0, 0, w=1280, h=1040, layout="vertical", padding=40, gap=28)
    text(pg, "WaveMaterial — design system (dark)", 24, "SemiBold", TEXT)

    def group(title: str) -> str:
        g = vstack(pg, title, gap=12, sizingH="fill")
        section_label(g, title)
        return g

    g = group("Colour")
    row = hstack(g, "Swatches", gap=12, wrap=True, sizingH="fill")
    for n, c in [
        ("bg", BG),
        ("surface", SURFACE),
        ("sidebar", SIDEBAR),
        ("border", BORDER),
        ("border-strong", BORDER_STRONG),
        ("text", TEXT),
        ("text-2", TEXT_2),
        ("text-3", TEXT_3),
        ("accent", ACCENT),
        ("accent-text", ACCENT_TEXT),
        ("accent-soft", ACCENT_SOFT),
        ("accent-tint", ACCENT_TINT),
        ("warn", WARN),
        ("warn-soft", WARN_SOFT),
        ("danger", DANGER),
        ("danger-soft", DANGER_SOFT),
        ("ok", OK),
        ("ok-soft", OK_SOFT),
    ]:
        sw = vstack(row, n, gap=6)
        rect(sw, 104, 52, c, cornerRadius=8, stroke=BORDER, strokeWeight=1)
        text(sw, n, 12, "Medium", TEXT)
        text(sw, c, 11.5, "Regular", TEXT_3)
    g = group("Speaker palette")
    row = hstack(g, "Speakers", gap=12)
    for i, c in enumerate(SPK):
        s = hstack(
            row,
            f"S{i + 1}",
            gap=8,
            pad=[6, 12, 6, 10],
            cornerRadius=999,
            stroke=BORDER,
            strokeWeight=1,
            fill=SURFACE,
        )
        dot(s, 10, c)
        text(s, f"Speaker {i + 1}", 12.5, "SemiBold", c)
        text(s, c, 11.5, "Regular", TEXT_3)
    g = group("Type")
    for label, size, wt, fam, sample in [
        ("Page title · Inter SemiBold 22", 22, "SemiBold", UI, "Library"),
        ("Section · Inter SemiBold 15", 15, "SemiBold", UI, "Speech models"),
        (
            "Body · Inter Regular 13.5",
            13.5,
            "Regular",
            UI,
            "Downloaded once. Everything runs on this computer.",
        ),
        ("Small · Inter Regular 12", 12, "Regular", UI, "Text · chunk 24 of 41 · about 2 min left"),
        (
            "Transcript · Noto Sans 16.5 / 27",
            16.5,
            "Regular",
            READ,
            "So the Europeans became conscious of the need for stability of yield.",
        ),
    ]:
        r = hstack(g, label, gap=24, sizingH="fill")
        t = text(r, label, 12, "Regular", TEXT_3)
        cmd("node.set", {"ids": [R(t)], "props": {"textAutoResize": "height", "width": 260}})
        text(r, sample, size, wt, TEXT, family=fam, sizingH="fill")
    g = group("Components")
    row = hstack(g, "Buttons", gap=10)
    button(row, "Add recordings", "primary", "plus")
    button(row, "Export", "secondary", "export")
    button(row, "Undo", "ghost")
    button(row, "Stop", "danger", "pause")
    button(row, "Play sample", "secondary", "play", small=True)
    row = hstack(g, "Status", gap=10)
    pill(row, "Transcribing", ON_ACCENT, ACCENT, ON_ACCENT)
    pill(row, "Queued · next", TEXT_2, BORDER)
    pill(row, "Ready", OK, OK_SOFT, OK)
    pill(row, "Failed", DANGER, DANGER_SOFT, DANGER)
    chip(row, "All", count="12", active=True)
    chip(row, "Tranquility", TEXT, SURFACE_2, None, removable=True)
    row = hstack(g, "Inputs", gap=10)
    field(row, "Search transcripts", width=240, placeholder=True, icon_name="search")
    field(row, "Automatic — Radeon 660M (Vulkan)", width=300, trailing="chev")
    progress(row, 0.58, 200)


# Selection popover positions (absolute, in window coordinates): tuned by eye from renders.
POPOVER_XY = (566, 584)  # above "Twan" in the playing turn
POPOVER_XY_COMPACT = (178, 304)


def main() -> None:
    cmd("page.rename", {"name": "Screens"})
    gap = 160
    first_run(0, 0)
    library(W + gap, 0)
    add_dialog(0, H + gap)
    editor(W + gap, H + gap, pop_xy=POPOVER_XY)
    details_drawer(0, 2 * (H + gap))
    settings(W + gap, 2 * (H + gap))
    editor(0, 3 * (H + gap), compact=True, pop_xy=POPOVER_XY_COMPACT)
    design_system()
    out = Path(__file__).with_name("mockups.json")
    out.write_text(json.dumps(steps, indent=1, ensure_ascii=False))
    print(f"wrote {out} ({len(steps)} steps)")


if __name__ == "__main__":
    main()
