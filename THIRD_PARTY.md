# Third-party components

Everything in this repository that is not our own work, with its licence and source. A new
dependency, font, icon, image, or sample is added here in the same change that adds it.
Model weights are never committed; their licences and credits live in the model manifest.

This file covers the source tree. The list shipped inside each package is generated from
the bundle when the package is built (see `docs/SPEC.md`, Licence).

## Runtime dependencies

Installed from `uv.lock` and shipped in every package.

| Component | Licence | Source |
|---|---|---|
| PyAV (`av`) | BSD-3-Clause | https://pypi.org/project/av/ |
| platformdirs | MIT | https://pypi.org/project/platformdirs/ |
| tomli-w | MIT | https://pypi.org/project/tomli-w/ |
| psutil | BSD-3-Clause | https://pypi.org/project/psutil/ |
| NumPy | BSD-3-Clause (bundled parts: 0BSD, MIT, Zlib, CC0-1.0) | https://pypi.org/project/numpy/ |
| transcribe-cpp | MIT | https://pypi.org/project/transcribe-cpp/ |
| transcribe-cpp-native (includes ggml) | MIT | https://pypi.org/project/transcribe-cpp-native/ |
| sherpa-onnx | Apache-2.0 | https://pypi.org/project/sherpa-onnx/ |
| sherpa-onnx-core (includes ONNX Runtime, MIT) | Apache-2.0 | https://pypi.org/project/sherpa-onnx-core/ |
| Flask, Werkzeug, Jinja2, MarkupSafe, itsdangerous, click | BSD-3-Clause | https://pypi.org/project/flask/ |
| blinker | MIT | https://pypi.org/project/blinker/ |
| waitress | ZPL-2.1 | https://pypi.org/project/waitress/ |
| pywebview | BSD-3-Clause | https://pypi.org/project/pywebview/ |
| bottle, proxy-tools (used by pywebview) | MIT | https://pypi.org/project/bottle/ |
| typing-extensions | PSF-2.0 | https://pypi.org/project/typing-extensions/ |
| PyGObject (Linux) | LGPL-2.1-or-later | https://pypi.org/project/PyGObject/ |
| pycairo (Linux) | LGPL-2.1-only OR MPL-1.1 | https://pypi.org/project/pycairo/ |
| pythonnet, clr-loader, cffi, pycparser (Windows) | MIT, MIT, MIT-0, BSD-3-Clause | https://pypi.org/project/pythonnet/ |
| FFmpeg (inside the PyAV wheel) | LGPL-3.0-or-later | https://ffmpeg.org/ |
| x264 (inside the PyAV wheel) | GPL-2.0-or-later | https://www.videolan.org/developers/x264.html |
| x265 (inside the PyAV wheel) | GPL-2.0-or-later | https://www.x265.org/ |

The PyAV wheel also carries other libraries (among them dav1d, LAME, Opus, SVT-AV1, VMAF,
libvpl, libvpx, libwebp, and libxcb, plus their dependencies). Their licences and exact
sources are recorded when the packages are built, and each release offers that source.

## Development tools

Used to build and check the project; not shipped in installers.

| Component | Licence | Source |
|---|---|---|
| hatchling (build backend) | MIT | https://pypi.org/project/hatchling/ |
| pytest | MIT | https://pypi.org/project/pytest/ |
| ruff | MIT | https://pypi.org/project/ruff/ |

## Sample content

| Content | Where | Licence | Source |
|---|---|---|---|
| Apollo 11 lunar landing air-to-ground transcript (20 July 1969) | `design/` mock-ups | Public domain (NASA, US government work) | NASA Apollo 11 air-to-ground transcript |
| Titles of US government recordings (1950–1990) | `design/` mock-ups, library list | Public domain (US government works) | US government archives |

## Vendored front end

Committed under `src/wavematerial/web/static/`, each with its licence file beside it.

| Component | Version | Licence | Source |
|---|---|---|---|
| Pico CSS (`vendor/pico/`) | 2.1.1 | MIT | npm `@picocss/pico` |
| htmx (`vendor/htmx/`) | 2.0.11 | 0BSD | npm `htmx.org` |
| Inter, variable, Latin and Latin Extended (`fonts/inter/`) | Fontsource 5.3.0 | OFL-1.1 | npm `@fontsource-variable/inter` (https://rsms.me/inter/) |
| Noto Sans, variable, upright and italic (`fonts/noto-sans/`) | Fontsource 5.3.0 | OFL-1.1 | npm `@fontsource-variable/noto-sans` |

The icons (`web/icons.py`) and the logo (`static/img/app-icon.svg`, a copy of
`design/logo/app-icon.svg`) are our own work.
