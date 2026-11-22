<p align="center">
  <img src="design/logo/app-icon.svg" width="160" height="160" alt="WaveMaterial logo">
</p>

<h1 align="center">WaveMaterial</h1>

<p align="center">
  <strong>Offline, Vulkan-first transcription with speaker diarisation and transcript editing.</strong>
</p>

A fully local desktop app that turns audio and video recordings into speaker-attributed
English transcripts, with an editor to correct them. It runs offline after a one-time model
download, on Linux and Windows, using a Vulkan GPU when there is one and the CPU otherwise.

https://github.com/user-attachments/assets/5e39ee3f-cb3d-407c-8191-58b4d60480f1

> **WaveMaterial 1.0.0** is out: a Windows installer and a Linux `.tar.gz` are on the
> [releases page](https://github.com/s7u512/wavematerial/releases), or run it from source
> (below). What it does is in [`docs/SPEC.md`](docs/SPEC.md), and the visual design is in
> [`design/DESIGN.md`](design/DESIGN.md).

See [`USAGE.md`](USAGE.md) for a tour of every screen, with screenshots.

## Install

Downloads are on the [releases page](https://github.com/s7u512/wavematerial/releases), with
SHA256 checksums and the source code. Nothing is signed. On first run WaveMaterial asks
before downloading its speech models (2.9 GB on disk); after that it works offline.

- **Windows 10 or 11 (64-bit):** `WaveMaterial-<version>-windows-x86_64-setup.exe`. It
  installs for your user only and needs no administrator rights, but Windows must already
  have the Microsoft Visual C++ Redistributable (see below).
- **Linux:** `wavematerial-<version>-linux-x86_64.tar.gz`. Unpack it and run
  `bin/wavematerial`; its `README.txt` explains adding it to your applications menu. It is
  built on Arch Linux with no compatibility guarantees, and needs WebKitGTK 4.1, a Vulkan
  loader for fast mode, and GStreamer's "good" plugins for playback.
- **Anything else, or if the `.tar.gz` doesn't run:** run from source.

### Windows needs one thing first

The Windows installer doesn't include Microsoft's Visual C++ runtime, because its licence
isn't a free-software licence. Windows must have the **Microsoft Visual C++ Redistributable
(x64)**, in a recent version; many PCs already do. The installer checks, names the version
it needs, and offers Microsoft's download if it's missing. Installing the redistributable
needs administrator rights; WaveMaterial itself doesn't.

- Direct download (always Microsoft's latest x64 version):
  <https://aka.ms/vs/17/release/vc_redist.x64.exe>
- Microsoft's page for it, with other versions and details:
  <https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist>

## Run from source

You need [uv](https://docs.astral.sh/uv/) (it fetches Python 3.12 if you don't have it) and
git. On Linux, PyGObject is built against your system's libraries, so you also need a C
compiler, WebKitGTK 4.1, and GStreamer's "good" plugins:

- Arch Linux: `sudo pacman -S --needed base-devel webkit2gtk-4.1 gst-plugins-good vulkan-icd-loader`
- Debian 13 (untested): `sudo apt install build-essential pkg-config libgirepository-2.0-dev
  libcairo2-dev gir1.2-webkit2-4.1 gstreamer1.0-plugins-good libvulkan1`

Then:

```
git clone https://github.com/s7u512/wavematerial
cd wavematerial
uv run --extra export wavematerial
```

(`--extra export` adds .docx and PDF export.) On Windows the same commands should work in
PowerShell (tested only under Wine); the app window needs the WebView2 runtime, which
Windows 10 and 11 include.

## Honest support claims

When 1.0.0 is released, it will have been tested on one machine (Ryzen 5 7535HS,
Radeon 660M, 14 GB RAM, Arch Linux) and with one recording. Windows builds are made and
tested only under Wine (Bottles), never on real Windows. Everything else will be
"untested, should work".

## Development

You need [uv](https://docs.astral.sh/uv/); `uv sync` fetches Python 3.12 if you don't have it.

```
uv sync
uv run ruff check && uv run ruff format --check
uv run pytest
```

Read [`CONTRIBUTING.md`](CONTRIBUTING.md) before opening a pull request. Report security
issues as described in [`SECURITY.md`](SECURITY.md).

## Licence

GPL-2.0-only WITH Universal-FOSS-exception-1.0. See [`LICENSE.md`](LICENSE.md), and
[`THIRD_PARTY.md`](THIRD_PARTY.md) for third-party components.
