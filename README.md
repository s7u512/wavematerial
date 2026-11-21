# WaveMaterial

**Offline, Vulkan-first transcription with speaker diarisation and transcript editing.**

A fully local desktop app that turns audio and video recordings into speaker-attributed
English transcripts, with an editor to correct them. It runs offline after a one-time model
download, on Linux and Windows, using a Vulkan GPU when there is one and the CPU otherwise.

> **Status: in development.** There is no release or installer yet; the app runs from
> source (`uv sync --extra export`, then `uv run --extra export wavematerial`). The plan
> for 1.0.0 is in [`docs/SPEC.md`](docs/SPEC.md), and the visual design is in
> [`design/DESIGN.md`](design/DESIGN.md).

## Honest support claims

When 1.0.0 is released, it will have been tested on one machine (Ryzen 5 7535HS,
Radeon 660M, 14 GB RAM, Arch Linux) and with one recording. Windows builds are made and
tested only under Wine (Bottles), never on real Windows. Everything else will be
"untested, should work".

## Windows needs one thing first

WaveMaterial's Windows installer doesn't include Microsoft's Visual C++ runtime, because
its licence isn't a free-software licence. Windows must have the **Microsoft Visual C++
Redistributable (x64)**, in a recent version; many PCs already do. The installer checks,
names the version it needs, and offers Microsoft's download page if it's missing. Installing
the redistributable needs administrator rights; WaveMaterial itself doesn't.

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
