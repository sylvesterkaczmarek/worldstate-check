from __future__ import annotations

from typing import Any

from worldstate_check.errors import PathBoundaryError, SpecError
from worldstate_check.models import CheckStatus, VerificationContext
from worldstate_check.util import MISSING, compare_value, field_value, strict_json_loads

from .base import timed_result, unknown
from worldstate_check.observations import resolve_evidence_path, observation, observation_text


def run_json_check(check: dict[str, Any], ctx: VerificationContext):
    try:
        path = resolve_evidence_path(ctx, check["path"])
    except PathBoundaryError as exc:
        return unknown(check, str(exc))

    def evaluate():
        limit = int(check.get('max_read_bytes', 1_048_576))
        item = observation(path, ctx, limit)
        evidence = {**item.evidence(path, ctx.root), "field": check["field"]}
        try:
            raw = observation_text(item, limit)
            data = strict_json_loads(raw)
        except FileNotFoundError:
            return CheckStatus.FAIL, "JSON file does not exist", None, None, evidence, None
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            return CheckStatus.UNKNOWN, "could not parse JSON evidence", None, None, evidence, str(exc)
        observed = field_value(data, check["field"])
        evidence["field_present"] = observed is not MISSING
        try:
            matched, expected = compare_value(observed, check["operator"], check)
        except (ValueError, SpecError) as exc:
            return CheckStatus.UNKNOWN, "JSON comparison could not be evaluated", None, None if observed is MISSING else observed, evidence, str(exc)
        if check["operator"] == "exists":
            observed = observed is not MISSING
        if matched:
            return CheckStatus.PASS, "JSON postcondition satisfied", expected, observed, evidence, None
        return CheckStatus.FAIL, "JSON postcondition not satisfied", expected, observed, evidence, None

    return timed_result(check, evaluate)
