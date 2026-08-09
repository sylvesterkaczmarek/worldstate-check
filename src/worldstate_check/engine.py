from __future__ import annotations

import math
import time
from datetime import datetime, timezone
from typing import Any

from .checks import CHECK_RUNNERS
from .loader import validate_spec
from .models import CheckResult, CheckStatus, VerificationContext, VerificationReport, Verdict


def evaluate_once(spec: dict[str, Any], ctx: VerificationContext) -> list[CheckResult]:
    results: list[CheckResult] = []
    for check in spec["checks"]:
        runner = CHECK_RUNNERS[check["type"]]
        results.append(runner(check, ctx))
    return results


def derive_verdict(results: list[CheckResult]) -> Verdict:
    required = [r for r in results if r.required]
    if any(r.status is CheckStatus.FAIL for r in required):
        return Verdict.NOT_VERIFIED
    if any(r.status is CheckStatus.UNKNOWN for r in required):
        return Verdict.UNCERTAIN
    return Verdict.VERIFIED


def verify(
    spec: dict[str, Any],
    ctx: VerificationContext,
    *,
    wait_seconds: float = 0.0,
    poll_interval: float = 0.5,
) -> VerificationReport:
    validate_spec(spec)
    if isinstance(wait_seconds, bool) or not isinstance(wait_seconds, (int, float)) or not math.isfinite(float(wait_seconds)) or wait_seconds < 0:
        raise ValueError("wait_seconds must be a finite non-negative number")
    if isinstance(poll_interval, bool) or not isinstance(poll_interval, (int, float)) or not math.isfinite(float(poll_interval)) or poll_interval <= 0:
        raise ValueError("poll_interval must be a finite positive number")

    started_wall = datetime.now(timezone.utc)
    started_perf = time.perf_counter()
    deadline = started_perf + wait_seconds
    attempts = 0
    results: list[CheckResult] = []

    while True:
        attempts += 1
        results = evaluate_once(spec, ctx)
        verdict = derive_verdict(results)
        if verdict is Verdict.VERIFIED:
            break
        now = time.perf_counter()
        if wait_seconds <= 0 or now >= deadline:
            break
        time.sleep(min(poll_interval, max(0.0, deadline - now)))

    finished_wall = datetime.now(timezone.utc)
    return VerificationReport(
        schema_version=1,
        task=spec["task"],
        verdict=derive_verdict(results),
        started_at=started_wall.isoformat().replace("+00:00", "Z"),
        finished_at=finished_wall.isoformat().replace("+00:00", "Z"),
        duration_ms=(time.perf_counter() - started_perf) * 1000,
        attempts=attempts,
        results=results,
    )
