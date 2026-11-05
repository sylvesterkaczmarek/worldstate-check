from __future__ import annotations

import csv
import io
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from worldstate_check.errors import PathBoundaryError, SpecError
from worldstate_check.models import CheckStatus, VerificationContext
from worldstate_check.util import (
    compare_value,
    extract_dotted,
    freshness_age_seconds,
    read_text_limited,
    strict_json_loads,
)

from .base import timed_result, unknown
from worldstate_check.observations import resolve_evidence_path, observation, observation_text

DEFAULT_MAX_TELEMETRY_BYTES = 16 * 1024 * 1024
_MISSING_VALUE = object()


def run_metric_check(check: dict[str, Any], ctx: VerificationContext):
    source = check["source"]
    try:
        path = resolve_evidence_path(ctx, source["path"])
    except PathBoundaryError as exc:
        return unknown(check, str(exc))

    def evaluate():
        limit = int(source.get('max_read_bytes', DEFAULT_MAX_TELEMETRY_BYTES))
        item = observation(path, ctx, limit)
        evidence: dict[str, Any] = {**item.evidence(path, ctx.root), "source_type": source["type"]}
        try:
            observed, timestamp_value = _read_source(path, source, raw=observation_text(item, limit))
        except FileNotFoundError:
            return CheckStatus.FAIL, "telemetry source does not exist", None, None, evidence, None
        except (OSError, UnicodeDecodeError, csv.Error, KeyError, ValueError) as exc:
            return CheckStatus.UNKNOWN, "could not read telemetry evidence", None, None, evidence, str(exc)

        failures, errors = [], []
        expected = None
        try:
            if observed is _MISSING_VALUE:
                raise ValueError("metric value is missing from the observation")
            matched, expected = compare_value(observed, check["operator"], check)
            if not matched:
                failures.append("metric postcondition not satisfied")
        except (ValueError, SpecError) as exc:
            errors.append(f"metric comparison could not be evaluated: {exc}")

        result_observed = None if observed is _MISSING_VALUE else observed
        if "max_age_seconds" in source:
            evidence["observed_timestamp"] = timestamp_value
            evidence["max_age_seconds"] = source["max_age_seconds"]
            try:
                age = freshness_age_seconds(timestamp_value, datetime.now(timezone.utc))
            except (ValueError, OSError, OverflowError) as exc:
                errors.append(f"could not evaluate telemetry freshness: {exc}")
            else:
                evidence["age_seconds"] = age
                if age > float(source["max_age_seconds"]):
                    failures.append("telemetry is stale")
                    expected = {"max_age_seconds": source["max_age_seconds"], "comparison": expected}
                    result_observed = {"age_seconds": age, "value": result_observed}
        status = CheckStatus.FAIL if failures else CheckStatus.UNKNOWN if errors else CheckStatus.PASS
        summary = "; ".join(failures) if failures else errors[0] if errors else "metric postcondition satisfied"
        return status, summary, expected, result_observed, evidence, "; ".join(errors) or None

    return timed_result(check, evaluate)


def _read_source(path: Path, source: dict[str, Any], *, raw=None) -> tuple[Any, Any]:
    if raw is None:
        raw = read_text_limited(path, int(source.get("max_read_bytes", DEFAULT_MAX_TELEMETRY_BYTES)))
    if source["type"] == "json":
        data = strict_json_loads(raw)
        try:
            observed = extract_dotted(data, source["field"])
        except KeyError:
            observed = _MISSING_VALUE
        timestamp = None
        if "max_age_seconds" in source:
            try:
                timestamp = extract_dotted(data, source["timestamp_field"])
            except KeyError:
                pass  # Value remains usable; freshness will be inconclusive.
        return observed, timestamp

    reader = csv.DictReader(io.StringIO(raw.lstrip("\ufeff")), strict=True)
    if reader.fieldnames is None:
        raise ValueError("CSV telemetry source has no header")
    if len(reader.fieldnames) != len(set(reader.fieldnames)):
        raise ValueError("CSV telemetry source has duplicate column names")
    row: dict[str, str | None] | None = None
    for row in reader:
        if None in row or any(value is None for value in row.values()):
            raise ValueError("CSV telemetry row does not match the complete header")
    if row is None:
        raise ValueError("CSV telemetry source has no data rows")
    observed = _coerce_scalar(row[source["column"]]) if source["column"] in row else _MISSING_VALUE
    timestamp = row.get(source["timestamp_column"]) if "max_age_seconds" in source else None
    return observed, timestamp


def _coerce_scalar(value: str | None) -> Any:
    if value is None:
        raise ValueError("CSV telemetry value is missing")
    stripped = value.strip()
    lowered = stripped.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    try:
        if any(c in stripped for c in ".eE"):
            value_float = float(stripped)
            if not math.isfinite(value_float):
                return stripped
            return value_float
        return int(stripped)
    except ValueError:
        return stripped
