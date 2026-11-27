# Changelog

## 2.2.0 — Library playback and speech tools (source/development builds)

- Embedded Qt media player with scrubbing, volume, persistent visual In/Out markers and immutable-source clip export.
- Relink selected moved bundles with bounded discovery, duplicate detection, revision checks and file hashes.
- Local faster-whisper transcription with explicit model-download opt-in, CPU execution, versioned TXT/VTT/JSON sidecars and a persistent timestamp search index.
- Search across transcripts and open matching media at its timestamp; matching CLI commands and background cancellation.
- Add real decoder compatibility and media operation regressions; extend packaged smoke checks to player, clipping and local transcription.

## 2.1.0 — Daily workspace

- Separate Add, Queue, Library and Settings pages, search/filter, contextual controls, compact layout, themes, shortcuts and optional notifications.
- Edit idle jobs; priority, earliest-start scheduling, selected-only runs, soft removal/restore and undo.
- Project/tags, readable media names, default-player playback, background checksum checks, JSON/CSV credits, backup/restore and scoped partial cleanup.
- MP3/M4A/FLAC/WAV/Opus, bitrate selection, 1440p, accurate ranges and bandwidth controls; matching CLI options.
- Fix thumbnail reply lifetime, recovery ownership race, SQLite sidecar modes, nested signed-link export leakage, fault-isolated discovery, QuickTime identification, retry policy editing and UI-blocking diagnostics.
- Package dependency lock, refreshed capability/workflow audit and regression tests.


## 2.0.0 — November 26, 2026 (source and CI packages)

- Replace the gallery-only loop with native single/playlist/channel inspection and bounded generic discovery.
- Add preview/selection, SQLite queue/history, retry/recovery, profiles, URL imports and library manifests.
- Validate media streams, retain valid small clips, stage partial downloads and publish verified bundles atomically.
- Track exact final output paths, enforce resolution ceilings and correct WebM merge selection.
- Add process-supervised cancellation, coordinated window close, real progress and explicit outcome states.
- Add audio-only output, subtitles, metadata, thumbnails, time ranges and editing-compatible conversion.
- Repair relative/nested metadata extraction, pagination cycles, button handling, scope filtering and JavaScript escapes.
- Add session-only cookie configuration, redacted plain-text logs, disk budgets, bounded retries and diagnostics.
- Switch to PySide6 Essentials and collect third-party notices for desktop packages.
- Add local regression/integration fixtures, platform CI, packaging workflows and updated documentation.
- Fix native desktop shutdown ordering on Linux/Windows and test the real executable through GUI startup, browser inspection and native downloads.
- Redact entire authorization/cookie values, including multi-word Bearer credentials and multiple cookies.
- Find standard Homebrew/user tools when launched from macOS Finder; package acceptance uses a Finder-style PATH.
- Pin current GitHub Actions by commit and bound CI job time.

Release status and validation limits are recorded in docs/RELEASE-AUDIT.md. CI artifacts are separate from publishing a signed installer or a GitHub Release.
