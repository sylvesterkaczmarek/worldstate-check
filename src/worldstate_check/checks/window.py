"""Check a predicate at distinct, attributable samples spanning a closed interval."""

from __future__ import annotations

from ..errors import PathBoundaryError
from ..models import CheckStatus
from ..observations import observation, observation_text, resolve_evidence_path
from ..util import (
    MISSING,
    compare_value,
    field_value,
    parse_timestamp,
    strict_json_loads,
)
from .base import timed_result, unknown


def _window_samples(rows, check, start, end, errors, legacy_identity):
    if not isinstance(rows, list):
        raise ValueError("sample series is missing or malformed")
    samples = {}
    for row in rows:
        if not isinstance(row, dict):
            errors.add("malformed sample")
            continue
        bindings = {k: field_value(row, k) for k in check.get("match", {})}
        missing_binding = any(value is MISSING for value in bindings.values())
        known_mismatch = any(
            value is not MISSING
            and not compare_value(value, "eq", {"value": check["match"][k]})[0]
            for k, value in bindings.items()
        )
        if legacy_identity and missing_binding:
            errors.add("missing sample identity")
            continue
        if known_mismatch:
            continue
        timestamp = field_value(row, check["timestamp_field"])
        try:
            when = parse_timestamp(timestamp)
        except (ValueError, OSError, OverflowError):
            errors.add("invalid sample time")
            continue
        if not start <= when <= end:
            continue
        if missing_binding:
            errors.add("missing sample identity")
            continue
        identity = field_value(row, check["sample_id_field"])
        if type(identity) not in (int, str) or identity == "":
            errors.add("missing sample ID")
            continue
        if identity in samples:
            errors.add("repeated sample ID")
            if not legacy_identity:
                samples[identity] = None
            continue
        samples[identity] = (when, timestamp, row)
    return samples


def evaluate_window(rows, check, *, legacy_identity=False):
    start, end = (parse_timestamp(check[key]) for key in ("start", "end"))
    errors = set()
    samples = _window_samples(rows, check, start, end, errors, legacy_identity)
    first = previous = None
    observed = {"samples": 0, "violations": 0}
    for identity, sample in samples.items():
        if sample is None:
            continue
        when, timestamp, row = sample
        if previous is not None:
            gap = (when - previous).total_seconds()
            if gap <= 0 or gap > check["max_gap_seconds"]:
                errors.add("unordered samples or excessive gap")
        if first is None:
            first = when
        previous = when
        observed["samples"] += 1
        value = field_value(row, check["field"])
        try:
            passed, _ = compare_value(value, check["operator"], check)
        except ValueError:
            errors.add("unavailable sample value")
        else:
            if not passed:
                observed["violations"] += 1
                if "first_violation" not in observed:
                    observed["first_violation"] = {
                        "sample_id": identity,
                        "timestamp": timestamp,
                        "field_present": value is not MISSING,
                    }
                    if check["operator"] != "exists":
                        observed["first_violation"]["value"] = value
    if first != start or previous != end:
        errors.add("missing window boundary sample")
    status = (
        CheckStatus.FAIL
        if observed["violations"]
        else CheckStatus.UNKNOWN
        if errors
        else CheckStatus.PASS
    )
    return status, observed, sorted(errors)


def run_window_check(check, ctx):
    try:
        path = resolve_evidence_path(ctx, check["path"])
    except PathBoundaryError as exc:
        return unknown(check, str(exc))

    def evaluate():
        limit = check.get("max_read_bytes", 1_048_576)
        item = observation(path, ctx, limit)
        evidence = item.evidence(path, ctx.root)
        expected = {
            key: check[key]
            for key in (
                "start",
                "end",
                "max_gap_seconds",
                "field",
                "operator",
                "value",
                "values",
                "min",
                "max",
                "tolerance",
            )
            if key in check
        }
        try:
            data = strict_json_loads(observation_text(item, limit))
            status, observed, errors = evaluate_window(
                field_value(data, check["series"]),
                check,
                legacy_identity=ctx._frame is not None
                and ctx._frame.legacy_window_identity,
            )
        except (ValueError, OSError) as exc:
            return (
                CheckStatus.UNKNOWN,
                "sample window unavailable",
                expected,
                None,
                evidence,
                str(exc),
            )
        evidence["window_errors"] = errors
        summary = {
            CheckStatus.PASS: "sampled window satisfied",
            CheckStatus.FAIL: "sampled window violated",
            CheckStatus.UNKNOWN: "incomplete sampled window",
        }[status]
        return status, summary, expected, observed, evidence, ", ".join(errors) or None

    return timed_result(check, evaluate)
