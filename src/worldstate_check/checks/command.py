from __future__ import annotations

import hashlib
import os
from typing import Any

from worldstate_check.errors import PathBoundaryError
from worldstate_check.models import CheckStatus, VerificationContext
from worldstate_check.util import resolve_path

from .base import timed_result, unknown
from worldstate_check.processes import run_bounded


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
        # Preserve essential Windows process environment without inheriting credentials.
        for name in ('SystemRoot', 'WINDIR', 'COMSPEC', 'PATHEXT', 'TEMP', 'TMP'):
            if os.name == 'nt' and name in os.environ:
                env[name] = os.environ[name]
        try:
            proc = run_bounded(check['argv'], cwd=cwd, env=env, timeout=timeout, max_bytes=max_bytes)
        except (OSError, ValueError) as exc:
            return CheckStatus.UNKNOWN, "verification command could not be started", None, None, {"cwd": str(cwd)}, type(exc).__name__
        if proc.timed_out:
            return CheckStatus.FAIL, "verification command timed out", {"timeout_seconds": timeout}, None, {"cwd": str(cwd)}, None
        if proc.output_limited:
            return CheckStatus.UNKNOWN, "verification command output exceeds configured evidence limit", None, None, {
                "cwd": str(cwd), "max_output_bytes": max_bytes, "stdout_bytes": proc.stdout_bytes,
                "stderr_bytes": proc.stderr_bytes, "output_limited": True}, None
        stdout_bytes, stderr_bytes = proc.stdout, proc.stderr
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
            "cwd": str(cwd),
            "argv_count": len(check["argv"]),
            "stdout_bytes": len(proc.stdout),
            "stderr_bytes": len(proc.stderr),
            "stdout_sha256": hashlib.sha256(proc.stdout).hexdigest(),
            "stderr_sha256": hashlib.sha256(proc.stderr).hexdigest(),
        }
        if proc.cleanup_error is not None:
            evidence['cleanup_error'] = proc.cleanup_error
        if failures:
            return CheckStatus.FAIL, "; ".join(failures), expected, observed, evidence, None
        if proc.cleanup_error is not None:
            return CheckStatus.UNKNOWN, "verification command cleanup could not be confirmed", expected, observed, evidence, proc.cleanup_error
        return CheckStatus.PASS, "command postcondition satisfied", expected, observed, evidence, None

    return timed_result(check, evaluate)
