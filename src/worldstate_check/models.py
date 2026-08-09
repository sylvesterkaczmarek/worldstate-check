from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class CheckStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


class Verdict(str, Enum):
    VERIFIED = "VERIFIED"
    NOT_VERIFIED = "NOT_VERIFIED"
    UNCERTAIN = "UNCERTAIN"


@dataclass(frozen=True)
class CheckResult:
    check_id: str
    check_type: str
    required: bool
    status: CheckStatus
    summary: str
    expected: Any = None
    observed: Any = None
    evidence: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


@dataclass(frozen=True)
class VerificationContext:
    spec_path: Path
    root: Path
    allow_outside_root: bool = False
    allow_command: bool = False
    allow_network: bool = False


@dataclass(frozen=True)
class VerificationReport:
    schema_version: int
    task: str
    verdict: Verdict
    started_at: str
    finished_at: str
    duration_ms: float
    attempts: int
    results: list[CheckResult]

    @property
    def required_passed(self) -> int:
        return sum(r.required and r.status is CheckStatus.PASS for r in self.results)

    @property
    def required_total(self) -> int:
        return sum(r.required for r in self.results)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "task": self.task,
            "verdict": self.verdict.value,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": round(self.duration_ms, 3),
            "attempts": self.attempts,
            "required_passed": self.required_passed,
            "required_total": self.required_total,
            "results": [r.to_dict() for r in self.results],
        }
