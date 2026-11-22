# Demo screenshots and video

`make.py` makes the screenshots in `demo/usage/` (shown in `USAGE.md`) and the README video.
It is a maintainers' tool and runs on Linux only.

```
uv run --no-project --python 3.12.13 --with playwright --with pillow \
    scripts/demo/make.py check        # transcribe the demo recordings once, print them
uv run --no-project --python 3.12.13 --with playwright --with pillow \
    scripts/demo/make.py screenshots  # 01, 03, 05, 06, 08, 26, 28, 29 into demo/usage/
uv run --no-project --python 3.12.13 --with playwright --with pillow \
    scripts/demo/make.py video        # dist/demo/wavematerial-demo.webm
```

Needs `bwrap` (bubblewrap), `chromium` (or set `WM_CHROMIUM` to another Chromium build, such as
Playwright's headless shell), `ffmpeg`, the repo's `uv sync` environment, and the speech
models already downloaded (`uv run wavematerial models`). The other screenshots in
`demo/usage/` are from 1.0.0.

How it works:

- `serve.py` runs the app's server (no window) under bubblewrap with a private home,
  `/home/you`, so every path on screen is generic. The models are mounted read-only from
  this machine's models folder; the GPU is available. The file pickers are stubbed to the
  demo recordings. It never contacts GitHub; the "update available" screenshot uses a local
  stand-in.
- Playwright drives the system Chromium headless at 1920×1080. Screenshots are tagged
  300 ppi. The video is the first-run screen, then one uncut take: adding the recording,
  its transcription in real time, and the editor. A cursor dot is drawn, since recordings
  show no pointer. Recordings have no sound either, so the page logs when its audio plays
  and from where, and ffmpeg rebuilds the soundtrack from the recording at those moments
  (silence elsewhere). Encoded as VP9 with Opus sound.
- Sample audio: one minute (3:00–4:00) of Act I of the LibriVox dramatic reading of
  Chekhov's *The Seagull* (translated by Marian Fell; archive.org `seagull_0903_librivox`;
  LibriVox recordings are public domain), downloaded into `dist/cache/demo/`, checked
  against its SHA-1, and cut with ffmpeg.
- Each part has its own reader, so the speakers are known from the LibriVox cast: Masha
  (Philippa), Medviedenko (Ernst Pattynama), Sorin (Glenn Simonsen), and the stage
  directions (Hannah Dowell). The video's edits are real corrections checked against the
  Project Gutenberg text of the same translation: Sorin's speech, which the app puts with
  Medviedenko's (two men's voices), goes to a new speaker, and "Treplief" becomes
  "Treplieff", as the translation spells it.

The README video is uploaded through GitHub's editor (so it plays inline), not committed.
