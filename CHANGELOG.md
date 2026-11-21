# Changelog

## 0.3.0

21 November 2026. Observation replay and paired outcomes pilot.

- Share HTTP response bytes per attempt and make redirects explicit.
- Align field-presence and missing-value semantics. Validate freshness declarations.
- Export bounded values, record acquisitions and replay all seven check types offline.
- Add sampled intervals, an optional Inspect scorer and the paired outcomes pilot.
- Exclude ambiguous repeated sample IDs, report the first attributable violation and replay older recordings under their original rules.
- Use the same value digests in terminal output and JSON when a failed comparison is too large to display inline.
- See the [migration and replay guide](docs/observation-replay.md) for changes affecting existing specifications.

## 0.2.0

5 November 2026. Verified observation and evidence integrity release.

- Reject incomplete or ambiguously framed HTTP responses before assertions can pass.
- Preserve known telemetry threshold and freshness failures when the other assertion is inconclusive.
- Reject saved PASS results with unresolved errors and regular-file reads shorter than their recorded size.
- Add 49 separate release-review cases and eight public-download verifier controls.
- Gate publication on full exact-commit CI, isolated package tests and verified public downloads.
- Preserve the original examples and document migration and remaining assurance boundaries.

## 0.2.0rc1

Unpublished reliability candidate prepared on 5 November 2026.

- Capture one bounded local-file observation per resolved path in an evaluation attempt, shared by file, JSON and metric checks. Retries use fresh observations.
- Bind each report to the normalized specification hash and include observed file hashes, sizes and acquisition times.
- Require actual boolean opt-ins, validate bounded JSON-compatible structures and reject unused assertion arguments.
- Preserve observed failures when other assertions are unreadable. Reject ragged CSV rows and inconclusive negative TCP evidence.
- Bound command capture during execution, close stdin and stop owned process groups on POSIX.
- Validate report schema, counts and verdict alongside its digest; protect input files and replace report outputs atomically.
- Add offline software, spacecraft and maintenance demonstrations, cross-platform tests and clean distribution verification.

Separate independent review is required before merging or publishing. The release
trigger remains 0.1.2; no new version has been uploaded.
