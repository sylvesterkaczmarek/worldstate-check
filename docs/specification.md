# Specification

A specification is YAML with `version`, `task`, and a non-empty `checks` list.

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

## Metric

Metrics read the latest state from JSON or the final row of a CSV file.

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

ISO-8601 UTC strings and Unix epoch timestamps are accepted.

## HTTP

```yaml
- id: service-health
  type: http
  url: http://127.0.0.1:8080/health
  status: 200
  json_field: status
  operator: eq
  value: ready
```

HTTP checks use GET. They can assert `status`, `text_contains`, or a JSON field comparison.

## TCP

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

Commands are executed without a shell. Specifications must provide an argument vector rather than a shell command string.
