# Changelog

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
- Pin current GitHub Actions by commit and bound CI job time.

Release status and validation limits are recorded in docs/RELEASE-AUDIT.md. CI artifacts are separate from publishing a signed installer or a GitHub Release.
