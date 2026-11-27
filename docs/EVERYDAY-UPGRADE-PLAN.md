# Everyday VideoBot upgrade — acceptance plan

The goal is a reliable application that is comfortable for daily use, including a real UI audit and improvements. The prior re-audit is the starting evidence, not a completion claim.

## Required work and proof

- [x] Repair R01–R08: thumbnail ownership, recovery compare-and-set, SQLite sidecar privacy, recursive export sanitization, fault-isolated discovery/partial results, container identification, editable retry policies, asynchronous diagnostics. Proof: regressions plus current suite.
- [x] Everyday queue: search/status filters, selected-only run, priority/reordering, scheduled start, explicit edit/retry-with-settings, undo/restore record removal, accurate totals and progress. Proof: transactional tests and real UI tasks.
- [x] Library: readable output names, project/tags, media playback/open, source-credit CSV/JSON, checksum verification, safe staging inventory/cleanup, backup and settings/profile management. Proof: fixture outputs, safe file-ownership tests and UI tasks.
- [x] Output upgrades: more audio formats/quality controls, 1440p, accurate range mode, bandwidth control, clearer storage estimates and limits. Proof: real FFmpeg/yt-dlp fixtures and boundary tests.
- [x] Daily UX: useful empty states, progressive advanced settings, keyboard shortcuts, URL paste/drop, accessible labels, compact layouts, light/dark/system theme, desktop completion notification preference. Proof: before/after screenshots, keyboard/mouse workflows and responsive checks.
- Setup and maintenance (implemented; release verification tracked below): background dependency checks, configurable tool directories, first-run guidance, sanitized support report, release/version check, reproducible package build and stable versioned release assets. Proof: clean-profile workflow, packaged tests, checksums and GitHub release verification.
- [x] Consistent headless workflow: CLI authentication during inspect/add, output-option parity and queue/library management commands. Proof: CLI integration tests and documented examples.
- Final release gates (see live checks): failure-path tests, privacy/ownership/concurrency review, source and package CI on supported OS families, docs and capability matrix refreshed, reviewed push/merge and main verification.

## Baseline UI observations

The actual 2.0 macOS package was inspected with desktop tools. At 1240x860 the destination and rights fields are narrow, all advanced output settings compete for the sidebar, advanced limits/authentication require scrolling, and empty discovery/queue tables lack an actionable next step. Queue controls do not reflect selection or distinguish saved media from active work. There is no search, explicit job editor or onboarding. Screenshot/AX inspection is evidence of the current layout, not proof of later improvements.

## Verification boundaries

Use generated media and test-only application data. Preserve existing user media and credentials. Real authenticated third-party services are separate from controlled fixtures. Signing/notarization depends on configured identities; never claim an unsigned build is signed. A feature only counts as complete when exposed, documented and verified through its actual user workflow.

## Acceptance details

- Priority-based ordering is implemented; drag reordering is not. Playback opens the OS player; embedded playback/visual trimming is explicitly future work in the capability audit.
- Restore uses a new database via CLI; the GUI has consistent backup and safe partial-file inventory/confirmation.
- Release discovery opens the official release page; there is no silent updater. Python build dependencies are hash locked; OS runner/tool drift prevents claiming byte-identical builds.
- 56 local tests passed including the final fixed-position Apply/Cancel adjustment and rejection of still images masquerading as video. Packaged macOS UI was manually exercised for inspect, queue and edit; source/package CI gates the final revision.

Final revision checks and merge status: [PR #2](https://github.com/ShadowfetchStudio/videobot/pull/2/checks). Published, verified package assets: [v2.1.0 release](https://github.com/ShadowfetchStudio/videobot/releases/tag/v2.1.0). These links are the live status authority, not an assertion that a pending workflow succeeded.
