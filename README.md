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

https://github.com/user-attachments/assets/c5d55654-e965-43e5-bcda-fe26cebf3074

> **WaveMaterial 1.1.0** is out: a Windows installer and a Linux `.tar.gz` are on the
> [releases page](https://github.com/s7u512/wavematerial/releases), or run it from source
> (below). New in 1.1.0: it asks before downloading the speech models, can update itself,
> and fixes a crash on some Windows 11 PCs (see [`CHANGELOG.md`](CHANGELOG.md)). What it
> does is in [`docs/SPEC.md`](docs/SPEC.md), and the visual design is in
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

From 1.1.0 on, the Windows installer and the Linux `.tar.gz` can update themselves: when a
new version is out, **Self-update** in Settings downloads it, checks it against the
release's checksums, installs it, and reopens WaveMaterial (**Manual update** lets you do
the last step yourself). Nothing updates without your click. Earlier versions need one
manual update.

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

WaveMaterial is tested on one machine (Ryzen 5 7535HS, Radeon 660M, 14 GB RAM, Arch Linux)
and with one recording. Windows builds are made and tested only under Wine (Bottles), never
on real Windows. Everything else is "untested, should work".

## Development

You need [uv](https://docs.astral.sh/uv/); `uv sync` fetches Python 3.12 if you don't have it.

```
uv sync
uv run ruff check && uv run ruff format --check
uv run pytest
```

## Contributing

Contributions are welcome. WaveMaterial is a small hobby project, so the rules are short:

- **Bugs and ideas:** open an issue on the
  [issues page](https://github.com/s7u512/wavematerial/issues). For a problem with a
  transcription, the recording's **Copy log** gives a ready-to-paste report.
- **Before writing code:** for anything beyond a small fix, open an issue first so we can
  agree on the approach. [`docs/SPEC.md`](docs/SPEC.md) lists what is decided.
- **Pull requests:** one change each, with
  [Conventional Commits](https://www.conventionalcommits.org/) messages, every commit signed
  off under the Developer Certificate of Origin (`git commit -s`), the checks above run, and
  a test for a bug fix. Contributions are licensed under the project's licence.
- **AI-assisted contributions** are welcome; you are responsible for every line you submit.

The full rules are in [`CONTRIBUTING.md`](CONTRIBUTING.md) and [`AGENTS.md`](AGENTS.md). Report
security issues privately, as described in [`SECURITY.md`](SECURITY.md).

## Licence

GPL-2.0-only WITH Universal-FOSS-exception-1.0. See [`LICENSE.md`](LICENSE.md), and
[`THIRD_PARTY.md`](THIRD_PARTY.md) for third-party components.
