# Changelog

Every user-visible change is recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- The app window: first-run model download (resumable, with pause), the library with
  filters and search, adding recordings (files, folders, or drag and drop) with speaker
  range and key terms, job details with stages and log, settings, and licences and credits.
- Transcription runs in the background, one recording at a time, resumes after a crash or
  a stop, and moves to the processor if the graphics card fails.
- Command line: `wavematerial models` (download or verify the models) and
  `wavematerial transcribe FILE`.
