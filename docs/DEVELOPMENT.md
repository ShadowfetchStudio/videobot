# Development and packaging — 2.3 Apple silicon

```sh
python -m pip install --require-hashes -r requirements-dev-lock.txt
python -m pip install --no-deps --no-build-isolation -e .
python -m playwright install chromium
ruff check videobot tests
ruff format --check videobot tests run.py
QT_QPA_PLATFORM=offscreen python -m pytest -q
python -m build
```

Use Python 3.12 on an Apple silicon Mac. Tests generate local video with FFmpeg and use local HTTP fixtures; install ffmpeg/ffprobe before running them. Browser fixtures require Playwright Chromium. No private accounts are needed.

## Dependencies

`pyproject.toml` declares supported ranges. `requirements-lock.txt` records a universal resolved production environment with hashes. Install it with `python -m pip install --require-hashes -r requirements-lock.txt`, then `python -m pip install --no-deps -e .`. `requirements-dev-lock.txt` locks the build/test tools too. Package CI installs it with `--require-hashes`, then installs the project with `--no-deps --no-build-isolation`. This pins Python dependencies; OS tools and runners can still change, so it is not a claim of byte-for-byte reproducible binaries. Source CI runs the same locked dependencies as package CI. GitHub Actions are pinned to reviewed commit hashes; update the version comments and hashes together, then rerun source and packaged acceptance. Update yt-dlp intentionally and rerun fixtures: source sites change independently of VideoBot. Do not suppress dependency audit failures without documenting a specific reviewed exception.

## Desktop packages

```sh
# Optional: bundle the browser instead of downloading it after installation.
PLAYWRIGHT_BROWSERS_PATH=0 python -m playwright install --only-shell chromium
python scripts/build.py
```

The PyInstaller build bundles Python, Qt/PySide6 Essentials, yt-dlp, EJS and Playwright. It collects installed production dependency license/notice files under `THIRD-PARTY-NOTICES`, with a version and upstream-link index. Qt libraries remain separate shared libraries in the directory-style bundle. Bundled headless Chromium requires the install command above. FFmpeg/ffprobe and a JS runtime remain explicit system dependencies. The Diagnostics action shows what is available. Distribution must include applicable third-party license notices; the repository's MIT license does not replace dependency licenses.

The Desktop packages workflow builds only an Apple silicon macOS disk image with SHA-256 checksums. The app is ad-hoc signed and is not Apple notarized. Workflow artifacts are build outputs; they are not automatically advertised as a published release. Verify the release audit before publishing.

`VideoBot.app` in the repository is the historical source launcher. New generated bundles live only under `dist/`; do not replace the tracked launcher with a large generated build.

## Qt binding and licensing

The maintained release uses PySide6 Essentials and Addons (Qt for Python), with LGPL-available Qt modules, in place of the original GPL/commercial PyQt binding. The project source retains its existing MIT license; dependency licenses remain applicable. See the [Qt for Python license documentation](https://doc.qt.io/qtforpython-6/licenses.html) and [PyQt licensing](https://www.riverbankcomputing.com/software/pyqt/intro). Do not remove bundled notices or prevent users from replacing compatible shared Qt libraries. The build does not bundle a system FFmpeg build.

## Library feature tests

`tests/test_media_tools.py` covers real clip encoding, rendered player frames, persisted markers, relink ambiguity/corruption/revision rejection, cancellation, transcript replacement/search/backup, and actual PyAV audio decoding without a model download. `scripts/package_smoke.py` additionally loads the tiny model and transcribes macOS-generated spoken audio inside the frozen executable and checks expected words, exercising the bundled native speech stack and VAD. This package check requires network access for model weights. This short recognition check is not a general accuracy benchmark.

`multiprocessing.freeze_support()` must run before Qt imports in `run.py`: model-download libraries can create a multiprocessing resource tracker which otherwise reopens the desktop app in frozen builds. Production and dev locks must both be regenerated after dependency changes.

Keep native speech libraries in worker processes rather than importing PyAV beside Qt's multimedia backend in UI tests. Decoder compatibility is exercised in a subprocess, matching production isolation. The optional Metal test requires `whisper-cli` and `VIDEOBOT_METAL_MODEL` pointing to a local GGML model; without those weights CI skips that one test.

## Release procedure

Commit a clean source tree, run locked tests and dependency audit, then build. `build/build-info.json` records the commit, architecture, runtime versions and dirty state inside the app. Run `python scripts/package_smoke.py`, verify the ad-hoc signature and arm64 executable, build the DMG, compute SHA-256, then publish a matching version tag and accurate release notes. Source CI, packaged workflow artifacts and public GitHub releases are distinct states. Native walkthroughs still matter: see [known accessibility limits](MAC-2.3.md).
