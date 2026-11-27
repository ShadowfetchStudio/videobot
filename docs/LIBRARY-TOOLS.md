# Library tools in 2.2

## From an archive to an editing clip

1. Download and complete a library item normally.
2. Double-click it, or choose **Preview / clip / transcribe**.
3. Play/pause, scrub the timeline, and set In/Out at the current position. Fine-tune in seconds to three decimal places. The timeline displays both markers; values persist in the queue database.
4. Choose **Export marked clip** and a destination. A supervised worker verifies the original, re-encodes the range and creates a new completed library item. Stop cancels the background operation.
5. The new manifest records the parent job ID, source hash and relative start/end. Original files and manifests stay unchanged. Accuracy is limited to the source frame/sample timing.

Video clips are H.264/AAC MP4, audio-only clips are AAC M4A. The source job's size limit and free-space reserve apply. Output encodes have a 24-hour time budget. A forced process termination can leave a `.videobot-clip-*` staging directory; it is not a completed clip. Such leftovers may be manually removed only after confirming no task is using them. An interruption between final publication and database insertion can leave a valid bundle not yet listed in Library; the file is retained.

## Reconnect a moved drive

Select completed items in Library and choose **Relink moved media**. Point at a moved bundle or the new containing folder. Search is limited to 20,000 directories and eight levels, excludes hidden directories and does not follow directory symlinks. Narrow the chosen root if a limit is reached. Unrelated media is ignored.

VideoBot requires the matching manifest job ID and original output settings, then verifies all listed file sizes and SHA-256 hashes. Multiple copies of a job are reported as ambiguous; select the desired single bundle folder. Missing/corrupt/mismatched jobs retain their original paths. Results appear in the activity log. Successfully verified items can relink even when another selected item fails. No files move or get deleted. Only completed items are supported; pending download destinations must be edited separately.

## Transcribe and find a quotation

Open a library item, choose **tiny**, **base**, or **small**, and click **Transcribe locally**. First use requires **Allow model download on first use**. The engine obtains multilingual Whisper weights from the faster-whisper model repositories on Hugging Face. The cache is `speech-models` beside the database. Download requires space for the selected model plus a 512 MiB reserve; cached offline use does not download. No audio is uploaded and no API key is needed.

Transcription uses CPU int8 with at most four threads and voice activity detection. Model download/loading and inference run outside the GUI; Stop terminates an unresponsive worker after a short grace period. Longer files use more RAM and CPU time. There is no GPU switch, translation, diarization, word-level karaoke or manual transcript editor in this release.

A successful run publishes a new `transcript-<unique-id>` folder inside the bundle, containing TXT, WebVTT and JSON with segment timestamps, model name, language and source media hash. The original download manifest is unchanged. Reruns retain previous sidecars and atomically replace the active search index. Failed/cancelled runs leave the previous index intact; a forced termination can leave a hidden `.transcript-*` directory. Automatic text and timing require review; silence may produce zero segments.

Filter lines inside the preview and click one to seek. **Search all transcripts** finds a literal case-insensitive phrase across non-removed completed items; double-click a result to open the item at that timestamp. Results are limited to 200 matches in the GUI, so narrow broad searches. Removed items are hidden from results and reappear after Restore. Search is not fuzzy or semantic.

Moving the whole media bundle preserves sidecars; relinking updates playback paths while the database keeps the timestamp index. Back up both bundles and the queue database. Copying only a transcript sidecar to a fresh installation does not import it into search. The download **Verify files** action verifies original manifest files, not these newly generated transcript sidecars.

## Headless equivalents

```sh
videobot --db /path/to/queue.sqlite3 clip JOB_ID 12.5 22.5 /media/clips
videobot --db /path/to/queue.sqlite3 relink /new-drive/library JOB_ID OTHER_JOB_ID
videobot --db /path/to/queue.sqlite3 transcribe JOB_ID --model tiny --allow-download
videobot --db /path/to/queue.sqlite3 search-transcripts "search phrase"
```

For offline transcription omit `--allow-download` after the chosen model is cached. A missing cache fails visibly. Existing `backup`, `remove`, `restore`, `verify` and export commands continue to work. Transcript content is private application data; share backups and sidecars intentionally.
