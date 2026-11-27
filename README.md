# VideoBot

**Discover media, choose what to save, and keep a reliable download library.**

VideoBot is a Python/PySide6 desktop app and headless CLI built around yt-dlp, Playwright and FFmpeg. Version 2.3 focuses on Apple silicon Macs: reliable queue selection, verified recovery/import, portable collections, reviewed transcripts, saved excerpts, indexed phrase search and optional background queue runs.

> **Maintained platform: macOS on Apple silicon only.** Windows/Linux packages in older releases are historical and are no longer maintained. See the [2.3 guide](docs/MAC-2.3.md) for capabilities, workflows and limitations.

![VideoBot desktop preview with example fixture](docs/images/desktop.png)

## Capabilities

- Inspect single video URLs, supported playlists/channels, direct media and generic HTML galleries.
- Preview titles, duration, formats when provided by the source, creator and thumbnails; select items before queuing.
- Persistent SQLite queue and history; duplicate prevention, retry failed/interrupted jobs and restart recovery.
- Real transfer progress, speed/ETA where known, plain-text bounded logs and explicit completed/failed/cancelled states.
- Strict resolution ceilings through 2160p (including 1440p), native/MP4/WebM, five audio formats, bitrate controls, subtitles, thumbnails and fast or accurate time ranges.
- Editing-compatible H.264/AAC preset (transcodes and therefore takes longer).
- Job-owned temporary storage, ffprobe validation, exact output paths and atomic completed-folder publication.
- Per-video folders with provenance, SHA-256 checksums, creator/title, retrieval time and rights notes.
- Opt-in browser/cookie-file authentication for the current session; no cookies in saved profiles or exported manifests.
- Bounded discovery, size/free-space budgets, retries and a minimum five-second cooldown after successful downloads.
- Search/filter, selected-only runs, priorities, scheduled starts with the window open or an opt-in macOS background queue, explicit job editing and record undo/restore.
- Project/tags, readable filenames, embedded playback, saved visual In/Out markers, new clip exports, checksum verification and JSON/CSV library exports.
- Relink moved library bundles by job identity, output settings and SHA-256 verification; ambiguous matches are left unchanged.
- Local CPU transcription (tiny/base/small Whisper), TXT/VTT/JSON sidecars, and cross-library transcript search with click-to-seek. First-use model downloads are opt-in; audio is not uploaded.
- Saved output profiles, backup/recovery, safe partial cleanup, background diagnostics, tools-folder selection, themes and optional notifications.
- Expanded CLI using the same engine. See the [current guide](docs/MAC-2.3.md) and [historical capability audit](docs/CAPABILITIES-AND-WORKFLOWS.md).

## Desktop build downloads

Published versions appear on [GitHub Releases](https://github.com/ShadowfetchStudio/videobot/releases). For development builds, open a successful [Desktop packages workflow](https://github.com/ShadowfetchStudio/videobot/actions/workflows/build.yml) and download the artifact for your system (GitHub sign-in required). Each artifact contains the package and `SHA256SUMS.txt`:

| System | Package | Installation |
|---|---|---|
| macOS Apple silicon | `VideoBot-2.3.0-macOS-arm64.dmg` | Copy VideoBot to Applications. |

Workflow artifacts are development builds; a published release is separately identified by its version tag and release notes. Packages bundle Python, Qt, the local speech engine and headless Chromium, but still require FFmpeg/ffprobe and a supported JavaScript runtime as described below. The Mac application is ad-hoc signed, not Developer ID signed or notarized; verify provenance and checksums before choosing whether to run them. Intel macOS, Windows and Linux are not maintained targets.

## Install from source

Use **Python 3.12 on an Apple silicon Mac** (the tested release environment).

```sh
git clone https://github.com/ShadowfetchStudio/videobot.git
cd videobot
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m playwright install chromium
```

Install **FFmpeg and ffprobe** and put them on PATH:

- macOS: `brew install ffmpeg`

On macOS, the app also searches the standard Homebrew, `~/.local/bin` and `~/.deno/bin` directories when launched from Finder, preserving any existing PATH choices.

Full YouTube support also needs a supported JavaScript runtime. Install [Deno](https://docs.deno.com/runtime/getting_started/installation/) or a current Node.js release. The Python installation includes `yt-dlp[default]` and its EJS dependency. VideoBot detects Deno first, then Node. See [yt-dlp's current requirements](https://github.com/yt-dlp/yt-dlp#dependencies).

```sh
videobot doctor
videobot-desktop
# Or: python run.py
```

For reproducible development, see [development and packaging](docs/DEVELOPMENT.md). The original `VideoBot.app` in the checkout remains a source launcher: it is **not** the new self-contained Python/Qt build. Keep that launcher beside `run.py`; its environment must still be installed.

## Desktop workflow

1. Paste one URL per line and click **Inspect URLs**. Discovery does not download the full videos.
2. Review the candidate list and select the items you want. Playlist entries may not have format/size metadata until extraction; unknown values are shown honestly.
3. Choose destination/output options and click **Queue selected videos**.
4. Open **Queue**, then **Run queue** or **Run selected**. Search, priority and scheduling are available here.
5. Use **Stop / pause** to end the current run. Select interrupted jobs and **Retry selected** to requeue them; already queued jobs remain queued.
6. Open **Library** to play media, open folders, verify checksums or export JSON/CSV source credits.

Use **Settings** for output choices, profiles, appearance, tool setup and backup. **Queue → Edit settings** applies a deliberate change to an idle job.

Authentication choices are session-only. Choose the needed browser or cookie file again when running authenticated queued jobs after a restart. Changing settings does not silently rewrite already queued jobs.

## Outputs and preservation

Each completed job is published as `VideoBot-<job-id>/` under the chosen destination. Format-affecting edits use a revision suffix such as `-r1`; old output folders are preserved. The folder contains title-named final media, requested sidecars and `manifest.json`. A hidden `.videobot-staging/` directory holds unfinished job files; interrupted work never appears as a completed final folder. Do not delete staging files while a job is running.

VideoBot checks real media streams instead of rejecting valid clips based on file size. It does not delete pre-existing user files. Removing queue records hides them until restored; it does not remove media. Selected idle partials can be inventoried and cleaned explicitly. Query parameters are redacted from exported source URLs to avoid leaking signed credentials; the private queue retains URLs needed for retry. Rights notes default to **unknown** and should be checked before reuse.

## Headless CLI

```sh
videobot inspect "https://example.com/videos"
videobot add "https://example.com/video.mp4" --destination "/path/to/library" --quality 1080 --container mp4
videobot list
videobot run
videobot retry JOB_ID
videobot run --cookie-browser firefox
```

Use `videobot --db /path/to/queue.sqlite3 ...` for an alternate queue. Set `VIDEOBOT_HOME` to relocate application data. CLI inspection emits JSON events suitable for automation. Source URLs and account access must be authorized by the user running the app.

## Important limits

- A strict height ceiling fails if no suitable format exists. It never silently downloads a larger video. MP4/WebM remux can fail for incompatible codecs; choose native or the editing-compatible preset as appropriate.
- Stop interrupts the supervised desktop worker; a short grace period allows cleanup before process-tree termination.
- yt-dlp downloads can resume when supported. Raw HTTP transfers restart safely instead of appending to a possibly changed resource.
- Generic web crawling stays on the listing origin for navigation and uses page/item/scroll budgets. A warning identifies truncated discovery. Dynamic sites may require a dedicated extractor or manual input.
- Subtitle/thumbnail availability depends on the source. Cookie access can require OS permission and does not bypass account restrictions or DRM.
- Fast stream-copy time ranges can align to keyframes. Accurate ranges download the full selected source and re-encode, within frame/sample timing. Editing conversion changes the encoding.
- Scheduling uses an open app with Auto-run enabled, or the optional background queue configured in Settings. No computer wake service is installed. Library playback uses the embedded preview; Open in player uses the OS default player.
- See [troubleshooting](docs/TROUBLESHOOTING.md), [architecture](docs/ARCHITECTURE.md), [changelog](CHANGELOG.md) and [security](SECURITY.md).

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md). Reproduction fixtures should be local/generated and must not contain account cookies or signed URLs. Changes to the downloader should include failure-path tests, not only a successful transfer.

[Support ShadowfetchStudio](https://www.buymeacoffee.com/shadowfetcu) · [Report a bug](https://github.com/ShadowfetchStudio/videobot/issues)

## Preview, clip, relink and search speech

Double-click a completed **Library** item to open **Preview / clip / transcribe**. Play or scrub, set **Mark In** and **Mark Out**, then **Export marked clip** to create a separate library bundle. Original downloads are preserved. Clips use H.264/AAC MP4 (audio-only items use AAC M4A).

If a drive or folder moved, select the affected completed items and choose **Relink moved media**. Pick their new parent folder, or a single bundle folder to disambiguate duplicate copies. This validates every listed file before changing its library path; it does not move or delete media.

For speech, choose a model in the preview and enable **Allow model download on first use** for the initial download from Hugging Face. Tiny is the fastest (~75 MB), base is balanced (~145 MB), small is slower (~485 MB). Models are cached beside the queue database under `speech-models`; subsequent runs work offline with the checkbox off. No API key or cloud transcription account is needed. Use **Search all transcripts** in Library to find a phrase and double-click to seek. Automatic transcripts need review; silence can produce an empty transcript. There is no speaker labeling or translation mode.

```sh
videobot clip JOB_ID 12.5 22.5 "/media/clips"
videobot relink "/new-drive/research" JOB_ID ANOTHER_JOB_ID
videobot transcribe JOB_ID --model tiny --allow-download
videobot search-transcripts "golden telescope"
```

Speech uses [faster-whisper](https://github.com/SYSTRAN/faster-whisper) locally by default. For Apple Metal acceleration, install `whisper-cpp` with Homebrew and select a local GGML `.bin` model in Preview. This optional engine and its model are not bundled. PyAV is constrained below version 19 because faster-whisper 1.2.1 uses an API removed in PyAV 19; a real audio-decoding regression test covers compatibility. See the [current workflows and limits](docs/MAC-2.3.md).
