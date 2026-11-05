# Independent verification of release 0.2.0

## Scope

Reviewed candidate 8073f25947bff6798a0e9ee1058de64721447753, from a fresh
checkout and environment. The original candidate passed 232 tests. A separate
40-case suite returned 23 passes and 17 failing cases. Further controls added two
more metric-conjunction cases and seven positive/negative HTTP controls. All 49
review cases pass after correction. Separate test design is not external certification.

The original 27 implementation findings were independently reproduced against
base d2af56cd4df55a6aa2f4d7a0ae09ee3abe193233, then rerun successfully after repair.
Original failure logs, external probes and candidate artifacts remain preserved.

## Findings and corrections

| Area | Independent reproduction | Correction |
| --- | --- | --- |
| HTTP completion | An owned loopback server closed before its declared Content-Length, yet matching partial bytes returned VERIFIED. Invalid/conflicting lengths were also accepted. | Validate framing, require the declared bounded body to arrive and retain existing failure/uncertainty semantics. Valid equal lengths, connection-close bodies, 204/304 and complete chunked messages have positive controls. |
| Metric conjunction | Missing/invalid/future timestamps hid a known numeric threshold failure; missing metric values hid known stale evidence. | Evaluate the comparison and freshness independently. A known failure takes precedence, while the unknown component stays in error metadata. |
| Report consistency | A rehashed report containing PASS and an unresolved error was accepted. | Reject that contradiction in schema-1 report validation. An unkeyed checksum still cannot authenticate a source. |
| File-read consistency | A simulated short regular-file read disagreed with stable descriptor size and was accepted. | Require captured byte count to match the final observed file size, in addition to identity/mtime/ctime checks. |

The HTTP reproductions use owned loopback servers. The shortened-file case is a
controlled I/O fault injection, not evidence that ordinary regular-file reads
routinely truncate. No real endpoint, deployment, spacecraft or sensor was tested.

## Independent controls

The review additionally checks exact numeric tolerances using a separately written
integer-ratio oracle, positive/negative report checksum cases, legacy report support,
metadata type errors, permission errors versus absence and symlink aliases sharing
a source snapshot. HTTP tests check real HTTP/1.1 chunk termination and avoid copying
sensitive framing-header values into reports. Eight further publication controls
check registry identity, file sets, bytes, download hosts and propagation retries.

The repaired suite contains 289 tests. Release is gated on passing the entire suite,
platform CI and isolated wheel installation at the final commit. Publication results
are recorded in the pull request and release workflow rather than assumed here.

## Compatibility and limits

Public API names, signatures, commands, opt-in defaults and verdict names remain.
Use actual booleans for permission flags. Prepare trusted specifications with valid
used assertions and explicit freshness bounds. File observations are shared per
resolved source within one attempt; this does not establish atomicity across sources,
causal attribution, sensor truth or persistence after an observation.

A report checksum plus structural validation checks self-consistency. Anyone who
can rewrite the report can also recompute an internally consistent checksum.
HTTP framing checks do not authenticate a server or eliminate stale cached state.
The existing documented HTTP text replacement-decoding behavior remains unchanged.
Command opt-in is not a sandbox; Windows concurrent-path replacement and detached
child limitations, spool polling overshoot and non-preemptive retry budgets remain.

No paid model calls, real credentials, private repositories or external probe
services were used. Dependency installation and normal repository/publication
traffic are separate from synthetic verifier tests.

## Primary references

- HTTP/1.1 message framing and incompleteness, RFC 9112 sections 6.3 and 8: https://www.rfc-editor.org/rfc/rfc9112.html
- Python HTTP response API: https://docs.python.org/3/library/http.client.html

Source and package reproduction instructions are in verification.md. Historical
implementation notes remain under audit-2026-11-05.md; their candidate counts
refer to that earlier stage rather than the final release.
