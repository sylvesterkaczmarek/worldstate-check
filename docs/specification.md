# Specification

A specification is YAML with `version`, `task`, and a non-empty `checks` list. Duplicate YAML keys are rejected. Values must remain JSON-compatible so that evidence reports are always serializable.

```yaml
version: 1
task: deploy-api
checks:
  - id: health
    type: http
    url: http://127.0.0.1:8080/health
    status: 200
```

Each check is required by default. Set `required: false` for evidence that should be reported without blocking the final verdict.

## File

```yaml
- id: marker
  type: file
  path: state/ready.txt
  exists: true
  contains: READY
```

Assertions: `exists`, `contains`, `not_contains`, `sha256`.

Text assertions read at most 1 MiB by default. Set `max_read_bytes` to an explicit positive integer when a different limit is required.

## JSON

```yaml
- id: migration
  type: json
  path: state/status.json
  field: database.migration
  operator: eq
  value: complete
```

Nested fields use dot notation. Numeric list indexes are supported, for example `items.0.status`.

Operators: `eq`, `ne`, `lt`, `lte`, `gt`, `gte`, `between`, `in`.

`lt`, `lte`, `gt`, `gte`, and `between` require finite numeric thresholds. `between` requires `min <= max`. `tolerance` is supported only with `eq` or `ne` and requires a numeric expected value.

JSON evidence is limited to 1 MiB by default. Use `max_read_bytes` to change the limit.

## Metric

Metrics read the current value from JSON or the final row of a CSV file.

```yaml
- id: attitude-error
  type: metric
  source:
    type: json
    path: telemetry.json
    field: attitude.error_deg
  operator: lte
  value: 3.0
```

CSV example:

```yaml
- id: vibration
  type: metric
  source:
    type: csv
    path: telemetry.csv
    column: vibration_rms
  operator: lte
  value: 2.5
```

Freshness can be enforced when the source contains a timestamp:

```yaml
source:
  type: json
  path: telemetry.json
  field: temperature_c
  timestamp_field: observed_at
  max_age_seconds: 5
```

ISO-8601 UTC strings and Unix epoch timestamps are accepted. A timestamp more than one second in the future produces `UNKNOWN` rather than being treated as fresh.

Telemetry sources are limited to 16 MiB by default. Set `source.max_read_bytes` when a different explicit bound is required.

## HTTP

HTTP checks are disabled unless `--allow-network` is supplied.

```yaml
- id: service-health
  type: http
  url: http://127.0.0.1:8080/health
  status: 200
  json_field: status
  operator: eq
  value: ready
```

HTTP checks use GET. They can assert `status`, `text_contains`, or a JSON field comparison. Response bodies are capped at 1 MiB. URLs recorded in evidence reports omit credentials, query strings, and fragments.

## TCP

TCP checks are also disabled unless `--allow-network` is supplied.

```yaml
- id: service-port
  type: tcp
  host: 127.0.0.1
  port: 8080
  reachable: true
```

## Command

Command checks are disabled unless `--allow-command` is supplied.

```yaml
- id: service-test
  type: command
  argv: ["python", "-m", "pytest", "-q"]
  exit_code: 0
```

Commands are executed without a shell and with standard input disabled. Specifications must provide an argument vector rather than a shell command string. Captured output is bounded by `max_output_bytes`, which defaults to 65,536 bytes per stream. Raw argv and output are not copied into evidence reports; hashes and byte counts are recorded instead.
