# VideoBot 2.0 implementation and acceptance plan

Goal: fix every finding F01–F24 in the November 26 audit, expand the app into a reliable desktop media queue, audit the resulting implementation, then push a reviewed pull request and merge after checks.

## Deliverables

- [x] Safe atomic, probed downloads; preserve existing files (F01–F03, F10).
- [x] Process-managed cancellation and graceful close (F04).
- [x] Native single/playlist/channel discovery and bounded browser fallback (F05–F06, F11–F17).
- [x] Explicit outcomes and real progress (F07, F18).
- [x] Strict format/quality selection plus audio, subtitles, metadata and segments (F08–F09).
- [x] Durable SQLite queue, retries, recovery and duplicate prevention (F19).
- [x] Plain/redacted bounded logs (F20).
- [x] Dependency diagnostics, modern baseline, reproducible install/update policy (F21).
- [x] GUI preview/select, saved settings/profiles, research manifests, CLI.
- [ ] Packaging/build instructions and CI across macOS/Windows/Linux (F22–F23).
- [x] Bounded retries, disk/size limits, five-second cooldown (F24).
- [ ] Full documentation, changelog, screenshots and platform validation matrix.
- [ ] Second audit, regression/integration tests, build smoke checks, PR checks and merge verification.

Evidence will be recorded in RELEASE-AUDIT.md. Checkboxes require current test/runtime evidence; implementation alone is not completion. Do not claim real service authentication or OS support tested without corresponding evidence.
