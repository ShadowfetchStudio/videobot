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
