# Troubleshooting

- **Missing FFmpeg/ffprobe:** install FFmpeg and restart the shell/app so PATH is refreshed. Run `videobot doctor`.
- **Chromium executable missing:** `python -m playwright install chromium` in the environment running VideoBot. The published Mac package bundles headless Chromium.
- **YouTube extraction warning:** check Deno/Node and EJS in Diagnostics, update yt-dlp in a controlled environment, and test again. Cookies and source restrictions may still affect availability.
- **Strict resolution unavailable:** choose another ceiling or Best. The app refuses to silently exceed your limit.
- **WebM/MP4 conversion failed:** the selected streams may not support that container. Choose native; use editing-compatible output for H.264/AAC conversion when wanted.
- **Stopped/failed queue item:** select it and Retry selected. Transfer errors remain visible in history. Raw HTTP restarts; supported yt-dlp partials can resume.
- **Partial files:** `.videobot-staging` is intentionally separate from completed bundles. Preserve it if you want retry/resume. Remove staging manually only while all runners are stopped and after checking the affected job IDs.
- **Protected media:** select an authorized cookie file or browser for this session. Credentials are not saved in profiles. Do not upload cookies or the private queue database in a bug report.
- **Missing collection items:** examine discovery warnings and increase the bounded page/item budget if appropriate. Generic navigation remains same-origin; supported playlist/channel extractors are preferred.
- **Already queued:** duplicate prevention includes source identity, destination and output policy. Retry a failed record instead of changing unrelated discovery settings to bypass deduplication.

Include OS, Python/app/dependency versions, a sanitized error and whether the problem reproduces with a public or local fixture when filing an issue.

## Preview, moved files and local speech

- If a completed item is missing after a drive move, select it in Library and use **Relink moved media**. Choose a single bundle if multiple copies match. The activity log explains failed identity/settings/hash checks.
- Embedded playback depends on the Qt multimedia backend and the source codec. An unsupported codec displays an error; use an editing-compatible MP4 copy or an external player for unusual formats.
- First-time transcription needs the model-download checkbox and internet access to Hugging Face. After caching, leave the checkbox off for offline operation. A missing cache fails without uploading audio or falling back to a cloud service.
- Tiny/base/small run on CPU, with different speed/accuracy and memory costs. Stop cancels the supervised worker, including model loading. Keep previous transcript sidecars until you have reviewed the replacement.
- Source installs constrain PyAV below 19 for faster-whisper 1.2.x compatibility. Use the project dependency metadata/locks rather than separately upgrading PyAV.

## Apple silicon 2.3 additions

- **Missing active transcript after moving a drive:** Relink now refuses an incomplete older copy. Copy the whole current bundle, including transcript folders, then retry.
- **Clip exists on disk but is absent from Library:** Settings → Recovery / import bundles → Import verified bundles. The original clip error includes its retained path.
- **Restore a backup:** Recovery restores into a new database/window. It does not replace the open queue.
- **Metal transcription unavailable:** Install `whisper-cpp` through Homebrew, restart the app and choose a local GGML `.bin` model in Preview. The CPU engine remains available. The Metal checkbox does not download a model.
- **Background queue unavailable:** Install VideoBot in Applications before enabling it. The user must remain logged in, the Mac awake and storage mounted. Configure current-session authentication in the interactive app for protected sources.
- **Source missed by a watch:** A watch inspects at most 100 recent items per check. Use explicit discovery for backfill.

See the [current guide](MAC-2.3.md) and [release notes](releases/2.3.0.md).

Queue and Library display 100 items per page. Use the row checkboxes for multiple selection, or click a title to select one item. The count includes selections on other pages. Filtering intentionally clears selections that no longer match. If an accessibility crash recurs, include the exact filter/action sequence and the macOS crash report, with private data removed.
