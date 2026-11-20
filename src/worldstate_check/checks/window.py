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


def evaluate_window(rows, check):
    start, end = (parse_timestamp(check[key]) for key in ("start", "end"))
    if not isinstance(rows, list):
        raise ValueError("sample series is missing or malformed")
    seen = set()
    first = previous = None
    count = 0
    errors = set()
    violations = 0
    for row in rows:
        if not isinstance(row, dict):
            errors.add("malformed sample")
            continue
        bindings = {k: field_value(row, k) for k in check.get("match", {})}
        if any(value is MISSING for value in bindings.values()):
            errors.add("missing sample identity")
            continue
        if any(
            not compare_value(value, "eq", {"value": check["match"][k]})[0]
            for k, value in bindings.items()
        ):
            continue
        try:
            when = parse_timestamp(field_value(row, check["timestamp_field"]))
        except (ValueError, OSError, OverflowError):
            errors.add("invalid sample time")
            continue
        if not start <= when <= end:
            continue
        identity = field_value(row, check["sample_id_field"])
        if type(identity) not in (int, str) or identity == "" or identity in seen:
            errors.add("missing or repeated sample ID")
            continue
        seen.add(identity)
        if previous is not None:
            gap = (when - previous).total_seconds()
            if gap <= 0 or gap > check["max_gap_seconds"]:
                errors.add("unordered samples or excessive gap")
        if first is None:
            first = when
        previous = when
        count += 1
        try:
            passed, _ = compare_value(
                field_value(row, check["field"]), check["operator"], check
            )
        except ValueError:
            errors.add("unavailable sample value")
        else:
            violations += int(not passed)
    if first != start or previous != end:
        errors.add("missing window boundary sample")
    status = (
        CheckStatus.FAIL
        if violations
        else CheckStatus.UNKNOWN
        if errors
        else CheckStatus.PASS
    )
    return status, {"samples": count, "violations": violations}, sorted(errors)


def run_window_check(check, ctx):
    try:
        path = resolve_evidence_path(ctx, check["path"])
    except PathBoundaryError as exc:
        return unknown(check, str(exc))

    def evaluate():
        limit = check.get("max_read_bytes", 1_048_576)
        item = observation(path, ctx, limit)
        evidence = item.evidence(path, ctx.root)
        expected = {key: check[key] for key in ("start", "end", "max_gap_seconds")}
        try:
            data = strict_json_loads(observation_text(item, limit))
            status, observed, errors = evaluate_window(
                field_value(data, check["series"]), check
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
