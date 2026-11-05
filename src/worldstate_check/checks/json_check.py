from __future__ import annotations

from typing import Any

from worldstate_check.errors import PathBoundaryError, SpecError
from worldstate_check.models import CheckStatus, VerificationContext
from worldstate_check.util import compare_value, extract_dotted, strict_json_loads

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
        try:
            observed = extract_dotted(data, check["field"])
        except KeyError:
            return CheckStatus.FAIL, f"JSON field not found: {check['field']}", None, None, evidence, None
        try:
            matched, expected = compare_value(observed, check["operator"], check)
        except (ValueError, SpecError) as exc:
            return CheckStatus.UNKNOWN, "JSON comparison could not be evaluated", None, observed, evidence, str(exc)
        if matched:
            return CheckStatus.PASS, "JSON postcondition satisfied", expected, observed, evidence, None
        return CheckStatus.FAIL, "JSON postcondition not satisfied", expected, observed, evidence, None

    return timed_result(check, evaluate)
