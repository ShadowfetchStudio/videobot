# Security and privacy

Do not post secrets in public issues. Report a reproducible security problem through GitHub's private vulnerability reporting when available, or ask the maintainer for a private reporting channel without including exploit credentials.

VideoBot loads user-chosen web pages and media through third-party parsers. Keep the app, browser and FFmpeg current. Authentication is opt-in for the current session. Browser cookie access may require OS permission. Stored queue URLs may include sensitive signed query parameters; keep the application-data directory private. Logs and exported source URLs redact query strings.

No telemetry is implemented. VideoBot does not bypass DRM or grant rights to downloaded content. The dependency audit is one check, not a guarantee of absence of vulnerabilities. Bundled third-party components retain their own licenses.
