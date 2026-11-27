# VideoBot 2.3 — Apple silicon workspace

VideoBot now maintains **macOS on Apple silicon only**. Windows/Linux releases remain historical downloads; they are not updated or tested for 2.3. Intel Macs are not a supported target. The application is ad-hoc signed, not Developer ID signed or Apple notarized.

## Reliable queue and discovery

Queue/Library use paged native checkbox controls with selection restored by job ID, independently per view. Each page renders at most 100 rows; selection remains available across pages. Filtering drops selections excluded by the filter. Generic extractor IDs are scoped to URLs; existing generic records are re-keyed without deleting history. Audio-only requests ignore video resolution ceilings. Raw FLAC, AAC, Opus and AIFF URLs are recognized as media. Scheduling changes only the fields you explicitly edit/check, preserving existing values. Typed tools paths are validated and saved.

## Recovery and portable collections

Settings → Recovery offers verified bundle import and backup restoration to a new database/window. Import validates original manifest hashes and never overwrites existing records. Use Relink for existing records whose paths changed. A clip retained after a database error includes a recovery instruction and its path. Reimporting an already registered bundle is harmless.

Library → Export collection copies selected completed bundles into a new folder, preserving source manifests and transcript revisions. A `collection.json` completion marker is written only after the copy completes. Partial copies from cancellation are retained and lack that completion marker. Import from the collection folder on the other installation. This copies actual media; ensure sufficient destination space. Symlinked files are rejected.

Transcripts written by 2.3 include an `active-transcript.json` pointer so portable imports can select the correct revision. Older collections without a pointer still import their media; their transcript files are retained but must be transcribed/reviewed again to create an active searchable revision. Existing databases keep their old active indexes.

Relink now rejects an incomplete/older copy that lacks or mismatches the active transcript. Copy the complete current bundle, including transcript folders, then retry.

## Research and clips

Preview → Correct transcript edits text while preserving timestamps. Saving creates a new TXT/VTT/JSON revision, retains previous files, updates search, and records `machine_generated: false` for the reviewed revision. Review remains a human responsibility.

Save named excerpt stores an In/Out range and label in the queue database. Export saved excerpts produces separate verified clip bundles sequentially. Completed clips remain if a later export fails or is stopped. The activity log maps excerpt names to output folders. Saved excerpt selections travel in portable collections; they are also retained by queue database backups.

Search all transcripts keeps the existing case-insensitive substring mode and adds **indexed whole-word/phrase search**. The two modes intentionally have different matching semantics. FTS data is maintained by SQLite triggers as active transcripts change.

## Background queue

For the installed application in Applications, Settings → Background queue can enable an opt-in per-user launch agent. It checks due jobs every minute while the user is logged in, even when the window is closed. It resumes after login/restart through launchd. Disable removes this application's launch agent only. The computer must be awake, the output drive mounted and the tools available. Session cookies are not persisted: account-dependent work belongs in the interactive app.

No background service is installed merely by opening the app. Watched sources can be configured with 15-minute to one-week intervals; each check inspects at most 100 items and deduplicates previously queued media. This is a recent-items monitor, not a guarantee of complete historical backfill.

## Apple Metal transcription

Optional Apple Metal transcription uses the official whisper.cpp CLI (`brew install whisper-cpp`) and a local GGML `.bin` model selected in Preview. Models are not downloaded automatically by this backend. The bundled CPU tiny/base/small engine remains available. Automatic speaker diarization is not included; speaker labeling is deferred to a later release.

## Desktop polish and maintenance

The workspace scrolls when necessary; status, progress and the activity-log toggle live in a fixed footer. Startup size respects the available display and saved window size. Find targets the active Library or Queue. The audio-only mode disables irrelevant video options. The earlier virtual Qt table/outline presentation was replaced after the native crash reproduced during final acceptance. Ordinary checkbox/label controls now expose each selectable job directly. Repeated native filter/select/clear checks retained the correct selection and accessibility hierarchy without crashing. Full screen-reader qualification remains separate from this focused regression check.

## Verification policy

Release CI runs on Apple silicon macOS with hash-locked dependencies, lint/format checks, tests and dependency auditing. Package smoke tests exercise the built application, browser inspection, downloads, playback, clips and a spoken transcription fixture. Passing tests is not a guarantee for arbitrary websites or authenticated accounts.

The tagged release includes an embedded source commit/runtime record, DMG SHA-256, test counts, native UI observations and remaining limitations. Historical audits describe their historical versions only.


## Scale observations

A synthetic local SQLite benchmark of 1,000 / 10,000 / 50,000 items loaded rows in 0.005 / 0.063 / 0.360 seconds and returned up to 200 indexed phrase matches in 0.001 / 0.009 / 0.039 seconds. These are database measurements on one development Mac, not end-to-end UI latency guarantees. Paged controls bound widget creation to 100 rows per view; execution and refreshed display order honor queue priority and earliest-start values.
