# VideoBot 2.0 release audit — in progress

This document records evidence, not intent. The repair branch has not yet been pushed or merged.

## Implemented, awaiting full acceptance

- Separate discovery/download/queue/process/GUI modules and modern package metadata.
- Persistent job states, selection/history/profiles, CLI and provenance bundles.
- Regressions for small-file preservation, partial/non-video rejection, strict quality, wrong-output prevention, cancellation, browser discovery and rich-text logging.
- Test/build/package workflows and installation/troubleshooting/security documentation.

## Current local evidence

Initial run: 18 passed, one test-fixture failure (missing yt-dlp metadata), one genuine Qt teardown error. Both were corrected. The expanded suite now passes **24 tests** (15.43 seconds), including actual native/direct transfer, audio-only range output, scoped browser cookie/referrer propagation, PID reuse recovery, and disk-budget rejection. Ruff and `git diff --check` pass. The latest dependency audit reported no known vulnerabilities.

Python wheel/sdist and the macOS PyInstaller application build succeeded. A packaged worker executed an empty queue successfully and emitted a completed JSON result. This is a packaging smoke test, not full packaged download/UI validation. A Windows windowed-output safeguard was added afterward and needs the next build/test cycle.

A rendered desktop screenshot was inspected and prompted fixes to clipped table headings and the options layout. Final screenshot review is still required.

## Gates still open

- Full F01–F24 mapping to current regression tests and manual/runtime evidence.
- Expanded tests for actual yt-dlp transfer, transformations/audio/ranges, cookie/referrer propagation, resource limits, worker shutdown and crash recovery.
- Remaining second-audit findings and stronger cancellation/process-tree tests.
- Rendered desktop inspection and final screenshots.
- Dependency lock/audit, wheel and desktop build smoke tests.
- Windows/Linux/macOS CI results and package artifacts.
- Fresh final code audit, fixes, PR validation, merge and final remote verification.

No real authenticated third-party account testing has occurred. Such coverage must never be implied by local fixtures.

## Original finding traceability (implementation review; final gates remain open)

| Finding | Implementation | Current evidence |
|---|---|---|
| F01 small/pre-existing file deletion | ffprobe + owned staging; refuse unrecognized output folder | core small-file and existing-output tests |
| F02 partial final files | staged `.part`, final-folder rename | disconnect test |
| F03 invalid media accepted | require requested stream via ffprobe | non-video rejection test |
| F04 stop/close | retained stop flag, managed child group, coordinated close | early-stop/close tests; stronger in-flight process test pending |
| F05 pagination cycles | normalized visited-page set and bounded budget | real browser cycle test |
| F06 single URL | native/media routing and current-page media inspection | single/gallery same-media test |
| F07 false success | terminal job states and structured result | queue failure test |
| F08 ceiling bypass | no unrestricted fallback; validate direct height | actual yt-dlp selector test |
| F09 wrong WebM container | explicit WebM merge policy | options capture; actual WebM remux test pending |
| F10 unrelated filename | exact final post-hook path; no glob | real yt-dlp transfer test |
| F11 limits/button pagination | explicit budgets/warnings, adaptive scroll and button handling | 205-item DOM and button tests |
| F12 missing metadata | URL resolution and bounded recursive JSON-LD | relative/nested source test |
| F13 embeds/manifests | native/manifest classification | code review; stream/iframe fixture test pending |
| F14 session loss | job-local browser cookies with scoped Requests jar/referrer | real protected local HTTP test |
| F15 thumbnail veto | remove broad substring veto | lexicon media test |
| F16 escaped regex | raw JS string, executed browser test | login exclusion test |
| F17 offsite links/fragments | origin filtering + normalized URLs | DOM scope test; button redirect fix reviewed |
| F18 progress | byte/downloader hooks and structured events | native/direct transfer progress assertions |
| F19 history/duplicates | transactional queue + output identity + retry | concurrent claim/dedup/recovery tests |
| F20 HTML/unbounded logs | QPlainTextEdit + 1,200 block cap + redaction | desktop/log tests |
| F21 setup drift | Python baseline, EJS/runtime detection, doctor, lock | local doctor + dependency audit |
| F22 packaging | PyInstaller + platform package workflow | macOS build/worker smoke; other OS gates pending |
| F23 no tests/CI | pytest fixture suite + multi-platform workflow | 24 tests locally; remote CI pending |
| F24 resources/retries | byte/free-space guards, bounded retry and cooldown | size budget test; retry timing/space guard tests pending |
