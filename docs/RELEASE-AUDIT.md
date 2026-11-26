# VideoBot 2.0 release audit

## Local second audit — November 26, 2026

All F01–F24 findings have implementation changes and the evidence mapped below. **34 local tests passed**, including native and direct downloads, valid small clips, HLS, WebM, editing conversion, audio/time ranges, protected local media, retry timing, disk limits, crash recovery, and supervised cancellation. Ruff and formatting checks pass. Wheel/sdist and the macOS application build succeed. A packaged browser inspection and native download passed; the final package cycle also exercises actual GUI startup.

The audit found and fixed additional issues: repeated window-close handling; WAV extension selection during audio clipping; PID reuse during recovery; Unicode file I/O on Windows; process children surviving root termination; GUI thread cleanup; partial authentication/session propagation; and Chromium bundle signing/layout. yt-dlp extraction/postprocessing now runs in a separately supervised process so cancellation and resource checks apply through FFmpeg operations, including the CLI.

The project retains its MIT source license. The desktop binding now uses PySide6 Essentials, and packages collect production third-party notices. No developer signing or notarization identity is configured.

## Release gates

- Local source regression suite, lint, second audit: passed.
- Local macOS wheel/application build and packaged acceptance: recorded in this release's evidence.
- Windows/Linux/macOS GitHub CI and desktop packages: must pass on the final PR revision before merge.
- PR merge and main-branch verification: pending until remote gates pass.

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
| F22 packaging | PyInstaller + platform package workflow | macOS packaged browser/native transfer smoke; platform CI gate below |
| F23 no tests/CI | pytest fixture suite + multi-platform workflow | 34 local tests; platform CI gate below |
| F24 resources/retries | byte/free-space guards, bounded retry and cooldown | byte/reserve limits, Retry-After and response cleanup tests; supervised FFmpeg guard |
