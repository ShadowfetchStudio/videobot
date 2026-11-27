# VideoBot 2.1 release audit

## Everyday workspace — November 26, 2026

Local acceptance: **56 tests pass** on macOS, including real audio conversions in five formats, precise video clips, checksum tampering, mixed-source discovery, queued-policy editing, scheduling/priority, backup recovery, safe cleanup and responsive desktop diagnostics. Ruff passes. The macOS package passes actual GUI startup/shutdown, bundled browser inspection and a native download. Python wheel/sdist and dependency audit are checked separately in the release workflow.

An additional validation regression rejects still images/attached cover art masquerading as video. The final UI adjustment pins Apply/Cancel beside the job editor and preserves cancelled edits.

All eight reproduced 2.0 re-audit defects have regressions:

| Finding | Repair and evidence |
|---|---|
| R01 stale thumbnail reply | Clear ownership before abort; ignore obsolete callback; thumbnail selection/deferred-delete regression |
| R02 recovery race | Compare owner, PID and process creation time in the update; interleaved reclaim regression |
| R03 readable SQLite sidecars | Precreate database mode 0600 before WAL creation, repair existing sidecar modes; umask regression on POSIX. Windows uses application-data ACLs. |
| R04 signed thumbnail/format leakage | Recursive public-data redaction for CLI/library/support exports; nested fake-token regression |
| R05 one broken source aborts batch | Per-input and per-page isolation, explicit partial status, preserve successful additions; real HTTP 404 gallery and CLI regression |
| R06 MOV saved as MP4 | Recognize QuickTime major brand before the shared MP4 demuxer list; real QTRLE/MOV metadata regression |
| R07 retry ignores revised budgets | Explicit idle-job editing, output-policy revision staging and immutable active jobs; edit/retry regression |
| R08 diagnostics blocks UI | Supervised background diagnostic process with cancellation; event-loop responsiveness test |

The GUI was reviewed at 1240×860 and 900×680. Add, Queue, Library and Settings now separate the primary workflows; destination width, empty guidance, action states, log visibility and recovery controls are improved. Full supported capabilities, limits and seven examples are in [Capabilities and workflows](CAPABILITIES-AND-WORKFLOWS.md).

### Release gates

The final PR revision must pass [source/dependency checks](https://github.com/ShadowfetchStudio/videobot/actions/workflows/ci.yml) and [packaged execution on all three OS families](https://github.com/ShadowfetchStudio/videobot/actions/workflows/build.yml) before merge. Published packages are listed on [GitHub Releases](https://github.com/ShadowfetchStudio/videobot/releases), with their own checksum files. A prior local pass is not evidence that a later revision passed CI.

No authenticated third-party account was exercised. The runtime cannot guarantee every remote site, rights clearance or editorial correctness. External FFmpeg/ffprobe and JS runtime dependencies remain. Packages remain unsigned/unnotarized. Playback opens the default player; scheduling requires the app to remain open, and the release button opens the official release page rather than installing an update.

---

# Historical VideoBot 2.0 release audit

## Local second audit — November 26, 2026

All F01–F24 findings have implementation changes and the evidence mapped below. **38 local tests passed**, including native and direct downloads, valid small clips, HLS, WebM, editing conversion, audio/time ranges, protected local media, retry timing, disk limits, crash recovery, and supervised cancellation. Ruff and formatting checks pass. Wheel/sdist and the macOS application build succeed. A packaged browser inspection and native download passed; the package cycle also exercises actual GUI startup and clean shutdown.

The audit found and fixed additional issues: repeated window-close handling; WAV extension selection during audio clipping; PID reuse during recovery; Unicode file I/O on Windows; process children surviving root termination; GUI thread cleanup; partial authentication/session propagation; Chromium bundle signing/layout; native Qt shutdown ordering; full authorization/cookie-header redaction; and discovery of installed media tools when launched from Finder. yt-dlp extraction/postprocessing now runs in a separately supervised process so cancellation and resource checks apply through FFmpeg operations, including the CLI.

The project retains its MIT source license. The desktop binding now uses PySide6 Essentials, and packages collect production third-party notices. No developer signing or notarization identity is configured.

## Verification record and merge policy

- **38 local regression/integration tests passed**, with lint and formatting checks.
- The [initial cross-platform source run](https://github.com/ShadowfetchStudio/videobot/actions/runs/45877500307) passed on Windows, macOS, Linux/Python 3.12 and Linux/Python 3.11, including the dependency audit.
- The [shutdown-fix package run](https://github.com/ShadowfetchStudio/videobot/actions/runs/45878332544) exercises the real packaged executable on all three systems: GUI open/close and screenshot, bundled headless Chromium inspection, and a native download through the nested transfer worker. The first package attempt exposed a native shutdown crash; widgets are now explicitly destroyed while QApplication is alive.
- Final credential-redaction and workflow updates have their own regression coverage and must pass **all source, dependency and package checks on the final PR revision before merge**. Live results and merge state are recorded in [PR #1](https://github.com/ShadowfetchStudio/videobot/pull/1/checks), not inferred from an older passing run.
- [Main-branch CI](https://github.com/ShadowfetchStudio/videobot/actions/workflows/ci.yml?query=branch%3Amain) verifies the merged source. Build artifacts are available from the package workflow; no signed installer or separate GitHub Release is implied.

| Environment | Acceptance coverage |
|---|---|
| macOS 26, Apple silicon, Python 3.12 | source tests, GUI lifecycle, packaged discovery/download, disk image |
| Windows x64, Python 3.12 | source tests, GUI lifecycle, packaged discovery/download, per-user installer |
| Ubuntu 26.04 x64, Python 3.12 | source tests, GUI lifecycle, packaged discovery/download, portable archive |
| Ubuntu 26.04 x64, Python 3.11 | source compatibility tests |

The stubborn-child SIGTERM fixture is intentionally Unix-only; Windows still runs the live-transfer cancellation fixture. CI jobs have a 15-minute bound and report the active test if they stall. GitHub Actions use pinned, reviewed current versions.

## Scope and honest limits

Tests use generated media, local HTTP servers, isolated browser contexts and controlled failures. Real authenticated third-party accounts were not tested and cannot be inferred from local cookie fixtures. Upstream site behavior, available formats and account restrictions can change independently. Time-range stream copying follows keyframes. FFmpeg/ffprobe and a supported JS runtime remain explicit system dependencies; headless Chromium is included in desktop packages. Packages are unsigned/unnotarized unless a later release configures signing.

## Reproducing acceptance

```
python -m pip install -e '.[dev]'
python -m playwright install chromium
ruff check videobot tests
ruff format --check videobot tests run.py
python -m pytest -q
python -m build
PLAYWRIGHT_BROWSERS_PATH=0 python -m playwright install --only-shell chromium
python scripts/build.py
python scripts/package_smoke.py
```

Install FFmpeg/ffprobe first. On Windows, use the shell's environment-variable syntax for `PLAYWRIGHT_BROWSERS_PATH`. CI covers Python 3.12 on all three OS families plus Python 3.11 on Linux. `scripts/package_smoke.py` tests the generated executable, rather than merely importing the source.

## Original finding traceability (local acceptance)

| Finding | Implementation | Current evidence |
|---|---|---|
| F01 small/pre-existing file deletion | ffprobe + owned staging; refuse unrecognized output folder | core small-file and existing-output tests |
| F02 partial final files | staged `.part`, final-folder rename | disconnect test |
| F03 invalid media accepted | require requested stream via ffprobe | non-video rejection test |
| F04 stop/close | retained stop flag, managed child group, coordinated close | early-stop/close, blocked transfer, stubborn-child process tests |
| F05 pagination cycles | normalized visited-page set and bounded budget | real browser cycle test |
| F06 single URL | native/media routing and current-page media inspection | single/gallery same-media test |
| F07 false success | terminal job states and structured result | queue failure test |
| F08 ceiling bypass | no unrestricted fallback; validate direct height | actual yt-dlp selector test |
| F09 wrong WebM container | explicit WebM merge policy | options capture and actual VP9/WebM output test |
| F10 unrelated filename | exact final post-hook path; no glob | real yt-dlp transfer test |
| F11 limits/button pagination | explicit budgets/warnings, adaptive scroll and button handling | 205-item DOM and button tests |
| F12 missing metadata | URL resolution and bounded recursive JSON-LD | relative/nested source test |
| F13 embeds/manifests | native/manifest classification | actual HLS transfer and embedded-platform routing fixtures |
| F14 session loss | job-local browser cookies with scoped Requests jar/referrer | real protected local HTTP test |
| F15 thumbnail veto | remove broad substring veto | lexicon media test |
| F16 escaped regex | raw JS string, executed browser test | login exclusion test |
| F17 offsite links/fragments | origin filtering + normalized URLs | DOM scope test; button redirect fix reviewed |
| F18 progress | byte/downloader hooks and structured events | native/direct transfer progress assertions |
| F19 history/duplicates | transactional queue + output identity + retry | concurrent claim/dedup/recovery tests |
| F20 HTML/unbounded logs | QPlainTextEdit + 1,200 block cap + redaction | desktop/log tests |
| F21 setup drift | Python baseline, EJS/runtime detection, doctor, lock | local doctor + dependency audit |
| F22 packaging | PyInstaller + platform package workflow | packaged GUI/browser/native transfer smoke on all three OS families; final checks linked above |
| F23 no tests/CI | pytest fixture suite + multi-platform workflow | 38 local tests; final CI checks linked above |
| F24 resources/retries | byte/free-space guards, bounded retry and cooldown | byte/reserve limits, Retry-After and response cleanup tests; supervised FFmpeg guard |
