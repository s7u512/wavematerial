# Changelog

Every user-visible change is recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.2.0] - 2026-11-22

### Added
- **Add to library** in the Add recordings dialog: the recordings are listed as **Not
  started** and wait until you press **Start** on one, or **Start N not started** at the top
  of the library. A **Not started** filter lists them.
- **Edit transcript** on every finished recording: a button on its library row, the first
  item in its ⋯ menu, and the main button of its details.
- **Editor** in the sidebar, under Library: it reopens the transcript you last had open
  (shown as "Last: …"), and lights up with that transcript in Recent while you edit.

### Changed
- The Add recordings dialog's main button is now **Add and transcribe**, which says what it
  does (it starts them, as before).
- The library's database gains a version number and is brought up to date when WaveMaterial
  starts. After running 1.2.0, an older version can't open your library; update rather than
  going back.

### Fixed
- Dropping files onto the app window now works on Linux; the app no longer logs an
  `'EventContainer' object has no attribute 'drop'` error on every page load.
- On KDE, WaveMaterial no longer logs a "QT cannot be loaded" error at start-up: on
  Linux it always opens its window with GTK.

## [1.1.0] - 2026-11-22

### Added
- **Self-update** and **Manual update** for the Windows installer and the Linux `.tar.gz`:
  when a newer version exists (Settings, and a small notice in the sidebar), Self-update
  downloads it from the release page, checks it against the release's checksums, waits
  until no transcription is running, then installs it and reopens WaveMaterial; Manual
  update lets you go through the installer yourself (Windows) or saves the new version in
  your Downloads folder (Linux). A "?" by each button says what it does. Nothing updates
  without your click. Running from source shows the notice only.
- **Copy log** on every job's details: copies a ready-to-paste report (app version, system,
  device, the job's settings, events, and the end of its log, with your home folder shown
  as ~) for reporting problems on the issues page.
- **Change folder** on the first-run screen: the models go in a "WaveMaterial models"
  folder in the folder you pick (models already there are used). Folders WaveMaterial can't
  write to, and folders synced by OneDrive, are refused; Settings' move follows the same
  rules. If a chosen folder's drive is gone, WaveMaterial says so.
- **Remove downloaded models** in Settings, and `wavematerial models --remove`. On Windows,
  uninstalling asks whether to delete the speech models too.

### Changed
- WaveMaterial asks before downloading its speech models (2.9 GB on disk). The first-run
  screen has one clear **Download models** button, lists each model with its licence and
  source, and checks the free space first (3.7 GB, counting what unpacking needs), refusing
  with a message if there isn't room. Partial downloads now stay in the models folder.
- A transcription that crashes now says so in plain words ("crashed (error 0xC0000005)"
  instead of a raw exit code) and suggests copying the log for a report, and the log now
  shows where in the program the crash happened.

### Fixed
- Windows: transcription no longer crashes right after "Read audio" ("stopped unexpectedly
  (exit code 3221225477)") on PCs where Windows has its own, older copy of a library
  WaveMaterial needs (ONNX Runtime), as some Windows 11 versions do. WaveMaterial now always
  uses its own copy. If Windows' copy gets in anyway, the job stops with a plain message
  when that copy can't work, or goes on with a warning in its log when it can.
- The usage guide said the daily update check is off by default; it is on (and can be
  turned off in Settings).

## [1.0.0] - 2026-11-21

### Added
- A Windows installer: per user, no admin rights needed. It is built and tested only
  under Wine. Windows needs Microsoft's Visual C++ Redistributable (x64), which the
  installer checks for.
- A portable Linux `.tar.gz` with its own Python runtime, a desktop entry, and icons (built
  on Arch Linux, no compatibility guarantees). On Linux the window now shows WaveMaterial's
  icon in docks and task switchers.
- The app window: first-run model download (resumable, with pause), the library with
  filters and search, adding recordings (files, folders, or drag and drop) with speaker
  range and key terms, job details with stages and log, settings, and licences and credits.
  F11 or Esc leaves full screen.
- The app opens on a landing screen with the logo, the name, and its tagline.
- When no app window can open, WaveMaterial runs in the browser with a Quit WaveMaterial
  item in the sidebar, and quits by itself a few minutes after its last tab closes.
- Opening a finished recording shows its transcript with a player: play from any
  timestamp or Ctrl+click a word, Follow highlights the spoken word, and selecting words
  plays exactly that audio (with Loop and 0.75×). The side panel lists the speakers with a
  sample of each, and the recording's details.
- Editing transcripts: fix words in place (edited words keep approximate timings), split
  a turn with Enter and join turns with Backspace, change a turn's speaker (menu or
  Alt+↑/↓, including a new speaker), replace selected words, merge neighbouring turns
  into one, and undo and redo. Edits save automatically and update every output file;
  the model's original output is kept unchanged.
- Naming speakers in the editor's Speakers panel (every turn and output follows), and
  "Merge into…" for when one person was split into two speakers.
- Find and replace in the editor (Ctrl+F, Ctrl+H), renaming a recording from its title,
  and "Restore original transcript" (undoable).
- Export from the editor: plain text, SRT and WebVTT subtitles, JSON with word timings,
  and, with the optional `export` extra, .docx and PDF. In the window a Save dialog asks
  where, starting in the last folder used. The .docx and PDF open with the centred title,
  the speakers and duration, and a TRANSCRIPT heading, with the transcript justified.
- Editor, second round: Shift+click selects across turns; a right-click menu in the text;
  Move rest to next turn and Move start to previous turn; Play starts at the cursor; Esc
  pauses playback; a History tab with named versions, automatic versions on opening, and
  the original transcript; draggable dividers between sidebar, transcript, and panel; a
  search box in the sidebar; Quit WaveMaterial in the sidebar.
- Transcribe again: a whole recording as a new entry ("name (2)") from the Library or the
  editor, and a selected passage from the editor's right-click menu, shown as a proposal
  to accept (available while no recording is being transcribed).
- Each transcription keeps a small Ogg Opus copy of its audio for playback, so the player
  works with any input format and after the original is moved.
- Transcription runs in the background, one recording at a time, resumes after a crash or
  a stop, and moves to the processor if the graphics card fails.
- Command line: `wavematerial models` (download or verify the models) and
  `wavematerial transcribe FILE`.
