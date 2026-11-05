# WorldState Check 0.2.0

This release improves deterministic postcondition verification and its evidence
records. It preserves the public Python API, CLI commands, safety opt-ins and
VERIFIED / NOT_VERIFIED / UNCERTAIN verdicts.

## Improvements

Local file, JSON and metric checks share bounded observations within each attempt,
with specification and source fingerprints. Invalid permission flags and malformed
specifications are rejected before evaluation. Output destinations cannot overwrite
input evidence. Commands use bounded capture and owned-process cleanup.

Independent review repaired HTTP response-completion checks, metric-failure precedence,
contradictory saved PASS results and simulated short-file-read handling. It added 49
review cases and eight publication-verifier controls. The full suite has 289 tests.
The offline demonstration has eight cases spanning deployment, spacecraft and
maintenance outcomes. The original examples remain unchanged.

## Installation

```sh
python -m pip install worldstate-check==0.2.0
worldstate-check --version
worldstate-check demo --scenario verified
```

The release workflow repeats exact-commit CI before building, tests a non-editable
installation, publishes the same artifacts to PyPI, compares public downloads with
the reviewed files and repeats tests on Python 3.10 and 3.14. The GitHub release
includes those artifacts, source, checksums and the independent review record.

## Scope

These are synthetic verifier tests, not evidence of a real deployment or sensor's
trustworthiness. Source truth, cross-source atomicity, causal attribution and future
state persistence remain outside the verifier's claims. An unkeyed report checksum
is not authentication. See the included review, migration and security documentation.
