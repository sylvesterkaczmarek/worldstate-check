from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from typing import Any

from worldstate_check.errors import PathBoundaryError, SpecError
from worldstate_check.models import CheckStatus, VerificationContext
from worldstate_check.util import compare_value, extract_dotted, freshness_age_seconds, resolve_path

from .base import timed_result, unknown


def run_metric_check(check: dict[str, Any], ctx: VerificationContext):
    source = check["source"]
    try:
        path = resolve_path(ctx.root, source["path"], ctx.allow_outside_root)
    except PathBoundaryError as exc:
        return unknown(check, str(exc))

    def evaluate():
        evidence: dict[str, Any] = {"path": str(path), "source_type": source["type"]}
        try:
            observed, timestamp_value = _read_source(path, source)
        except FileNotFoundError:
            return CheckStatus.FAIL, "telemetry source does not exist", None, None, evidence, None
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, csv.Error, KeyError, ValueError) as exc:
            return CheckStatus.UNKNOWN, "could not read telemetry evidence", None, None, evidence, str(exc)

        if "max_age_seconds" in source:
            try:
                age = freshness_age_seconds(timestamp_value, datetime.now(timezone.utc))
            except (ValueError, OSError) as exc:
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


def _read_source(path, source: dict[str, Any]) -> tuple[Any, Any]:
    if source["type"] == "json":
        data = json.loads(path.read_text(encoding="utf-8"))
        observed = extract_dotted(data, source["field"])
        timestamp = extract_dotted(data, source["timestamp_field"]) if "max_age_seconds" in source else None
        return observed, timestamp

    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("CSV telemetry source has no data rows")
    row = rows[-1]
    if source["column"] not in row:
        raise KeyError(source["column"])
    observed = _coerce_scalar(row[source["column"]])
    timestamp = row[source["timestamp_column"]] if "max_age_seconds" in source else None
    return observed, timestamp


def _coerce_scalar(value: str) -> Any:
    stripped = value.strip()
    lowered = stripped.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    try:
        if any(c in stripped for c in ".eE"):
            return float(stripped)
        return int(stripped)
    except ValueError:
        return stripped
