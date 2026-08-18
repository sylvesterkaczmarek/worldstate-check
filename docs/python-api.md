# Python API

WorldState Check remains CLI-first, but the deterministic verifier can also be embedded directly in Python.

## Verify a specification file

```python
from worldstate_check import Verdict, verify_spec

report = verify_spec("worldstate.yaml")
if report.verdict is Verdict.VERIFIED:
    print("verified")
```

Relative evidence paths are resolved from the specification directory unless `root=` is provided.

## Verify an in-memory specification

Use `verify_spec_data()` when another application already has the verification specification as Python data and should not write a temporary YAML file:

```python
from worldstate_check import Verdict, verify_spec_data

specification = {
    "version": 1,
    "task": "confirm-deployment",
    "checks": [
        {
            "id": "health",
            "type": "json",
            "path": "state.json",
            "field": "status",
            "operator": "eq",
            "value": "healthy",
        }
    ],
}

report = verify_spec_data(specification, root="./evidence")
print(report.verdict.value)
```

`root` defines the verification boundary and the base directory for relative evidence paths.

## Handle all verdicts explicitly

```python
from worldstate_check import Verdict, verify_spec

report = verify_spec("worldstate.yaml")

if report.verdict is Verdict.VERIFIED:
    proceed()
elif report.verdict is Verdict.NOT_VERIFIED:
    reject()
else:
    request_more_evidence()
```

`UNCERTAIN` is intentionally distinct from failure when reliable evidence is unavailable.

## Opt in to powerful checks deliberately

Command execution, network access, and paths outside the verification root remain disabled by default in both public APIs. Enable only the capability required by a trusted specification:

```python
report = verify_spec(
    "deployment.yaml",
    allow_network=True,
    wait_seconds=30,
)
```

The Python API uses the same deterministic engine and safety boundaries as the CLI. `verify_spec()` and `verify_spec_data()` both return `VerificationReport`.