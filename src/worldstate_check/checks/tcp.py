from __future__ import annotations

import socket
from typing import Any

from worldstate_check.models import CheckStatus, VerificationContext

from .base import timed_result, unknown


def run_tcp_check(check: dict[str, Any], ctx: VerificationContext):
    if not ctx.allow_network:
        return unknown(check, "network checks are disabled; pass --allow-network for a trusted specification")

    def evaluate():
        expected = check.get("reachable", True)
        timeout = float(check.get("timeout_seconds", 2.0))
        evidence = {"host": check["host"], "port": check["port"]}
        try:
            with socket.create_connection((check["host"], check["port"]), timeout=timeout):
                reachable = True
        except OSError as exc:
            reachable = False
            evidence["connection_error"] = exc.__class__.__name__
        status = CheckStatus.PASS if reachable == expected else CheckStatus.FAIL
        summary = "TCP postcondition satisfied" if status is CheckStatus.PASS else "TCP postcondition not satisfied"
        return status, summary, expected, reachable, evidence, None

    return timed_result(check, evaluate)
