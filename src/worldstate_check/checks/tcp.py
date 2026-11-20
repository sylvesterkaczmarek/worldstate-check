from __future__ import annotations

import socket
from typing import Any

from worldstate_check.journal import sample
from worldstate_check.models import CheckStatus, VerificationContext

from .base import timed_result, unknown


def run_tcp_check(check: dict[str, Any], ctx: VerificationContext):
    if not ctx.allow_network:
        return unknown(check, "network checks are disabled; pass --allow-network for a trusted specification")

    def evaluate():
        expected = check.get("reachable", True)
        timeout = float(check.get("timeout_seconds", 2.0))
        evidence = {"host": check["host"], "port": check["port"]}
        def connect():
            try:
                with socket.create_connection((check["host"], check["port"]), timeout=timeout):
                    return {"reachable": True, "error": None}
            except ConnectionRefusedError as exc:
                return {"reachable": False, "error": type(exc).__name__}
            except (OSError, OverflowError, ValueError) as exc:
                return {"reachable": None, "error": type(exc).__name__}

        record = sample(ctx, "tcp", check["id"], connect)
        reachable = record["reachable"]
        if record["error"] is not None:
            evidence["connection_error"] = record["error"]
        if reachable is None:
            return CheckStatus.UNKNOWN, "TCP reachability could not be established", expected, None, evidence, record["error"]
        status = CheckStatus.PASS if reachable == expected else CheckStatus.FAIL
        summary = "TCP postcondition satisfied" if status is CheckStatus.PASS else "TCP postcondition not satisfied"
        return status, summary, expected, reachable, evidence, None

    return timed_result(check, evaluate)
