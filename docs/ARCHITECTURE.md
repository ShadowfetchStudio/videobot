# Architecture

`models.py` defines serializable options and candidates. `discovery.py` selects native extractor enumeration or bounded same-origin Playwright discovery. `storage.py` owns transactional queue state. `downloader.py` owns staged transfers, validation, transformation and publication. `engine.py` coordinates durable jobs. `cli.py` exposes headless operation and a JSON event protocol. `worker.py` supervises a separate process tree for the desktop. `app.py` renders those events and manages selection/profiles/history.

## States

`queued → running → completed | failed | cancelled`. Retry transitions failed/cancelled back to queued. A process owner token prevents another runner from finishing its jobs. SQLite transactions prevent concurrent claim of the same record. Restart recovery checks both PID and process creation time, so reused process IDs do not leave stale jobs running forever. Access-denied process checks are treated conservatively.

## File ownership

Only job-owned staging is modified or cleaned. Finished bundles appear by rename on the same filesystem after ffprobe validation. Exact postprocessor paths replace filename globs. An already-existing bundle is reused only when its job ID and all manifest hashes verify. Existing unrecognized files/folders cause a visible failure and are preserved.

## Authentication and privacy

Authentication configuration is passed to the worker through a private temporary request file, removed immediately after reading. Cookie choices are excluded from persisted option profiles. Source URLs can contain credentials in query strings; these are retained privately for retry and redacted from logs/manifests. Do not share your queue database. No background telemetry is implemented.

## Extension points

Add source-specific discovery through yt-dlp before adding broad DOM heuristics. Add new output policies through Options and downloader validation, with CLI/GUI serialization tests. Keep GUI state out of the engine so it can run on a headless machine. Remote network control of the queue is not implemented in this release.

## Local library tools

`media_tools.py` owns verified relinking, new derived clip bundles and transcription publication. `player.py` owns QMediaPlayer preview, saved range markers and timestamp navigation. CLI and GUI call the same background operations through TaskWorker. Transcription uses local faster-whisper CPU int8, or the optional external whisper.cpp CLI with Metal and a user-selected GGML model. CPU model downloads require an explicit flag. SQLite `transcripts` and `transcript_segments` tables are additive migrations. Search offers a parameterized Unicode-casefolded literal substring or a quoted SQLite FTS5 phrase, limits results, and excludes soft-removed records. FTS insert/delete triggers track active transcript segments. Backups include the index; model caches and media require separate backup.

Relinking compares-and-updates the observed completed path after checking identity, options and hashes. Transcripts publish uniquely named sidecar folders before atomically replacing the index, preserving earlier versions. Clips publish a new UUID bundle and completed record with parent/hash/range provenance. Media originals are never overwritten.

## Recovery, tables and background execution

`recovery.py` verifies imports, active transcript identity and source hashes, restores excerpt notes, and rolls back newly registered rows if an import fails. Collection export copies real files, rejects symlinks, reverifies copied media and writes its completion marker last. Cancellation leaves a partial folder without that marker.

`table.py` uses stable model row identities and hides filtered rows instead of repeatedly removing native accessibility objects. Visible order is first-seen for the lifetime of a view. This avoids the reproduced native crash sequence, but the macOS accessibility hierarchy can still omit the view after filtering; full accessibility qualification is unresolved.

`background.py` creates an opt-in per-user launch agent for an installed app. The agent polls bounded watched sources and uses the same transactional queue engine. It stores no cookies, does not wake the computer, and is not enabled automatically.
