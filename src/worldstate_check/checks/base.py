from __future__ import annotations

import time
from typing import Any, Callable

from worldstate_check.models import CheckResult, CheckStatus, VerificationContext


def timed_result(
    check: dict[str, Any],
    fn: Callable[[], tuple[CheckStatus, str, Any, Any, dict[str, Any], str | None]],
) -> CheckResult:
    started = time.perf_counter()
    status, summary, expected, observed, evidence, error = fn()
    return CheckResult(
        check_id=check["id"],
        check_type=check["type"],
        required=check.get("required", True),
        status=status,
        summary=summary,
        expected=expected,
        observed=observed,
        evidence=evidence,
        error=error,
        duration_ms=(time.perf_counter() - started) * 1000,
    )


def unknown(check: dict[str, Any], message: str, *, evidence: dict[str, Any] | None = None) -> CheckResult:
    return CheckResult(
        check_id=check["id"],
        check_type=check["type"],
        required=check.get("required", True),
        status=CheckStatus.UNKNOWN,
        summary=message,
        evidence=evidence or {},
        error=message,
    )
