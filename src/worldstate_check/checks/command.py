from __future__ import annotations

import os
import subprocess
from typing import Any

from worldstate_check.errors import PathBoundaryError
from worldstate_check.models import CheckStatus, VerificationContext
from worldstate_check.util import resolve_path

from .base import timed_result, unknown


def run_command_check(check: dict[str, Any], ctx: VerificationContext):
    if not ctx.allow_command:
        return unknown(check, "command checks are disabled; pass --allow-command for a trusted specification")
    try:
        cwd = resolve_path(ctx.root, check.get("cwd", "."), ctx.allow_outside_root)
    except PathBoundaryError as exc:
        return unknown(check, str(exc))

    def evaluate():
        max_bytes = check.get("max_output_bytes", 65_536)
        timeout = float(check.get("timeout_seconds", 10.0))
        env = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "")}
        try:
            proc = subprocess.run(
                check["argv"],
                cwd=cwd,
                env=env,
                capture_output=True,
                text=False,
                shell=False,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return CheckStatus.FAIL, "verification command timed out", {"timeout_seconds": timeout}, None, {"cwd": str(cwd)}, None
        except (OSError, ValueError) as exc:
            return CheckStatus.UNKNOWN, "verification command could not be started", None, None, {"cwd": str(cwd)}, str(exc)

        stdout_bytes = proc.stdout[: max_bytes + 1]
        stderr_bytes = proc.stderr[: max_bytes + 1]
        if len(stdout_bytes) > max_bytes or len(stderr_bytes) > max_bytes:
            return (
                CheckStatus.UNKNOWN,
                "verification command output exceeds configured evidence limit",
                None,
                {"exit_code": proc.returncode},
                {"cwd": str(cwd), "max_output_bytes": max_bytes},
                None,
            )
        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        expected: dict[str, Any] = {}
        observed: dict[str, Any] = {"exit_code": proc.returncode}
        failures: list[str] = []
        if "exit_code" in check:
            expected["exit_code"] = check["exit_code"]
            if proc.returncode != check["exit_code"]:
                failures.append(f"exit_code={proc.returncode}")
        if "stdout_contains" in check:
            expected["stdout_contains"] = check["stdout_contains"]
            matched = check["stdout_contains"] in stdout
            observed["stdout_contains"] = matched
            if not matched:
                failures.append("required stdout text missing")
        if "stderr_contains" in check:
            expected["stderr_contains"] = check["stderr_contains"]
            matched = check["stderr_contains"] in stderr
            observed["stderr_contains"] = matched
            if not matched:
                failures.append("required stderr text missing")

        evidence = {
            "argv": check["argv"],
            "cwd": str(cwd),
            "stdout_excerpt": stdout[-2000:],
            "stderr_excerpt": stderr[-2000:],
        }
        if failures:
            return CheckStatus.FAIL, "; ".join(failures), expected, observed, evidence, None
        return CheckStatus.PASS, "command postcondition satisfied", expected, observed, evidence, None

    return timed_result(check, evaluate)
