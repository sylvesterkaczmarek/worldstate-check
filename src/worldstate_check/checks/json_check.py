from __future__ import annotations

import json
from typing import Any

from worldstate_check.errors import PathBoundaryError, SpecError
from worldstate_check.models import CheckStatus, VerificationContext
from worldstate_check.util import compare_value, extract_dotted, resolve_path

from .base import timed_result, unknown


def run_json_check(check: dict[str, Any], ctx: VerificationContext):
    try:
        path = resolve_path(ctx.root, check["path"], ctx.allow_outside_root)
    except PathBoundaryError as exc:
        return unknown(check, str(exc))

    def evaluate():
        evidence = {"path": str(path), "field": check["field"]}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return CheckStatus.FAIL, "JSON file does not exist", None, None, evidence, None
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
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
