# VideoBot capabilities and workflows — 2.3

Maintained target: macOS on Apple silicon. See [release validation and limits](releases/2.3.0.md).

| Workflow | Steps | Result |
|---|---|---|
| Collect public source media | Inspect URLs → select candidates → choose output policy → queue → run | Verified media bundles, source manifests, checksums and durable history |
| Research an interview | Library preview → local CPU or optional Metal transcription → search → correct transcript | Timestamped reviewed quotations with retained revisions |
| Prepare multiple editing clips | Mark In/Out → Save named excerpt → repeat → Export saved excerpts | Separate H.264/AAC clips with parent/source/range provenance |
| Move a library drive | Move complete bundles → Relink moved media | Verified paths and active transcripts reconnect without altering originals |
| Recover an interrupted clip | Read retained output path → Recovery → Import verified bundles | Existing valid clip registered once without another encode |
| Hand off a project collection | Select completed items → Export collection → copy to destination → Recovery import | Real media, provenance, active transcript revisions and named excerpts |
| Run a scheduled public queue | Install in Applications → enable background queue → set earliest starts | launchd checks every minute while logged in and awake |
| Monitor a public source | Enable background queue → configure watched URL and interval | Up to 100 recent items checked per interval, deduplicated into queue |
| Restore queue metadata | Recovery → restore backup into a new database/window | Separate restored workspace for inspection; current database preserved |

## Boundaries

Authentication is session-only. Background runs do not reuse private cookies. FFmpeg/ffprobe and Deno or Node are external tools; optional whisper.cpp and GGML models are separate installs. Tiny/base/small CPU models download only with explicit opt-in. Audio remains local.

Search offers substring and indexed word/phrase modes, not semantic search. Speaker labeling is deferred. VideoBot creates clips but is not a full nonlinear editor or social publisher. Strict video ceilings, format compatibility, source restrictions and source-codec support still apply.

Queue and Library use paged checkbox controls with explicit selected counts. Filtering restores selection by job ID, while the queue engine independently enforces priority/schedule. Repeated native accessibility checks passed the formerly crashing sequence; full screen-reader qualification is separate. See [the current guide](MAC-2.3.md), [library examples](LIBRARY-TOOLS.md), [troubleshooting](TROUBLESHOOTING.md) and [audit resolution](AUDIT-RESOLUTION-2.3.md).
