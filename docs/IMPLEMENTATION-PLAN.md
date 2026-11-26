# VideoBot 2.0 implementation and acceptance plan

Goal: fix every finding F01–F24 in the November 26 audit, expand the app into a reliable desktop media queue, audit the resulting implementation, then push a reviewed pull request and merge after checks.

## Deliverables

- [ ] Safe atomic, probed downloads; preserve existing files (F01–F03, F10).
- [ ] Process-managed cancellation and graceful close (F04).
- [ ] Native single/playlist/channel discovery and bounded browser fallback (F05–F06, F11–F17).
- [ ] Explicit outcomes and real progress (F07, F18).
- [ ] Strict format/quality selection plus audio, subtitles, metadata and segments (F08–F09).
- [ ] Durable SQLite queue, retries, recovery and duplicate prevention (F19).
- [ ] Plain/redacted bounded logs (F20).
- [ ] Dependency diagnostics, modern baseline, reproducible install/update policy (F21).
- [ ] GUI preview/select, saved settings/profiles, research manifests, CLI.
- [ ] Packaging/build instructions and CI across macOS/Windows/Linux (F22–F23).
- [ ] Bounded retries, disk/size limits, five-second cooldown (F24).
- [ ] Full documentation, changelog, screenshots and platform validation matrix.
- [ ] Second audit, regression/integration tests, build smoke checks, PR checks and merge verification.

Evidence will be recorded in RELEASE-AUDIT.md. Checkboxes require current test/runtime evidence; implementation alone is not completion. Do not claim real service authentication or OS support tested without corresponding evidence.
