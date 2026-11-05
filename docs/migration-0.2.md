# Migration to 0.2.0

The CLI, Python API, verdict enum and report schema version 1 remain compatible.
Reports add an optional specification_sha256 fingerprint. Consistent legacy reports
without that field remain readable. Report checks now reject contradictory metadata,
counts, statuses and verdicts even when the checksum was recomputed.

Invalid/incomplete HTTP framing cannot verify an outcome. A metric check now reports
any known threshold or freshness failure even when its other component is unknown.
Callers should inspect the error and evidence fields alongside the verdict.

Permission options require True or False. Invalid/unused comparison arguments and
non-JSON-compatible inputs are rejected before observation. Explicit read/capture
limits are capped at 64 MiB. File checks read bounded stable regular-file snapshots;
hash assertions now honor those limits. Multiple checks sharing a source reuse its
captured bytes within an attempt. A retry collects a new observation.

The CLI refuses report destinations that alias its specification or local evidence,
and replaces reports atomically. Report digests provide consistency, not authenticity.
Keep original evidence records. A new release does not change the past observations
contained in a previously produced report.
