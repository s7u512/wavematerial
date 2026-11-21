# Changelog

Every user-visible change is recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- A Windows installer: per user, no admin rights needed. It is built and tested only
  under Wine.
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
