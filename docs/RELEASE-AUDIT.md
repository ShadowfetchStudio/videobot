# VideoBot 2.0 release audit

## Local second audit — November 26, 2026

All F01–F24 findings have implementation changes and the evidence mapped below. **37 local tests passed**, including native and direct downloads, valid small clips, HLS, WebM, editing conversion, audio/time ranges, protected local media, retry timing, disk limits, crash recovery, and supervised cancellation. Ruff and formatting checks pass. Wheel/sdist and the macOS application build succeed. A packaged browser inspection and native download passed; the package cycle also exercises actual GUI startup and clean shutdown.

The audit found and fixed additional issues: repeated window-close handling; WAV extension selection during audio clipping; PID reuse during recovery; Unicode file I/O on Windows; process children surviving root termination; GUI thread cleanup; partial authentication/session propagation; Chromium bundle signing/layout; native Qt shutdown ordering; and full authorization/cookie-header redaction. yt-dlp extraction/postprocessing now runs in a separately supervised process so cancellation and resource checks apply through FFmpeg operations, including the CLI.

The project retains its MIT source license. The desktop binding now uses PySide6 Essentials, and packages collect production third-party notices. No developer signing or notarization identity is configured.

## Verification record and merge policy

- **37 local regression/integration tests passed**, with lint and formatting checks.
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
| F23 no tests/CI | pytest fixture suite + multi-platform workflow | 37 local tests; final CI checks linked above |
| F24 resources/retries | byte/free-space guards, bounded retry and cooldown | byte/reserve limits, Retry-After and response cleanup tests; supervised FFmpeg guard |
