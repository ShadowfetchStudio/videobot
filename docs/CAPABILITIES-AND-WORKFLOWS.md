# VideoBot 2.1 — capability audit and daily workflows

Audit date: November 26, 2026. This describes the implementation, not a promise that every third-party website works. The evidence is the source, generated-media integration tests, desktop tests and the release checks linked in `RELEASE-AUDIT.md`.

## What the application is good at

VideoBot is a local media acquisition and preservation workspace. Its strongest workflow is **inspect sources, choose a subset, download with an explicit policy, and retain a traceable library**. The GUI and CLI use the same database and download engine. It is useful for a research library, editing preparation, audio listening, approved archival collection and repeatable batch downloads.

It is not an editor, documentary generator, social publishing service, universal crawler or DRM bypass. It does not decide whether a source is factually correct or licensed for your intended use.

## Full capability matrix

| Area | Available in 2.1 | Practical boundary |
|---|---|---|
| Source input | Paste/drop HTTP(S) links; import UTF-8 URL files; multiple source inspection | Local media import and conversion-only jobs are not implemented. URL files are limited to 1 MiB. |
| Site support | yt-dlp extraction for supported sites; playlists/channels; HLS/DASH; direct media; browser discovery on generic galleries | Site/account restrictions and extractor changes still apply. No guarantee for arbitrary dynamic sites. |
| Discovery | Titles, duration, creator, thumbnail and formats when available; checkbox selection; page/item budgets | Flat playlist entries often lack full metadata. No fabricated size or quality estimate is shown. |
| Fault isolation | A bad URL/page reports an error while remaining sources continue; successful CLI add results remain queued | Partial inspection exits nonzero in the public CLI. Redacted failed URLs may need signed queries re-entered before retry. |
| Queue durability | SQLite WAL, atomic claims, owner/PID/start-time recovery, explicit terminal states | One sequential runner per run. Multiple processes cannot claim the same job. No distributed coordinator. |
| Queue navigation | Search titles, sources, projects, tags and errors; status filter; separate Library | Search is local. There is no full-text transcript search. |
| Queue control | Run all eligible jobs or selected IDs; retry; edit idle jobs; priority; earliest start; soft removal/restore and undo | Priority changes ordering; there is no drag reorder. GUI scheduling runs only while the app is open with Auto-run enabled. CLI `run` processes currently eligible jobs and exits. |
| Editing queued policies | Change limits/destination/formats before retry; retain ID and attempt history | Running/completed jobs cannot be rewritten. Format-affecting changes use a new partial revision and output folder. Older files are retained. |
| Quality and containers | Best/worst or hard 2160/1440/1080/720/480/360p ceiling; native/MP4/WebM | No suitable format means failure, not an oversized fallback. Direct files above a ceiling are rejected, not downscaled. MP4/WebM remux requires compatible codecs. |
| Editing preparation | H.264/AAC, yuv420p, fast-start MP4 | CPU encoding, CRF 18. No GPU selection, color grading, HDR tone mapping or timeline editing. |
| Audio | MP3, M4A/AAC, FLAC, WAV and Opus; 64–320 kbps choices for lossy formats | Lossless output cannot restore fidelity missing in a lossy source. Bitrate is irrelevant to FLAC/WAV. |
| Clips | Start/end seconds; fast stream-copy ranges; accurate range option using re-encoding | Accurate mode fetches the full selected source before trimming. It is frame/sample constrained, not an arbitrary sub-frame editor. Stream-copy ranges can align to keyframes. |
| Subtitles and extras | Language selection, automatic-caption opt-in, thumbnail sidecars, metadata where available | Direct media lacks a subtitle/thumbnail catalog. Automatic captions may be inaccurate. No transcription or translation service is included. |
| Transfer control | Retry budget, rate limit, size and free-space limits, speed/ETA when known, interruptible worker | Bandwidth is approximate per transfer, not a global machine cap. Native partials resume when supported; direct HTTP restarts safely. |
| Library organization | Readable media filenames inside stable per-job folders; project and tag fields; searchable completed library | Project/tags organize records, not arbitrary user folders. Moving a folder outside VideoBot requires manual path repair; automatic relinking is not implemented. |
| Playback | Open a verified manifest-listed media path in the OS default player; open output folder | No embedded streaming preview, waveform or visual in/out editor. Player/codec support comes from the installed player. |
| Provenance | Creator, title, source, retrieval time, options, rights notes, chapters when supplied, file bytes and SHA-256 in each bundle | Signed URL queries are redacted in public exports. Unknown rights stay unknown. Chapters originate upstream and may not be retimed for clips. |
| Verification and export | Background checksum/size verification; combined JSON or spreadsheet-safe source-credit CSV | Checksums detect changed/missing files relative to the manifest; they are not an independent certificate of authenticity. |
| Maintenance | Consistent database backup including profiles; restore to a new database; selected idle-job partial inventory/cleanup | Database backups contain private retry URLs and exclude media. Completed media is never removed by record/partial cleanup. Restoration is CLI/manual, not an overwrite button. |
| Authentication | Explicit cookie file or browser selection during GUI/CLI inspect/add/run | Session-only, not saved in queue/profiles/manifests. OS permission and a valid authorized account may be needed. |
| Setup and comfort | Background diagnostics, tools-folder picker, saved/load/delete profiles, dark/light/system styles, keyboard shortcuts, optional completion notifications, bounded collapsible log | Notifications depend on OS support/settings. Release button opens GitHub; it is not a silent updater. FFmpeg/ffprobe and JS runtime remain external. |
| Packaging | Python/Qt/headless Chromium bundled; locked package dependencies; Windows/macOS/Linux CI | Unsigned/unnotarized. Official package architectures and tested baselines are listed in README. No Intel Mac or Linux ARM package claim. |

## Workflow 1: documentary research collection

1. In **Settings**, choose a destination on your media disk, `native` container and `best` quality. Enter a project such as `Apollo research` and tags such as `NASA, archive, reference`.
2. Add rights notes from the actual source. Save a profile such as `Research archive`.
3. In **Add sources**, paste a playlist, gallery or several video URLs. Click **Inspect URLs**. Review failures in the activity log and choose only relevant items.
4. Click **Queue selected videos**, then **Run queue**. Use a bandwidth limit if the machine is doing other work.
5. In **Library**, search the project, open a saved bundle, and **Verify files**. Export JSON for complete manifests or CSV for a source-credit worksheet.

Result: one job folder per item, readable media filename, requested sidecars and provenance. Technical verification does not approve rights or factual use in a film.

## Workflow 2: bring footage into an editor

Choose the `Editing H.264` profile, set the destination and project, then inspect/queue/run. This transcodes to H.264/AAC MP4 with yuv420p. Keep native source archives separately if preservation matters. The conversion uses CPU and can be slower than the transfer. It does not add missing detail, correct color or remove source artifacts.

## Workflow 3: a precisely bounded reference clip

Enable **Download a time range**, enter start/end in seconds, and select **Accurate range**. Use native or MP4 for video. A 12.5–22.5 second selection requests ten seconds; output is limited by source frame/sample timing. Accurate mode downloads the full selected source and re-encodes the clip. For fast approximate cuts, leave it unchecked and accept keyframe alignment.

An exact clip is not a replacement for reviewing the final audiovisual result. If the start lies beyond the available media, the job fails validation instead of producing a successful empty bundle.

## Workflow 4: listening copies

Enable **Audio only**, choose MP3 at 192 kbps for broad compatibility, or M4A/Opus/FLAC/WAV as needed. Save a listening profile. Inspect a source you are authorized to download, queue and run. Double-click the completed Library item to launch your default player. FLAC/WAV are larger and do not improve a compressed source.

## Workflow 5: recover from a disk-budget failure

Filter Queue by **failed**, select one item and choose **Edit settings**. Increase the maximum job size/free-space policy appropriately or select another destination. Click **Apply changes to selected job**, then **Retry selected** and **Run selected**. Changing limits keeps compatible native partials; changing output policy starts separate staging. Use **Clean partials** only after reviewing the exact listed paths if those partials are no longer useful.

Closing/restarting the app does not lose the queue. Recovery marks work owned by a demonstrably dead process as cancelled. Select it and retry. Re-select authentication if needed; it was deliberately not persisted.

## Workflow 6: an evening batch

Queue the items, select urgent ones and set a higher priority. Set the earliest start in **Priority / schedule**, then enable **Auto-run due jobs**. Leave the app open and ensure the computer stays awake. **Stop / pause** also disables automatic running, so a stopped run will not immediately restart. VideoBot does not change system power settings.

For shell automation, invoke the CLI through your own scheduler. `run` exits after currently eligible work; it is not a background daemon.

## Workflow 7: headless use

Replace example URLs with authorized sources; placeholders below are syntax examples.

```sh
videobot inspect "https://example.com/collection" --cookie-browser firefox
videobot add "https://example.com/video" --destination "/media/research" --quality 1440 --project "Research" --tags "interview,reference"
videobot add "https://example.com/talk" --audio-only --audio-format opus --audio-bitrate 128
videobot add "https://example.com/video" --segment-start 12.5 --segment-end 22.5 --accurate-range --container mp4
videobot list
videobot organize JOB_ID --priority 20
videobot run --ids JOB_ID --cookie-browser firefox
videobot verify JOB_ID
videobot export "/media/source-credits.csv"
videobot backup "/backups/videobot-new.sqlite3"
```

To change an idle job, put the fields to change in a JSON file, for example `{"max_bytes": 21474836480}`, then run `videobot edit JOB_ID settings.json` and `videobot retry JOB_ID`. `clean-partials JOB_ID` inventories without deleting; add `--delete` for intentional cleanup. `remove` and `restore` operate on records only.

To recover a backup: close the desktop app, run `videobot restore-backup backup.sqlite3 restored.sqlite3`, inspect it with `videobot --db restored.sqlite3 list`, then keep a copy of the old application data and use the restored database in your chosen `VIDEOBOT_HOME`. Do not replace a live SQLite database or its sidecars.

## UI audit: changes and remaining opportunities

The 2.0 window had a narrow output-folder field, an always-visible long advanced sidebar, little empty-state guidance and no separation between pending work and completed media. Diagnostics launched a browser on the GUI thread. Removing records had no undo and failed jobs could not be corrected in place.

2.1 gives Add, Queue, Library and Settings their own pages; the destination is a full-width field; advanced controls no longer consume the main work surface; the activity log is collapsed by default. Search, totals, contextual action states, empty-state instructions and keyboard navigation make routine actions discoverable. Background dependency checks remain cancellable. The smaller-window layout was inspected at 900×680 in addition to 1240×860. Automated desktop tests cover editing, filtering, undo and responsive diagnostics. Actual packaged checks and platform status belong in the release audit.

Keyboard shortcuts: Ctrl+L focuses source input, Ctrl+Enter inspects, Ctrl+F focuses queue search, Escape stops an active run and disables auto-run. Standard platform copy/paste remains available. The minimum window is 840×620; table columns can be resized and output settings scroll.

The most valuable next additions would be an embedded player with visual clip markers, library relinking after moving a drive, subtitle transcription/search, carefully bounded per-host concurrency, signed installers and an update-check dialog. These are future work, not hidden features. Arbitrary third-party login/DRM flows, editing timelines and automatic social posting are outside this release.
