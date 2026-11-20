from __future__ import annotations

import hashlib
import re
import urllib.error
import urllib.request
from contextlib import closing
from http.client import HTTPException, IncompleteRead
from typing import Any
from urllib.parse import urljoin, urldefrag

from worldstate_check.journal import sample
from worldstate_check.util import MISSING, field_value, utc_now_iso

from worldstate_check.errors import SpecError
from worldstate_check.models import CheckStatus, VerificationContext
from worldstate_check.util import compare_value, redact_url_for_evidence, strict_json_loads

from .base import timed_result, unknown



def _declared_body_length(response):
    """Validate HTTP/1.1 framing before partial bytes can satisfy an assertion.

    RFC 9112 sections 6.3 and 8 require incomplete length-delimited messages to
    be treated as incomplete. read(amt) alone does not enforce that condition.
    """
    if response.status in (204, 304) or 100 <= response.status < 200:
        return 0
    headers = getattr(response, 'headers', None)
    if headers is None:
        return None
    def values(name):
        if hasattr(headers, 'get_all'):
            return headers.get_all(name, [])
        return [value for key, value in headers.items() if key.lower() == name.lower()]
    lengths = values('Content-Length')
    encodings = values('Transfer-Encoding')
    if encodings:
        codes = [part.strip().lower() for value in encodings for part in value.split(',')]
        if lengths or codes != ['chunked']:
            raise ValueError('ambiguous or unsupported HTTP transfer framing')
        # http.client verifies chunk boundaries and the terminating chunk.
        return None
    if not lengths:
        return None  # Connection-close delimited response.
    tokens = [part.strip() for value in lengths for part in value.split(',')]
    if any(re.fullmatch(r'[0-9]+', token) is None for token in tokens):
        raise ValueError('invalid HTTP content length')
    values = [int(token) for token in tokens]
    if len(set(values)) != 1:
        raise ValueError('conflicting HTTP content lengths')
    return values[0]

class _RedirectPolicy(urllib.request.HTTPRedirectHandler):
    def __init__(self, destination):
        self.destination = destination

    def redirect_request(self, request, fp, code, msg, headers, newurl):
        if newurl != self.destination:
            return None
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def _open_response(request, *, timeout, redirect_to):
    opener = urllib.request.build_opener(_RedirectPolicy(redirect_to))
    return opener.open(request, timeout=timeout)


def _capture_http(check):
    url = check["url"]
    record = {"observed_at": utc_now_iso(), "effective_url": None, "redirect_target": None,
              "redirected": False, "status": None, "body": None, "error": None}
    try:
        request = urllib.request.Request(url, method="GET", headers={"User-Agent": "worldstate-check"})
        try:
            response = _open_response(request, timeout=check.get("timeout_seconds", 3.0),
                                      redirect_to=check.get("redirect_to"))
        except urllib.error.HTTPError as exc:
            response = exc
        with closing(response):
            effective = response.geturl() if hasattr(response, "geturl") else url
            record["effective_url"] = redact_url_for_evidence(effective)
            record["redirected"] = urldefrag(effective).url != urldefrag(url).url
            record["status"] = response.status
            headers = getattr(response, "headers", None)
            location = headers.get("Location") if headers else None
            if location and response.status in (301, 302, 303, 307, 308):
                record["redirect_target"] = redact_url_for_evidence(urljoin(effective, location))
            declared = _declared_body_length(response)
            body = response.read(1_048_577)
            if declared is not None and len(body) < min(declared, 1_048_577):
                raise IncompleteRead(body, declared - len(body))
            record["body"] = body
    except (OverflowError, urllib.error.URLError, OSError, HTTPException, ValueError) as exc:
        record["error"] = type(exc).__name__
    return record


def run_http_check(check: dict[str, Any], ctx: VerificationContext):
    if not ctx.allow_network:
        return unknown(check, "network checks are disabled; pass --allow-network for a trusted specification")

    def evaluate():
        key = (urldefrag(check["url"]).url, check.get("sample"))
        session = ctx._session
        if session is not None and key in session.http:
            record = session.http[key]
        else:
            record = sample(ctx, "http", check["id"], lambda: _capture_http(check))
            if session is not None:
                body = record["body"]
                if body is not None:
                    if len(body) > session.remaining_bytes:
                        record = {**record, "error": "ObservationBudget", "body": None}
                    else:
                        session.retained_bytes += len(body)
                session.http[key] = record

        evidence = {"url": redact_url_for_evidence(check["url"])}
        for field in ("observed_at", "effective_url", "redirect_target", "redirected"):
            evidence[field] = record[field]
        if record["error"] is not None:
            if record["error"] in {"ObservationBudget", "OverflowError"}:
                return CheckStatus.UNKNOWN, "HTTP observation limit exceeded", None, None, evidence, record["error"]
            return CheckStatus.FAIL, "HTTP request or response could not be completed", None, None, evidence, record["error"]
        body_bytes = record["body"]
        status = record["status"]
        if len(body_bytes) <= 1_048_576:
            evidence["source_sha256"] = hashlib.sha256(body_bytes).hexdigest()

        observed: dict[str, Any] = {"status": status}
        expected: dict[str, Any] = {}
        failures: list[str] = []

        if record["redirect_target"] is not None and check.get("status") != status:
            failures.append("redirect destination was not authorised")
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
                value = field_value(payload, check["json_field"])
                evidence["field_present"] = value is not MISSING
                matched, expected_value = compare_value(value, check["operator"], check)
            except (KeyError, ValueError, SpecError, RecursionError):
                # Do not let an unevaluable assertion hide an already observed
                # failure, or echo arbitrary response data through parser errors.
                summary = "; ".join([*failures, "HTTP JSON assertion could not be evaluated"])
                result_status = CheckStatus.FAIL if failures else CheckStatus.UNKNOWN
                return result_status, summary, expected, observed, evidence, error_context
            if check["operator"] == "exists":
                value = value is not MISSING
            expected["json"] = {"field": check["json_field"], "value": expected_value, "operator": check["operator"]}
            observed["json"] = {"field": check["json_field"], "value": value}
            if not matched:
                failures.append("JSON response postcondition not satisfied")

        evidence["body_bytes"] = len(body_bytes)
        if failures:
            return CheckStatus.FAIL, "; ".join(failures), expected, observed, evidence, None
        return CheckStatus.PASS, "HTTP postcondition satisfied", expected, observed, evidence, None

    return timed_result(check, evaluate)
