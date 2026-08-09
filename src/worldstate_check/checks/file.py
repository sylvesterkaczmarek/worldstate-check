from __future__ import annotations

import hashlib
from typing import Any

from worldstate_check.errors import PathBoundaryError
from worldstate_check.models import CheckStatus, VerificationContext
from worldstate_check.util import resolve_path

from .base import timed_result, unknown


def run_file_check(check: dict[str, Any], ctx: VerificationContext):
    try:
        path = resolve_path(ctx.root, check["path"], ctx.allow_outside_root)
    except PathBoundaryError as exc:
        return unknown(check, str(exc))

    def evaluate():
        exists = path.exists()
        expected: dict[str, Any] = {}
        observed: dict[str, Any] = {"exists": exists}
        evidence: dict[str, Any] = {"path": str(path)}
        failures: list[str] = []

        if "exists" in check:
            expected["exists"] = check["exists"]
            if exists != check["exists"]:
                failures.append(f"exists={exists}")

        content: str | None = None
        if any(k in check for k in {"contains", "not_contains"}):
            if not exists or not path.is_file():
                failures.append("file content unavailable")
            else:
                max_bytes = check.get("max_read_bytes", 1_048_576)
                size = path.stat().st_size
                evidence["size_bytes"] = size
                if size > max_bytes:
                    return (
                        CheckStatus.UNKNOWN,
                        f"file exceeds max_read_bytes ({size} > {max_bytes})",
                        expected,
                        observed,
                        evidence,
                        "file too large for configured text assertion",
                    )
                try:
                    content = path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError) as exc:
                    return CheckStatus.UNKNOWN, "could not read file as UTF-8", expected, observed, evidence, str(exc)

        if "contains" in check:
            expected["contains"] = check["contains"]
            matched = content is not None and check["contains"] in content
            observed["contains"] = matched
            if not matched:
                failures.append("required text missing")

        if "not_contains" in check:
            expected["not_contains"] = check["not_contains"]
            matched = content is not None and check["not_contains"] not in content
            observed["not_contains"] = matched
            if not matched:
                failures.append("forbidden text present")

        if "sha256" in check:
            expected["sha256"] = check["sha256"].lower()
            if not exists or not path.is_file():
                failures.append("sha256 unavailable")
            else:
                digest = hashlib.sha256()
                try:
                    with path.open("rb") as handle:
                        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                            digest.update(chunk)
                except OSError as exc:
                    return CheckStatus.UNKNOWN, "could not hash file", expected, observed, evidence, str(exc)
                observed["sha256"] = digest.hexdigest()
                if observed["sha256"] != expected["sha256"]:
                    failures.append("sha256 mismatch")

        if failures:
            return CheckStatus.FAIL, "; ".join(failures), expected, observed, evidence, None
        return CheckStatus.PASS, "file postcondition satisfied", expected, observed, evidence, None

    return timed_result(check, evaluate)
