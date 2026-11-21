# WaveMaterial 1.0: specification

The decisions that bind 1.0.0. Anything not listed here is open; propose it in an issue
before building it. Visual design: [`design/DESIGN.md`](../design/DESIGN.md).

## Product

- A fully local desktop app that turns audio and video files, one or a batch, into
  speaker-attributed **English** transcripts, with an editor to correct them.
- Linux and Windows. Vulkan GPU first (integrated GPUs included), CPU as a fallback.
- Speed budget: processing time ≤ 0.9 × audio length on the reference machine.
- Offline after first run. The only network calls are the model downloads and the update
  check. No telemetry, no accounts.
- **Not in 1.0.0:** other languages, CUDA, macOS, a light theme, live transcription,
  translation or summarisation, automatic self-update, importing models from files,
  editable timings, and output-formatting work (cue splitting, paragraphing, headers).

## Engine

| Step | Component | Runtime |
|---|---|---|
| Decode | Any audio or video file → 16 kHz mono float32, in memory (no temp WAV) | PyAV (its bundled FFmpeg; no system ffmpeg) |
| Speech chunks | Silero VAD; chunks ≤ 20 s, split at pauses of ≥ 0.4 s, each side padded by up to 0.2 s into silence | sherpa-onnx |
| Word timings | Parakeet TDT 0.6B v3 int8 (its text is discarded) | sherpa-onnx |
| Text | Qwen3-ASR-1.7B Q8_0 GGUF, per chunk, language forced to English | transcribe.cpp |
| Align | Matching words take Parakeet's timing; differing spans are interpolated | Python |
| Diarise | pyannote segmentation-3.0 + TitaNet-small + fast clustering (window shift 0.5, threshold 1.0, 2–3 speakers by default) | sherpa-onnx |
| Merge | Each word goes to the speaker it overlaps most; speakers numbered `SPEAKER_00`… in order of appearance | Python |

- Only one model is loaded at a time.
- CJK characters (such as the filler 嗯) are removed from each chunk's English text.
- **Key terms:** each job may carry a list of names and jargon that is passed to Qwen as
  vocabulary, with a default list in Settings. It is a best-effort hint, untested.

## Devices

- The startup preflight takes **≤ 2 s**. It only detects devices: no benchmarking and no
  network.
- Order: a real **Vulkan** device, then the **CPU**. Software rasterisers (llvmpipe,
  lavapipe, SwiftShader) count as no GPU. Under WSL, the translated Dozen device is not
  preferred.
- The CPU uses physical cores − 1 threads, minimum 1.
- If a job fails on the GPU (backend error or out of memory), it is rerun on the CPU from
  its last saved stage, and the GPU is remembered as unreliable until the user resets it.
- Settings can override the choice: auto, a specific Vulkan device, or CPU, plus a thread
  count.

## Jobs

- One job per media file, and jobs run one at a time. States: `queued → running → done |
  failed | cancelled`. Naming speakers and editing are actions on a done job.
- Each stage saves its result to the job's folder: `chunks.json`, `timings.json`,
  `text.jsonl` (one line per chunk), `diarization.json`, then `artifact.json`. After a
  crash, a job that was `running` goes back to `queued` and resumes from its last saved
  stage.
- Jobs are stored in SQLite (WAL mode). Heavy work runs in one worker subprocess per job,
  never in the web server. Progress comes back as JSON lines over a pipe.
- Controls: Pause (finish the current job, then stop the queue), Stop (cancel and keep the
  saved stages), Resume, Retry (from the last good stage), reorder, and Delete.
- On resume, the source file's fingerprint is checked; a changed or missing source fails
  with a clear message.
- Only one instance of the app runs at a time.

## Transcripts

- `artifact.json` is the model output and is **never modified** after it is written. It
  holds the schema version, language, duration, speakers, engine metadata, and turns with
  word timings.
- User edits and speaker names are saved as a separate current revision. Every output is
  rendered from that revision, and the original can always be restored.
- Outputs: `json`, `txt`, `srt`, and `vtt` are always produced; `docx` and `pdf` are made
  on export. Plain formatting: `SPEAKER: text` per turn, one subtitle cue per turn.
  `docx` and `pdf` also carry a centred title, then Speakers and Duration lines, a centred
  TRANSCRIPT heading, and the turns justified.
- **Editor:** fix words; change a turn's speaker; name, merge, and split speakers; split
  and join turns; find and replace; undo and redo; rename the recording. Selecting any
  words plays exactly that audio, with Loop, 0.75× speed, and a Replace field. Clicking a
  timestamp plays from there, and Follow highlights the spoken word. Edits autosave.
  There are no review flags.
- Speakers: renaming one relabels every turn and output; "Merge into…" moves all of one
  speaker's turns to another; a turn's speaker menu offers "New speaker". A selection
  spanning neighbouring turns can merge them into one turn with a chosen speaker.
- The editor plays `playback.opus`, a mono Ogg Opus copy (~32 kbit/s) of the audio that
  the decode stage writes into the job folder (made once by the worker for older jobs).
- Export offers docx and pdf only when their optional libraries are installed.
- Shift+click extends a selection into another turn. A right-click menu in the text offers
  Play from here, Split turn here, Move rest to next turn, Move start to previous turn, and
  for a selection Play selection, Copy, Merge turns, and Transcribe again.
- History: named versions to restore (undoably), the original transcript, and the last 3
  automatic versions saved when a transcript is opened.
- Transcribe again: a whole recording becomes a new entry in the queue; a passage is
  re-transcribed in place as a proposal to accept, when no transcription is running.
- Play starts at the cursor's word if the cursor was placed since playback stopped. Esc
  pauses playback. The dividers between sidebar, transcript, and side panel can be dragged.

## Data and settings

Paths come from `platformdirs`. Nothing is written inside the install folder.

| What | Linux | Windows |
|---|---|---|
| Settings (`config.toml`) | `~/.config/wavematerial/` | `%APPDATA%\wavematerial\` |
| Jobs (`jobs.db`, one folder per job) | `~/.local/share/wavematerial/` | `%LOCALAPPDATA%\wavematerial\` |
| Models (~2.9 GB) | `~/.local/share/wavematerial/models/` | `%LOCALAPPDATA%\wavematerial\models\` |
| Logs | `~/.local/state/wavematerial/logs/` | `%LOCALAPPDATA%\wavematerial\logs\` |
| Downloads in progress | `~/.cache/wavematerial/` | `%LOCALAPPDATA%\wavematerial\cache\` |

- Flatpak uses the same layout under `~/.var/app/<app-id>/`. It gets read-only access to
  the home folder, plus the file-chooser portal for saving.
- Settings are TOML. The models folder can be moved in Settings. Outputs stay in the job's
  folder; Export copies them out.
- Uninstalling keeps jobs and models. The Windows uninstaller asks whether to delete them.

## Models

- A manifest shipped with the app lists each model's URL (pinned to an exact version),
  size, sha256, licence, creator, upstream model card, and what was changed from the
  original (for example, converted to ONNX or quantised to Q8_0).
- Models are downloaded from upstream only (Hugging Face and sherpa-onnx releases) over
  plain HTTPS: no mirroring and no token.
- Downloads resume after an interruption, are retried, and are sha256-verified before they
  are used. Each launch checks file sizes only; a full check is in Settings.
- Model updates come with app updates.

| Model | Role | Licence |
|---|---|---|
| Qwen3-ASR-1.7B Q8_0 GGUF | text | Apache-2.0 |
| Parakeet TDT 0.6B v3 int8 | word timings | CC-BY-4.0 |
| Silero VAD | speech chunks | MIT |
| pyannote segmentation-3.0 (ONNX) | diarisation | MIT |
| TitaNet-small | speaker embeddings | CC-BY-4.0 |

## Updates

- The app checks GitHub releases at most once a day, plus a "Check now" button. The check
  can be turned off in Settings.
- If a newer version exists, the app links to its release page. Installing is manual.
- Offline or failed checks are silent.

## UI

- A pywebview window over Flask on waitress, bound to `127.0.0.1` on a random port, with a
  per-launch token on every request. "Open in browser" is the fallback when the system web
  view is missing.
- Server-rendered HTML with htmx; live updates come from polling small fragments. All
  front-end assets are vendored, so nothing is fetched at run time.
- Pico.css v2 plus our own stylesheet. Dark only. Fullscreen 1920 × 1080 by default; F11
  leaves full screen for a 1280 × 720 (16:9, 720p) window, and back; Esc also leaves it
  when no dialog or panel is open. The minimum window is
  960 × 720.
- The app opens on a landing screen: the logo, the name, the tagline "Offline, Vulkan-first
  transcription with speaker diarisation and transcript editing", Open library, Add
  recordings (straight from there), and Quit. The sidebar's logo returns to it.
- The sidebar has **Quit WaveMaterial** and a search over titles and transcript text. If no
  window can open, the app opens in the browser and exits 5 minutes after its last page
  closes.

## Licence

- **GPL-2.0-only WITH Universal-FOSS-exception-1.0.** Never GPLv3, never "or later".
- The exception allows combining with OSI-approved or FSF-free software (such as
  Apache-2.0 sherpa-onnx), but not with proprietary code.
- Contributions are accepted under the same licence and exception.
- Model weights are downloaded at run time, never shipped. CC-BY models are credited on
  the About page.
- Packages bundle PyAV's FFmpeg (LGPL-3.0-or-later) and the libraries in its wheel,
  including x264 and x265 (GPL-2.0-or-later). Each release offers their exact source.
- **About page** (in Settings, works offline):
  - WaveMaterial's version and licence, with the full text, and a link to the source of
    that exact release;
  - each model's required credit, from the manifest;
  - every bundled component with its version and licence, and its licence text.
- The component list and licence texts are **generated from the bundle** when packages are
  built, plus a short hand-kept list for what pip can't see (the Python runtime, FFmpeg's
  libraries, the vendored front end, and fonts). The build **fails** if a component has no
  licence, or one that is GPL-3.0 (only or or-later), any AGPL, or proprietary.

## Distribution

- Python 3.12. Every package wraps the same bundle: a standalone Python runtime with the app
  and its locked dependencies. Models are not bundled.
- The bundle is built by `packaging/bundle.py`, for Linux or Windows, and holds no paths
  from the machine that built it. Its launcher runs the bundled Python with
  bytecode writing off; all bytecode is precompiled. Runtime modules the app doesn't need are
  left out.
- **Arch Linux first:** a `PKGBUILD` (not published to the AUR), plus a Linux `.tar.gz` of
  the same bundle with no compatibility guarantees.
- **`.deb`** for Debian 13 and later.
- Both Linux packages depend on GStreamer's "good" plugins, which WebKitGTK needs to play
  audio; without them the app turns playback off and says so.
- **Flatpak** for other Linux distributions, as a `.flatpak` file on GitHub releases.
- **Windows `.exe`** installer, per user (no admin rights needed), into
  `%LOCALAPPDATA%\Programs\WaveMaterial`; its shortcuts run the bundled `pythonw.exe -m
  wavematerial`. Inno Setup builds it under Wine (`packaging/windows/build.py`).
- The Windows bundle ships none of Microsoft's C++ runtime (wheels' private copies included).
  The installer requires the Visual C++ Redistributable (x64) at the newest version the
  bundled files were built with, and offers Microsoft's download page if it is missing.
- Everything is built locally; there is no CI. Nothing is signed. Each release carries
  SHA256 checksums.

## Support claims

- WaveMaterial is tested on one machine (Ryzen 5 7535HS, Radeon 660M, 14 GB RAM, Linux) and
  one recording. Everything else is "untested, should work", and the README says so.
- Windows builds are made and tested only under Wine (Bottles), never on real Windows.
- Requirements are stated as measured: peak 3.4 GB RAM on the CPU path; about 1.2 GB plus
  2.2 GB of shared GPU memory on Vulkan; 2.9 GB of models on disk.
