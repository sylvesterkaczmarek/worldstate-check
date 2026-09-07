from __future__ import annotations

import urllib.error
import urllib.request
from contextlib import closing
from http.client import HTTPException
from typing import Any

from worldstate_check.errors import SpecError
from worldstate_check.models import CheckStatus, VerificationContext
from worldstate_check.util import compare_value, extract_dotted, redact_url_for_evidence, strict_json_loads

from .base import timed_result, unknown


def run_http_check(check: dict[str, Any], ctx: VerificationContext):
    if not ctx.allow_network:
        return unknown(check, "network checks are disabled; pass --allow-network for a trusted specification")

    def evaluate():
        timeout = float(check.get("timeout_seconds", 3.0))
        evidence: dict[str, Any] = {"url": redact_url_for_evidence(check["url"])}
        try:
            request = urllib.request.Request(check["url"], method="GET", headers={"User-Agent": "worldstate-check/0.1"})
            try:
                response = urllib.request.urlopen(request, timeout=timeout)
            except urllib.error.HTTPError as exc:
                # Error responses are still valid evidence for an explicit status assertion.
                response = exc
            with closing(response):
                status = response.status
                body_bytes = response.read(1_048_577)
        except (urllib.error.URLError, TimeoutError, OSError, HTTPException, ValueError) as exc:
            # Transport messages may contain the request URL or a redirect URL,
            # including credentials. Retain the failure class without that text.
            return CheckStatus.FAIL, "HTTP request or response could not be completed", None, None, evidence, type(exc).__name__

        observed: dict[str, Any] = {"status": status}
        expected: dict[str, Any] = {}
        failures: list[str] = []

        if "status" in check:
            expected["status"] = check["status"]
            if status != check["status"]:
                failures.append(f"status={status}")
        if len(body_bytes) > 1_048_576:
            summary = "; ".join([*failures, "HTTP response exceeds 1 MiB evidence limit"])
            result_status = CheckStatus.FAIL if failures else CheckStatus.UNKNOWN
            return result_status, summary, expected, observed, evidence, None
        if "text_contains" in check:
            body = body_bytes.decode("utf-8", errors="replace")
            expected["text_contains"] = check["text_contains"]
            matched = check["text_contains"] in body
            observed["text_contains"] = matched
            if not matched:
                failures.append("required response text missing")
        if "json_field" in check:
            error_context = "HTTP response must be valid UTF-8 JSON with unique keys and finite numbers"
            try:
                payload = strict_json_loads(body_bytes.decode("utf-8"))
                error_context = "HTTP JSON field is missing or incompatible with the requested comparison"
                value = extract_dotted(payload, check["json_field"])
                matched, expected_value = compare_value(value, check["operator"], check)
            except (KeyError, ValueError, SpecError, RecursionError):
                # Do not let an unevaluable assertion hide an already observed
                # failure, or echo arbitrary response data through parser errors.
                summary = "; ".join([*failures, "HTTP JSON assertion could not be evaluated"])
                result_status = CheckStatus.FAIL if failures else CheckStatus.UNKNOWN
                return result_status, summary, expected, observed, evidence, error_context
            expected["json"] = {"field": check["json_field"], "value": expected_value, "operator": check["operator"]}
            observed["json"] = {"field": check["json_field"], "value": value}
            if not matched:
                failures.append("JSON response postcondition not satisfied")

        evidence["body_bytes"] = len(body_bytes)
        if failures:
            return CheckStatus.FAIL, "; ".join(failures), expected, observed, evidence, None
        return CheckStatus.PASS, "HTTP postcondition satisfied", expected, observed, evidence, None

    return timed_result(check, evaluate)
