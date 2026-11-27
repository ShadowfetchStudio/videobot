# November 27 audit resolution — 2.3.0

This record maps the earlier source audit to the maintained Apple silicon release. It does not certify absence of unknown bugs.

| Finding | Resolution and evidence |
|---|---|
| D01 filtered selection | Paged native controls with job-ID selection; regression verifies only the intended job remains selected. Native filter/select/clear sequence exercised. |
| D02 Generic identity collisions | URL-scoped Generic identities, non-destructive migration and duplicate regression. |
| D03 native accessibility crash | The virtual outline candidate also crashed in final acceptance. Replaced it with paged native checkbox/label controls. Repeated filter/select/clear then passed with correct selection and a complete accessibility hierarchy. Full screen-reader qualification is separate. |
| D04 clipped activity-log toggle | Fixed footer, bounded startup geometry and independently scrolling Settings/transcript panes. |
| D05 audio-only height ceiling | Video ceiling applies only to video output; actual 480p-to-audio regression with a stored 360p ceiling. |
| D06 FLAC/AAC discovery | Shared extension list for direct URLs, page links and data attributes; local real-media regression. |
| D07 relink missing transcript | Active revision required to match; incomplete copy refused and original path retained. |
| D08 typed tools path | Validation and save on completed editing; restart persistence regression. |
| D09 priority overwrites schedule | Existing values shown and independent change toggles; untouched schedule regression. |
| D10 retained unregistered clip | Error includes retained path; verified recovery/import registers once without re-encoding. Failure-injection regression. |

## Workflow and upgrade disposition

- Setup readiness and dependency diagnostics are exposed from Add sources. Destination checks and space reserves also run in the download engine.
- Recovery imports complete verified bundles and restores backups into a separate database/window. Invalid imported transcripts do not leave newly registered partial records.
- Portable collections preserve provenance, reviewed transcripts and named excerpts; copied media is reverified before the completion marker is written.
- Transcript correction, saved excerpts, batch clips and indexed phrase search are available. Substring search retains its prior semantics.
- Optional launch-agent scheduling and bounded watched sources are available. No background agent is installed automatically. Session credentials are never stored for unattended reuse.
- Optional whisper.cpp / Metal transcription was exercised with a verified local model. Speaker labeling was explicitly deferred by the maintainer. Semantic search and a full editing suite remain future product work.
- Source/package checks use locked dependencies and only maintain Apple silicon macOS. Earlier Windows/Linux assets are historical.
- Packaged acceptance uses actual spoken audio, local downloads, browser inspection, embedded playback and clip export. Arbitrary authenticated websites and full assistive-technology compatibility remain outside the verified scope.

The final native-control design, focused regression evidence and remaining qualification boundaries are described in the current guide and release notes.
