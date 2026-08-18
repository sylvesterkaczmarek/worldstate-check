from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from worldstate_check.errors import SpecError
from worldstate_check.models import CheckStatus, VerificationContext
from worldstate_check.util import compare_value, extract_dotted

from .base import timed_result, unknown


def run_http_check(check: dict[str, Any], ctx: VerificationContext):
    if not ctx.allow_network:
        return unknown(check, "network checks are disabled; pass --allow-network for a trusted specification")

    def evaluate():
        timeout = float(check.get("timeout_seconds", 3.0))
        request = urllib.request.Request(check["url"], method="GET", headers={"User-Agent": "worldstate-check/0.1"})
        evidence: dict[str, Any] = {"url": check["url"]}
        try:
            response = urllib.request.urlopen(request, timeout=timeout)
            status = response.status
            body_bytes = response.read(1_048_577)
        except urllib.error.HTTPError as exc:
            status = exc.code
            body_bytes = exc.read(1_048_577)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return CheckStatus.FAIL, "HTTP endpoint could not be reached", None, None, evidence, str(exc)

        if len(body_bytes) > 1_048_576:
            return CheckStatus.UNKNOWN, "HTTP response exceeds 1 MiB evidence limit", None, status, evidence, None
        body = body_bytes.decode("utf-8", errors="replace")
        observed: dict[str, Any] = {"status": status}
        expected: dict[str, Any] = {}
        failures: list[str] = []

        if "status" in check:
            expected["status"] = check["status"]
            if status != check["status"]:
                failures.append(f"status={status}")
        if "text_contains" in check:
            expected["text_contains"] = check["text_contains"]
            matched = check["text_contains"] in body
            observed["text_contains"] = matched
            if not matched:
                failures.append("required response text missing")
        if "json_field" in check:
            try:
                payload = json.loads(body)
                value = extract_dotted(payload, check["json_field"])
                matched, expected_value = compare_value(value, check["operator"], check)
            except (json.JSONDecodeError, KeyError, ValueError, SpecError) as exc:
                return CheckStatus.UNKNOWN, "HTTP JSON assertion could not be evaluated", expected, observed, evidence, str(exc)
            expected["json"] = {"field": check["json_field"], "value": expected_value, "operator": check["operator"]}
            observed["json"] = {"field": check["json_field"], "value": value}
            if not matched:
                failures.append("JSON response postcondition not satisfied")

        evidence["body_bytes"] = len(body_bytes)
        if failures:
            return CheckStatus.FAIL, "; ".join(failures), expected, observed, evidence, None
        return CheckStatus.PASS, "HTTP postcondition satisfied", expected, observed, evidence, None

    return timed_result(check, evaluate)
