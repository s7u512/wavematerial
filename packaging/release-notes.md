<!-- SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
Release notes template for packaging/release.py: {changes} is the version's CHANGELOG
section; {exe}, {tarball}, {source} and {thirdparty} are the file names. -->
Offline, Vulkan-first transcription with speaker diarisation and transcript editing.

{changes}

## Downloads

| File | For |
|---|---|
| `{exe}` | Windows 10 or 11, 64-bit. Installs for your user, no administrator rights. Needs the [Microsoft Visual C++ Redistributable (x64)](https://aka.ms/vs/17/release/vc_redist.x64.exe). |
| `{tarball}` | Linux, no compatibility guarantees (built on Arch Linux). Needs WebKitGTK 4.1, a Vulkan loader, and GStreamer's "good" plugins. Unpack and run `bin/wavematerial`. |
| `{source}` | WaveMaterial's source code. Anyone else can [run from source](https://github.com/s7u512/wavematerial#run-from-source). |
| `{thirdparty}` | The exact sources of the copyleft libraries bundled in the files above (FFmpeg, x264, x265, and others), with a manifest. |
| `SHA256SUMS` | Checksums of every file. Nothing is signed. |

On first run WaveMaterial asks before downloading its speech models (2.9 GB on disk); after
that it works offline. From 1.1.0 on, installed copies update themselves (Settings › Self-update);
older versions need this download once.

## Tested on

One machine (Ryzen 5 9600X, GeForce RTX 5060 Ti through Vulkan, 15 GB RAM, Arch Linux) and a
few recordings. Windows builds are made and tested only under Wine, never on real Windows.
Everything else is "untested, should work".
