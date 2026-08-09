from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .models import CheckStatus, VerificationReport
from .util import canonical_json, read_text_limited, strict_json_loads


def report_payload(report: VerificationReport) -> dict[str, Any]:
    payload = report.to_dict()
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    payload["report_sha256"] = digest
    return payload


def verify_json_report(path: Path) -> bool:
    data = strict_json_loads(read_text_limited(path, 16 * 1024 * 1024))
    if not isinstance(data, dict):
        return False
    claimed = data.pop("report_sha256", None)
    if not isinstance(claimed, str) or len(claimed) != 64:
        return False
    actual = hashlib.sha256(canonical_json(data).encode("utf-8")).hexdigest()
    return actual == claimed


def write_json_report(report: VerificationReport, path: Path) -> Path:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report_payload(report), indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return path


def render_text(report: VerificationReport) -> str:
    lines = [f"WorldState Check: {report.task}", ""]
    for result in report.results:
        marker = {
            CheckStatus.PASS: "PASS",
            CheckStatus.FAIL: "FAIL",
            CheckStatus.UNKNOWN: "UNKNOWN",
        }[result.status]
        requirement = "required" if result.required else "optional"
        lines.append(f"[{marker:<7}] {result.check_id} ({result.check_type}, {requirement})")
        lines.append(f"          {result.summary}")
        if result.status is not CheckStatus.PASS and result.observed is not None:
            lines.append(
                f"          observed: {json.dumps(result.observed, ensure_ascii=False, sort_keys=True, allow_nan=False)}"
            )
        if result.status is not CheckStatus.PASS and result.expected is not None:
            lines.append(
                f"          expected: {json.dumps(result.expected, ensure_ascii=False, sort_keys=True, allow_nan=False)}"
            )
    lines.extend(
        [
            "",
            f"VERDICT: {report.verdict.value}",
            f"Required checks: {report.required_passed}/{report.required_total} passed",
            f"Attempts: {report.attempts}",
        ]
    )
    return "\n".join(lines)
