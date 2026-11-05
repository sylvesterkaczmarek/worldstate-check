# Reproducible verification

## Source candidate

Use a fresh source checkout and Python 3.10 or later:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest -o addopts='' -q
python -m ruff check src scripts tests
python scripts/showcase.py --out /tmp/worldstate-showcase-new
```

The showcase requires an absent output directory. Eight cases cover a deployment
claim with a failed health observation, recovered deployment, spacecraft attitude
failure despite command acknowledgement, fresh maintenance, stale maintenance,
missing observation time, duplicate JSON evidence and an inconsistent saved report.
Every input and output is retained in that directory. All observations are synthetic
local files; this demonstration opens no endpoint and launches no verification
command. It does not certify a real deployment or physical system.

## Installed distributions

Build and run package verification with Python 3.12 or later:

```bash
python -m build
python -m twine check --strict dist/*
python scripts/verify_distribution.py dist/*.whl dist/*.tar.gz --report /tmp/worldstate-package-proof.json
```

The verifier checks wheel and source-distribution identity, compares all runtime
module bytes, creates a fresh non-editable installation outside the checkout,
compares installed files, and runs the complete suite, showcase and shipped examples.
Test dependencies are separate from the single PyYAML runtime dependency.

CI covers Linux Python 3.10 through 3.14 plus macOS and Windows. Platform-specific
skips must remain visible. Final package checks depend on those jobs. The release
workflow is prepared to repeat CI and check exact built packages before publication;
the implementation pass does not change its release trigger or publish a version.

## Independent review targets

Repeat the saved audit probes from a fresh checkout. Challenge source changes,
file identity, parser limits, output collisions, command cleanup, timestamp bounds,
required/optional aggregation and report metadata with separately authored tests.
Verify the specification fingerprint and observation hashes against retained bytes.
Check the published artifacts only in the separate release pass.

A successful report verifier checks internal structure and its unkeyed checksum.
It cannot establish authenticity, truthfulness of a source or a current world state.
See audit-2026-11-05.md for all compatibility changes and assurance limits.

## Release verification

The independent review and migration notes describe release-specific changes.
Public package verification compares registry metadata, exact filenames and hashes
with the tested build, downloads those files, installs them in a fresh environment,
and repeats the complete suite, showcase and shipped examples. Python 3.10 requires
tomli for the standalone build-verification script only; the installed runtime
still depends only on PyYAML. GitHub release downloads are checked separately.
