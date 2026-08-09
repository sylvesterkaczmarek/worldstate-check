# WorldState Check

[![CI](https://github.com/sylvesterkaczmarek/worldstate-check/actions/workflows/ci.yml/badge.svg)](https://github.com/sylvesterkaczmarek/worldstate-check/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

**Verify that an autonomous action changed the world as intended.**

WorldState Check evaluates explicit postconditions against independent observations after an AI agent, automation, robot, or autonomous system acts. It distinguishes a successful command from a verified outcome and uses deterministic verdict logic and produces a structured evidence report without requiring an LLM judge.

## At a glance

```text
INTENT
  |
ACTION
  |
ACKNOWLEDGEMENT
  |
OBSERVED WORLD STATE
  |
POSTCONDITIONS
  |
VERIFIED / NOT_VERIFIED / UNCERTAIN
```

A tool call returning success is not the same as the requested state being achieved.

```text
Agent: "Safe mode entered."

$ worldstate-check demo

[PASS   ] command-ack
[PASS   ] payload-power
[FAIL   ] attitude-error
[PASS   ] battery-soc

VERDICT: NOT_VERIFIED
Required checks: 3/4 passed
```

The command was acknowledged and the payload was powered down, but the synthetic attitude error remained outside the required bound.

## Why this is useful

The same verification pattern applies across software and physical autonomy:

- an agent says a deployment succeeded, but the health endpoint still fails;
- a maintenance workflow closes a job, but the measured equipment state remains outside limits;
- a spacecraft accepts a safe-mode command, but telemetry shows the required attitude was not reached;
- an automation reports completion, but the expected file, process, API state, or database-facing evidence is absent.

WorldState Check makes the success condition explicit and evaluates observable state instead of trusting the actor's completion claim.

## Check types

| Type | What it verifies |
| --- | --- |
| `file` | existence, text assertions, SHA-256 |
| `json` | structured state through deterministic field comparisons |
| `metric` | JSON or CSV telemetry, thresholds, ranges, freshness |
| `http` | status, response text, JSON response state |
| `tcp` | endpoint reachability |
| `command` | explicit verification commands, opt-in only |

Required checks produce one of three verdicts:

- `VERIFIED` when every required postcondition passes;
- `NOT_VERIFIED` when at least one required postcondition fails;
- `UNCERTAIN` when no required check fails but reliable evidence is unavailable for one or more required checks.

## Quick start

```bash
git clone https://github.com/sylvesterkaczmarek/worldstate-check.git
cd worldstate-check
python -m pip install .
worldstate-check demo
```

Run a passing synthetic scenario:

```bash
worldstate-check demo --scenario verified
```

Create a starter specification:

```bash
worldstate-check init worldstate.yaml
```

Validate it without touching any evidence source:

```bash
worldstate-check validate worldstate.yaml
```

Then verify the observed state:

```bash
worldstate-check verify worldstate.yaml
```

Write a machine-readable evidence report:

```bash
worldstate-check verify worldstate.yaml --report evidence.json
worldstate-check verify-report evidence.json
```

## Verification specification

```yaml
version: 1
task: spacecraft-safe-mode

checks:
  - id: payload-off
    type: json
    path: telemetry.json
    field: payload.power
    operator: eq
    value: "off"

  - id: attitude-error
    type: metric
    source:
      type: json
      path: telemetry.json
      field: attitude.error_deg
    operator: lte
    value: 3.0

  - id: battery-reserve
    type: metric
    source:
      type: json
      path: telemetry.json
      field: battery.soc
    operator: gte
    value: 25.0
```

See [docs/specification.md](docs/specification.md) for all supported checks.

## Telemetry freshness

A value can be numerically valid and still be unsafe evidence if it is stale. Metric checks can require a recent timestamp:

```yaml
- id: temperature
  type: metric
  source:
    type: json
    path: telemetry.json
    field: temperature_c
    timestamp_field: observed_at
    max_age_seconds: 5
  operator: lte
  value: 75
```

Stale required telemetry causes `NOT_VERIFIED` because the available observation does not satisfy the declared freshness postcondition.

## Waiting for eventual state

Some effects are asynchronous. `--wait` re-evaluates the postconditions until they pass or the timeout expires:

```bash
worldstate-check verify deployment.yaml --wait 30
```

The report records the number of attempts. Keep verification checks idempotent when using retries.

## Safety boundaries

WorldState Check treats the verification specification as potentially powerful input.

- evidence paths are confined to the verification root by default;
- paths outside that root require `--allow-outside-root`;
- command checks require `--allow-command`;
- commands use an argument vector with `shell=False`;
- command checks receive only `PATH` and `HOME` from the parent environment;
- evidence reads have explicit size limits where practical.

See [docs/security.md](docs/security.md).

## Example physical-system checks

The repository contains two runnable file-backed examples:

```bash
worldstate-check verify examples/field-maintenance.yaml
worldstate-check verify examples/spacecraft-safe-mode.yaml
```

The first is expected to verify. The second is intentionally expected to return `NOT_VERIFIED` because the attitude-error postcondition fails.

## Evidence report

JSON reports include:

- task and final verdict;
- every expected and observed value;
- required versus optional checks;
- timing and attempt count;
- source metadata such as evidence path, endpoint, or telemetry age;
- a SHA-256 digest of the report payload.

`worldstate-check verify-report` recomputes that digest and reports whether the saved payload still matches it. The digest is not a digital signature and does not establish the identity or trustworthiness of the evidence source.

## Assurance model

WorldState Check verifies declared postconditions against observations. It does not prove that sensors, endpoints, files, or other evidence sources are trustworthy or correctly calibrated. It also does not determine whether the original intent was safe.

See [docs/assurance-model.md](docs/assurance-model.md) for the exact scope.

## Repository layout

```text
worldstate-check/
├── .github/workflows/ci.yml
├── assets/social/
├── docs/
├── examples/
├── src/worldstate_check/
│   ├── checks/
│   ├── cli.py
│   ├── engine.py
│   ├── loader.py
│   ├── models.py
│   └── report.py
├── tests/
├── CITATION.cff
├── LICENSE
├── Makefile
├── pyproject.toml
└── README.md
```

## Development

```bash
python -m pip install -e .
python -m pip install pytest
pytest
```

The core verdict path is deterministic and does not call an LLM.

## Cite this repository

If you use or adapt this repository, please cite:

> Kaczmarek, S. (2026). *WorldState Check*. GitHub. https://github.com/sylvesterkaczmarek/worldstate-check

```bibtex
@software{Kaczmarek_2026_WorldState_Check,
  author = {Sylvester Kaczmarek},
  title  = {{WorldState Check}},
  year   = {2026},
  url    = {https://github.com/sylvesterkaczmarek/worldstate-check}
}
```

## License

MIT. See [LICENSE](LICENSE).

© **Sylvester Kaczmarek** · [https://www.sylvesterkaczmarek.com](https://www.sylvesterkaczmarek.com)
