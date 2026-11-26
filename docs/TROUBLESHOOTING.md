# Troubleshooting

- **Missing FFmpeg/ffprobe:** install FFmpeg and restart the shell/app so PATH is refreshed. Run `videobot doctor`.
- **Chromium executable missing:** `python -m playwright install chromium` in the environment running VideoBot. Linux may also need `python -m playwright install --with-deps chromium`.
- **YouTube extraction warning:** check Deno/Node and EJS in Diagnostics, update yt-dlp in a controlled environment, and test again. Cookies and source restrictions may still affect availability.
- **Strict resolution unavailable:** choose another ceiling or Best. The app refuses to silently exceed your limit.
- **WebM/MP4 conversion failed:** the selected streams may not support that container. Choose native; use editing-compatible output for H.264/AAC conversion when wanted.
- **Stopped/failed queue item:** select it and Retry selected. Transfer errors remain visible in history. Raw HTTP restarts; supported yt-dlp partials can resume.
- **Partial files:** `.videobot-staging` is intentionally separate from completed bundles. Preserve it if you want retry/resume. Remove staging manually only while all runners are stopped and after checking the affected job IDs.
- **Protected media:** select an authorized cookie file or browser for this session. Credentials are not saved in profiles. Do not upload cookies or the private queue database in a bug report.
- **Missing collection items:** examine discovery warnings and increase the bounded page/item budget if appropriate. Generic navigation remains same-origin; supported playlist/channel extractors are preferred.
- **Already queued:** duplicate prevention includes source identity, destination and output policy. Retry a failed record instead of changing unrelated discovery settings to bypass deduplication.

Include OS, Python/app/dependency versions, a sanitized error and whether the problem reproduces with a public or local fixture when filing an issue.
