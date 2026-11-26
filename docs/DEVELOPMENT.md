# Development and packaging

```sh
python -m pip install -e '.[dev]'
python -m playwright install chromium
ruff check videobot tests
ruff format --check videobot tests run.py
QT_QPA_PLATFORM=offscreen python -m pytest -q
python -m build
```

On Windows set `QT_QPA_PLATFORM=offscreen` through your shell instead of the inline POSIX environment assignment. Tests generate local video with FFmpeg and use local HTTP fixtures; install ffmpeg/ffprobe before running them. Browser fixtures require Playwright Chromium. No private accounts are needed.

## Dependencies

`pyproject.toml` declares supported ranges. `requirements-lock.txt` records a universal resolved production environment with hashes. Install it with `python -m pip install --require-hashes -r requirements-lock.txt`, then `python -m pip install --no-deps -e .`. CI also tests the supported dependency ranges to detect upstream drift. Update yt-dlp intentionally and rerun fixtures: source sites change independently of VideoBot. Do not suppress dependency audit failures without documenting a specific reviewed exception.

## Desktop packages

```sh
# Optional: bundle the browser instead of downloading it after installation.
PLAYWRIGHT_BROWSERS_PATH=0 python -m playwright install --only-shell chromium
python scripts/build.py
```

The PyInstaller build bundles Python, Qt/PySide6 Essentials, yt-dlp, EJS and Playwright. It collects installed production dependency license/notice files under `THIRD-PARTY-NOTICES`, with a version and upstream-link index. Qt libraries remain separate shared libraries in the directory-style bundle. Bundled headless Chromium requires the install command above. FFmpeg/ffprobe and a JS runtime remain explicit system dependencies. The Diagnostics action shows what is available. Distribution must include applicable third-party license notices; the repository's MIT license does not replace dependency licenses.

The Desktop packages workflow builds a Windows per-user Inno Setup installer, a macOS disk image and a Linux portable archive, each with SHA-256 checksums. These packages are unsigned/unnotarized unless a later release configures signing. Workflow artifacts are build outputs; they are not automatically advertised as a published release. Verify the release audit before publishing.

`VideoBot.app` in the repository is the historical source launcher. New generated bundles live only under `dist/`; do not replace the tracked launcher with a large generated build.

## Qt binding and licensing

The 2.0 release uses PySide6 Essentials (Qt for Python), with LGPL-available Qt modules, in place of the original GPL/commercial PyQt binding. The project source retains its existing MIT license; dependency licenses remain applicable. See the [Qt for Python license documentation](https://doc.qt.io/qtforpython-6/licenses.html) and [PyQt licensing](https://www.riverbankcomputing.com/software/pyqt/intro). Do not remove bundled notices or prevent users from replacing compatible shared Qt libraries. The build does not bundle a system FFmpeg build.
