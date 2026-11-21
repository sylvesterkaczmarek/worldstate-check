# Observable outcomes and offline replay

## Changes from 0.2.0

| Input | Result in this revision | Migration |
| --- | --- | --- |
| Two HTTP checks of one resource | One GET per URL and sample name per attempt. Failures are shared too. | Omit `sample` to evaluate one response. Give different `sample` names only when the experiment calls for distinct acquisitions. Checks sharing a sample must agree on timeout and redirect policy. |
| HTTP redirect | The initial 3xx response is available for an explicit status assertion. A redirected sign-in page cannot satisfy a health check. | To permit a canonical destination, specify its exact absolute URL in `redirect_to`. Only that destination may be followed. Reports record redacted requested and effective URLs, redirect metadata, capture time and a digest of the complete bounded body when available. |
| Missing field in a well-formed object | A value comparison gives UNKNOWN across local JSON, metric and HTTP JSON. | For a requirement that the field must exist, use `operator: exists` with `value: true`. Use false to require absence. 0.2.0 local JSON treated an absent field as FAIL. |
| Source timestamps | `timestamp_field` and `timestamp_column` require `max_age_seconds`. Age uses the time of observation. | Specify both fields. Capture time describes the reader. Source event time describes the underlying measurement. |
| Large values | Reports inline small values and replace bulky values with typed canonical JSON byte lengths and SHA-256 references under `evidence.value_references`. | Inspect the reference before interpreting null as an observed JSON null. The reference identifies the corresponding value in the specification or captured observation. Text output shows the same byte lengths and hashes for oversized values. New output uses report schema 2. Legacy schema-1 reports remain readable. Upgrade downstream readers before switching the writer. |

| Observation | Value comparison | Explicit presence |
| --- | --- | --- |
| Missing field in a parsed object | UNKNOWN | FAIL for required presence, PASS for required absence |
| Present JSON null | PASS for equality to null, UNKNOWN for numeric ordering | PASS for presence |
| Malformed JSON | UNKNOWN | UNKNOWN |
| Known threshold violation | FAIL | Independently evaluated |
| Declared freshness bound exceeded | FAIL, including when the metric value is missing | Independently evaluated |

A failed HTTP status or other known required failure takes precedence over an unevaluable assertion. A missing local source still fails the existing file-backed JSON and metric source requirement.

## Record an evaluation

```bash
worldstate-check verify task.yaml --record run.json --report decision.json
worldstate-check replay run.json --json
worldstate-check verify-report decision.json
```

In Python, pass `record_to=path` to `verify_spec` or `verify_spec_data`. Use `worldstate_check.replay.replay_bundle(path)` to obtain a VerificationReport. Replay uses the recorded observations, acquisition permissions and source clock for every attempt. It recomputes predicates, machine-readable reason codes and verdicts and checks them against the recorded decisions. Execution timings of individual replayed predicates are new measurements. The returned overall timing identifies the original run.

Format `worldstate-check/observations/1` includes the evaluator revision, package version, spec hash, original specification, ordered acquisition records, decision history and bundle checksum. Binary inputs use base64. The maximum encoded recording is 64 MiB. Oversized recordings fail explicitly and the previous output survives. File, HTTP, TCP and command acquisitions all replay without contacting the original sources. Existing reports can be checked structurally with `verify-report`. Historical replay needs a recording captured during evaluation.

**Handle recordings as raw evidence.** They include the full specification, paths, source bytes, HTTP bodies and command streams used in the run. Reports redact URL credentials and limit large fields. An unkeyed checksum detects changes relative to a trusted copy. Authenticate a recording separately when its origin matters.

## Sampled persistence and attribution

The `window` check reads a JSON array selected by `series`. It applies a predicate to rows matching every optional `match` identity. Supply `timestamp_field`, `sample_id_field`, `start`, `end` and a positive `max_gap_seconds`. Times are timezone-qualified strings or epoch seconds. Use distinct integer or string IDs. Both boundaries must be sampled. Repeated IDs, missing identities, unordered times, missing boundary samples and gaps exceeding the declared limit prevent a pass. New recordings use evaluator 2. Within the matched interval, all copies of a repeated ID are excluded. A definite violation in a different, uniquely identified sample still yields FAIL. A row known to belong to another subject is ignored even if another match field is missing. When a sample fails, `observed.first_violation` identifies its ID, source timestamp and value, and `expected` records the predicate. Replay honours the identity rules of evaluator-1 recordings, including their original first-occurrence treatment of repeated IDs. A sampled pass applies only to the observations collected. The pilot contains a deployment fault entirely between sample times. [Runnable contract](../examples/placement/spec.json)

For a new transition, bind the observations to the request and add a predicate for the pre-action state. When an already-achieved goal is acceptable, omit the transition requirement. Route the observation through a source controlled by the evaluator. Repeating a claim from one producer in two places adds no independent evidence.

## Use with Inspect AI

Install the checkout with `python -m pip install '.[inspect]'`. Supply a trusted specification and a mapping from Inspect sample IDs to evaluator-owned directories. The optional scorer evaluates after the solver finishes. It returns the verdict, per-check reasons and separate verified, failed and uncertain indicators. The mean of each indicator gives its rate. The task owner controls evidence acquisition, including any transfer from an observation sandbox. Run the supplied three-sample task without a paid model:

```bash
inspect eval examples/inspect/task.py --model mockllm/model
```
