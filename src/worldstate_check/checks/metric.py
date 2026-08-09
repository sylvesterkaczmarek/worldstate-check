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
    evidence_path,
    extract_dotted,
    freshness_age_seconds,
    read_text_limited,
    resolve_path,
    strict_json_loads,
)

from .base import timed_result, unknown

DEFAULT_MAX_TELEMETRY_BYTES = 16 * 1024 * 1024


def run_metric_check(check: dict[str, Any], ctx: VerificationContext):
    source = check["source"]
    try:
        path = resolve_path(ctx.root, source["path"], ctx.allow_outside_root)
    except PathBoundaryError as exc:
        return unknown(check, str(exc))

    def evaluate():
        evidence: dict[str, Any] = {"path": evidence_path(path, ctx.root), "source_type": source["type"]}
        try:
            observed, timestamp_value = _read_source(path, source)
        except FileNotFoundError:
            return CheckStatus.FAIL, "telemetry source does not exist", None, None, evidence, None
        except (OSError, UnicodeDecodeError, csv.Error, KeyError, ValueError) as exc:
            return CheckStatus.UNKNOWN, "could not read telemetry evidence", None, None, evidence, str(exc)

        if "max_age_seconds" in source:
            try:
                age = freshness_age_seconds(timestamp_value, datetime.now(timezone.utc))
            except (ValueError, OSError, OverflowError) as exc:
                return CheckStatus.UNKNOWN, "could not evaluate telemetry freshness", None, observed, evidence, str(exc)
            evidence["age_seconds"] = round(age, 3)
            evidence["max_age_seconds"] = source["max_age_seconds"]
            if age > float(source["max_age_seconds"]):
                return (
                    CheckStatus.FAIL,
                    "telemetry is stale",
                    {"max_age_seconds": source["max_age_seconds"]},
                    {"age_seconds": round(age, 3), "value": observed},
                    evidence,
                    None,
                )

        try:
            matched, expected = compare_value(observed, check["operator"], check)
        except (ValueError, SpecError) as exc:
            return CheckStatus.UNKNOWN, "metric comparison could not be evaluated", None, observed, evidence, str(exc)
        if matched:
            return CheckStatus.PASS, "metric postcondition satisfied", expected, observed, evidence, None
        return CheckStatus.FAIL, "metric postcondition not satisfied", expected, observed, evidence, None

    return timed_result(check, evaluate)


def _read_source(path: Path, source: dict[str, Any]) -> tuple[Any, Any]:
    raw = read_text_limited(path, int(source.get("max_read_bytes", DEFAULT_MAX_TELEMETRY_BYTES)))
    if source["type"] == "json":
        data = strict_json_loads(raw)
        observed = extract_dotted(data, source["field"])
        timestamp = extract_dotted(data, source["timestamp_field"]) if "max_age_seconds" in source else None
        return observed, timestamp

    reader = csv.DictReader(io.StringIO(raw.lstrip("\ufeff")))
    if reader.fieldnames is None:
        raise ValueError("CSV telemetry source has no header")
    if len(reader.fieldnames) != len(set(reader.fieldnames)):
        raise ValueError("CSV telemetry source has duplicate column names")
    row: dict[str, str | None] | None = None
    for row in reader:
        if None in row:
            raise ValueError("CSV telemetry row has more values than the header")
    if row is None:
        raise ValueError("CSV telemetry source has no data rows")
    if source["column"] not in row:
        raise KeyError(source["column"])
    observed = _coerce_scalar(row[source["column"]])
    timestamp = row[source["timestamp_column"]] if "max_age_seconds" in source else None
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
