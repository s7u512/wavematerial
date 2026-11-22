# Using WaveMaterial

A tour of every screen, in the order you meet them. The screenshots come from WaveMaterial
run from source (`uv run --extra export wavematerial`) full screen at 1920 × 1080, using two
public-domain NASA recordings made on board Apollo 11: the crew on their first orbit of
Earth, and the undocking before the Moon landing. Everything shown is what the app really
produced from them, mistakes included.

## Contents

- [First run](#first-run)
- [The landing screen](#the-landing-screen)
- [Adding recordings](#adding-recordings)
- [While recordings are transcribed](#while-recordings-are-transcribed)
- [The library](#the-library)
- [The editor](#the-editor)
  - [Playing the audio](#playing-the-audio)
  - [Selecting words](#selecting-words)
  - [Speakers](#speakers)
  - [Find and replace](#find-and-replace)
  - [The right-click menu](#the-right-click-menu)
  - [Transcribing a passage again](#transcribing-a-passage-again)
  - [History](#history)
  - [Details](#details)
  - [Exporting, renaming, and more](#exporting-renaming-and-more)
- [Settings](#settings)
- [Licences and credits](#licences-and-credits)

## First run

The first time it starts, WaveMaterial needs its speech models (2.9 GB on disk, a 2.7 GB
download). Nothing is downloaded until you click **Download models**. The screen lists each
model with its licence and source, and says whether WaveMaterial can use your graphics
card. **Change folder** puts the models somewhere else, for example on a bigger drive; they
go in a **WaveMaterial models** folder there, and models already in that folder are used
as they are. WaveMaterial won't save them in a folder it can't write to, or in one synced
by OneDrive. If the drive doesn't have room (3.7 GB, counting what the download needs
while it unpacks), it says so instead of starting. The download can be paused, and resumes
where it left off if it is interrupted. After this, nothing else is downloaded:
transcription runs entirely on your computer.

![First-run setup asking before it downloads the speech models](demo/usage/01-first-run-setup.png)

## The landing screen

WaveMaterial then opens on its landing screen. **Open library** shows your recordings;
**Add recordings…** goes straight to adding some. The logo at the top of the sidebar always
brings you back here. **F11** switches full screen and **Esc** leaves it.

![The landing screen](demo/usage/02-landing.png)

## Adding recordings

Drop audio or video files, or a whole folder, onto the dialog, or choose them. Any format
FFmpeg reads works. For each batch you can say how many people speak (a range is fine) and
give **key terms**: names and jargon spelled the way you want them. Key terms are hints to
the model, not guarantees; give only words that are really said, because the model may
otherwise put them where they don't belong. **Save as my defaults** remembers the choices.

**Add and transcribe** (or Enter) starts them straight away. **Add to library** only lists
them, as **Not started**, so you can collect recordings now and start them later: press
**Start** on a recording, or **Start N not started** at the top of the library for all of
them. Starting puts a recording at the end of the queue.

![The Add recordings dialog with two files, a speaker range, and a key term](demo/usage/03-add-recordings.png)

## While recordings are transcribed

Recordings are transcribed one at a time, in the background, in the order you added them.
The library shows the current stage and the time left; the sidebar shows the queue and the
device in use, with **Pause queue**. If WaveMaterial is closed or crashes, the queue
carries on from where it stopped next time. If the graphics card fails, the recording moves
to the processor.

![The library while the first recording is transcribed and the second waits](demo/usage/04-library-transcribing.png)

Click a recording for its details: each stage with its time, the settings used, and a log.
**Stop** stops it (you can resume it later). If something goes wrong, **Copy log** copies a
ready-to-paste report (versions, system, the recording's settings and log, with your home
folder shown as ~) for the [issues page](https://github.com/s7u512/wavematerial/issues);
**Open log file** opens the full log.

![The details drawer of a recording being transcribed](demo/usage/05-job-details.png)

## The library

Every recording, with its length, the number of speakers found, and its status. The tabs
filter by status. Click a row to open its transcript.

![The library with two finished recordings](demo/usage/06-library.png)

**Search transcripts** finds recordings by what was said in them.

![The library filtered to recordings that mention "trees"](demo/usage/07-library-search.png)

Each row's **⋯** menu has the details, the folder with the output files, **Transcribe
again…**, and **Delete** (which never touches the original file).

![A library row's menu](demo/usage/08-library-row-menu.png)

**Transcribe again…** adds the recording to the queue as a new entry ("name (2)"), with a
new speaker range and key terms if you like. The first transcript stays as it is.

![The Transcribe again dialog](demo/usage/09-transcribe-again.png)

The sidebar's search box finds recordings by title or text from any screen.

![Searching from the sidebar](demo/usage/10-sidebar-search.png)

## The editor

Opening a finished recording shows its transcript: one block per turn, each with its time
and speaker, and the player along the bottom with a coloured strip of who speaks when. The
side panel lists the speakers, the key terms used, and the keyboard shortcuts. Edits save
as you type and update every output file; the model's original output is always kept.

![The editor](demo/usage/11-editor.png)

### Playing the audio

**Play** (or **Ctrl+Space**) plays from the cursor; **Esc** pauses. **Ctrl+click** a word
plays from that word, and clicking a turn's time plays from the start of the turn. With
**Follow** on, the word being spoken is highlighted and kept in view. The speed button
steps through 0.75×, 1×, 1.25×, and 1.5×. Each transcription keeps a small copy of its audio, so the player works
even after the original file is moved.

![Playback with the spoken word highlighted](demo/usage/12-editor-playing-follow.png)

### Selecting words

Select words to hear exactly that audio: **Play selection** (or **Space**), with **Loop**
and **0.75×** for hard passages. Type a correction into **Replace with** and press
**Enter** to replace the selection. **Shift+click** in another turn selects across turns,
and then **Merge** joins them into one.

![A selection of ten words with its play and replace controls](demo/usage/13-editor-selection.png)

Fix a word by clicking into the text and typing; edited words keep approximate timings.
**Enter** splits a turn at the cursor and **Backspace** at the start of a turn joins it to
the one above. **Ctrl+Z** and **Ctrl+Shift+Z** undo and redo.

A turn's speaker menu (or **Alt+↑/↓**) changes who said it, including to a new speaker.

![A turn's speaker menu](demo/usage/14-editor-speaker-menu.png)

### Speakers

Name each speaker in the panel and every turn and output file follows. **Play sample**
plays that speaker's longest turn, which helps to tell who is who. The bar shows each
speaker's share of the talking.

![The Speakers panel with the speakers named](demo/usage/15-editor-speakers-named.png)

If one person was split into two speakers, **Merge into…** moves all of one speaker's
turns to another.

![Merge into… choosing the speaker to merge into](demo/usage/16-editor-merge-into.png)

### Find and replace

**Ctrl+F** finds and **Ctrl+H** finds and replaces, one match at a time or all at once.

![Find and replace with two matches](demo/usage/17-editor-find-replace.png)

### The right-click menu

Right-click in the text to play from that point, split the turn there, or move the text
after (or before) the cursor into the next (or previous) turn, for when a turn change
landed a few words early or late.

![The right-click menu in the text](demo/usage/18-editor-context-menu.png)

### Transcribing a passage again

With words selected, the right-click menu offers **Transcribe again**: WaveMaterial runs
the model on just that audio and shows the new text beside the current one. **Use the new
text** replaces it; **Cancel** keeps what you have. It is available while no recording is
being transcribed.

![The proposal from transcribing a passage again](demo/usage/19-editor-transcribe-passage.png)

### History

The **History** tab keeps named versions you save, an automatic version each time you
open the recording, and the original transcript. **Restore** goes back to any of them (and
can itself be undone). Click a version's name to rename it.

![The History tab with a named version, an automatic one, and the original](demo/usage/20-editor-history.png)

### Details

The **Details** tab shows the original file, the length, language, number of speakers
found, the device used, the models, and how long each stage took.

![The Details tab](demo/usage/21-editor-details.png)

### Exporting, renaming, and more

**Export** saves the transcript as plain text, SRT or WebVTT subtitles, JSON with word
timings, or (with the optional `export` extra) a .docx document or PDF, wherever you
choose. The documents start with the title, the speakers, and the length, and set the
transcript justified.

![The Export menu](demo/usage/22-editor-export-menu.png)

Click the title (or its pencil) to rename the recording.

![Renaming the recording](demo/usage/23-editor-rename.png)

The **⋯** menu transcribes the whole recording again as a new entry, or opens the folder
with its output files.

![The editor's ⋯ menu](demo/usage/24-editor-more-menu.png)

## Settings

Where transcription runs (automatic picks the graphics card when it can), processor
threads, the defaults for new recordings, the speech models with their folder and a
**Verify all** check, **Remove downloaded models** (to get the space back; WaveMaterial asks
for them again next time), and the once-a-day update check (on unless you turn it off; it only
asks GitHub whether a newer release exists).

When a newer version exists, Settings says so and a small notice appears in the sidebar.
The Windows installer and the Linux `.tar.gz` can then update themselves (from 1.1.0 on);
each button's **?** says what it does:

- **Self-update** downloads the new version, checks it, waits for any transcription to
  finish, then installs it and reopens WaveMaterial. On Linux the old folder is kept beside
  the new one, with `.previous` added to its name.
- **Manual update** downloads and checks it, then on Windows closes WaveMaterial and opens
  the installer for you to go through, or on Linux saves it in your Downloads folder.

Your recordings, transcripts, and settings stay as they are. If you run from source, update
with git.

![Settings, top](demo/usage/25-settings.png)

![Settings, lower: models, updates, and About](demo/usage/26-settings-lower.png)

![Settings when an update is available: Self-update, Manual update, and what each does](demo/usage/28-settings-update.png)

## Licences and credits

**Licences and credits** (from Settings) shows WaveMaterial's licence, the credits each
speech model requires, and every component it is built from with its licence text. It
works offline.

![Licences and credits](demo/usage/27-credits.png)
