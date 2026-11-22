# WaveMaterial: visual design

The design system for the 1.2.0 UI. Behaviour is specified in
[`docs/SPEC.md`](../docs/SPEC.md); the mock-ups show how it looks.

## Files

| File | What |
|---|---|
| `wavematerial.figcraft` | The mock-ups (FigCraft). Pages: **Screens** and **Design system**. |
| `exports/*.png` | Each screen at 1920 × 1080. Screen 07 is the 960 × 720 minimum. |
| `logo/app-icon.svg` | **The logo master, made by hand.** Every other logo file is generated from it. |
| `logo/logo-mark*.svg`, `logo/png/`, `logo/app-icon.ico` | Generated variants, PNGs, and the Windows icon. |
| `logo/wavematerial-logo.vectorcraft`, `logo/replica/` | The logo rebuilt in VectorCraft, and its pixel comparison with the master. |
| `tools/` | Generators (`logo_variants.py`, `build_logo_vectorcraft.py`, `build_mockups.py`) and the contrast audit (`contrast.py`). |

To regenerate everything, from `design/`:

```
uv run python tools/logo_variants.py
uv run python tools/build_logo_vectorcraft.py
uv run python tools/build_mockups.py          # writes tools/mockups.json (gitignored)
figcraft-cli run tools/mockups.json --out wavematerial.figcraft
figcraft-cli export wavematerial.figcraft -o exports/ --page Screens
figcraft-cli export wavematerial.figcraft -o exports/ --page "Design system"
```

The mock-ups are generated, so change `tools/build_mockups.py`, not the FigCraft file.

## Screens

| # | Screen |
|---|---|
| 00 | Landing: the logo large in the middle, the name, the tagline, Open library, Add recordings, and Quit; the sidebar logo returns to it |
| 01 | First run: asks before the one-time model download. One dominant, focused **Download models** button with the size under it (2.9 GB on disk, a 2.7 GB download); Saving to with **Change folder**; the model list, quiet (name, role, licence, source, size); the device note small at the bottom. Problems (no room, a folder it can't write to, OneDrive, a missing drive) show under the button; the progress view replaces the button in place |
| 02 | Library: every recording, with filter chips (All, Not started, In progress, Done, Failed) and search. Not started rows come first, with a small secondary **Start**; finished rows have a small secondary **Edit transcript**; both sit before the row's ⋯ menu. **Start N not started** (secondary) sits beside Add recordings while there are any |
| 03 | Add recordings (dialog): files or a folder, speaker range, key terms. The footer has Cancel (ghost), **Add to library** (secondary), and **Add and transcribe** (primary, ▶), with a small line under them: "Add to library keeps them as Not started until you press Start." |
| 04 | Transcript editor |
| 05 | Job details (drawer): stages, device, log, Stop and Retry, **Copy log** (a ready-to-paste report) and Open log file |
| 06 | Settings, shown with an update available: the models card has **Remove downloaded models** (red, ghost); the Updates card has **Self-update** (primary) and **Manual update** (secondary), each with a help tip, one shown open |
| 07 | Editor at the 960 × 720 minimum: the sidebar becomes an icon rail and the side panel an overlay |
| 08 | Job details (drawer) of a finished recording: **Edit transcript** (primary) and Open output folder (secondary) under the status; Delete moves to the footer |

The shell is a 248 px sidebar (logo, Library, Editor, Recent, the engine card, and Settings).
**Editor** (pencil) has a second line, "Last: <name>", in text-3; in the editor it is the
active item (surface fill, accent icon) and the open transcript is lit the same way in
Recent; with nothing finished it is dimmed (text-3) with "No transcripts yet". The
**Not started** pill is surface-2 with text-2 and its dot. Below
about 1280 px wide it becomes a 60 px icon rail. When a newer version exists, a small notice
("Version 1.1.1 is available", surface-2 fill) sits above the engine card and leads to
Settings; in the rail it is just its icon.

**Help tip:** a small round "?" (18 px, surface-2, border-strong, text-2) beside a control.
On hover or keyboard focus it opens a tooltip above it: surface-2, border-strong, 6 px
radius, the raised shadow, text 12 px, about 300 px wide. Its text leads with what is
different about the control. It is a focusable button whose text screen readers read.

In the editor's Speakers tab each speaker has its own "Merge into…" action, in place of the
mock-up's single "Merge or split speakers…" link. A selection across neighbouring turns adds
"Merge N turns into one" with a speaker menu to the select-and-listen popover.

## Colour tokens

Dark only. Text meets 4.5:1 and graphics meet 3:1; `tools/contrast.py` checks every pair.

| Token | Value | Use |
|---|---|---|
| bg | `#111214` | app background |
| surface / surface-2 | `#151518` / `#202328` | panels / inputs, chips, headers |
| sidebar | `#0B0C0E` | sidebar, log |
| border / border-strong | `#2A2D33` / `#3B3F46` | dividers / inputs |
| text / text-2 / text-3 | `#ECECEC` / `#A8ACB3` / `#858A91` | body / secondary / tertiary |
| **accent** | **`#C81400`** | fills, borders, icons: primary buttons, progress, playhead, selection band, logo tile (3.17:1 on bg, so never text) |
| **accent-text** | **`#D75647`** | red text: active chips, the playing word, links (≥ 4.58:1) |
| on-accent | `#FFFFFF` | text on red fills (5.91:1) |
| accent-soft / accent-tint | `#2A0D08` / `#1C1210` | selected chip / playing-turn background |
| warn | `#F0B04A` (soft `#33270F`) | warnings |
| danger | `#FF8A80` (soft `#3A1717`) | failures, always with an icon |
| ok | `#4CC38A` (soft `#11291D`) | ready, verified |
| speakers | `#4FB8C0` `#E0A04A` `#A08CEB` `#6FA3F2` `#A8C36A` `#D58BD5` | speaker colours; no reds |

## Type and shape

- **UI:** Inter (Regular, Medium, SemiBold). **Transcript:** Noto Sans 16.5 / 27 px. Logs are
  monospace.
- **Scale:** page title 22 · section 15 · body 13.5 · small 12 · caps labels 11 (+6 % tracking).
- **Grid:** 8 px. Reading column 900 px wide at 1080p.
- **Radius:** 6 px controls, 8–10 px cards, 12–14 px dialogs. 1 px borders separate surfaces;
  shadows only on raised surfaces (dialog, popover, drawer).
- Pico.css's root font scaling and spacing are overridden to reach this density.

## Logo

A rounded red tile (`#C81400`) with a yellow sickle (`#FFE600`, 4.66:1 on the tile) and a
five-bar yellow waveform (`#FFFF00`). To change it, edit `logo/app-icon.svg` and rerun the
generators; never hand-edit the generated files.

## Sample content

Mock-ups, docs, and screenshots use public-domain recordings only. The mock-ups' editor
shows NASA's Apollo 11 lunar landing (20 July 1969). The USAGE screenshots and the README
video use a minute of the LibriVox dramatic reading of Chekhov's *The Seagull* (Act I,
3:00–4:00), whose speakers are known from its cast (see `scripts/demo/`).
