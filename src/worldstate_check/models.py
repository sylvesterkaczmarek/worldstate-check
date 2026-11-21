from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
from enum import Enum

from .util import canonical_json
from pathlib import Path
from typing import Any


REPORT_SCHEMA = 2


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

    @property
    def reason_code(self) -> str:
        if self.status is CheckStatus.PASS:
            return "satisfied"
        if self.evidence.get("age_seconds", 0) > self.evidence.get("max_age_seconds", float("inf")):
            return "stale"
        if self.status is CheckStatus.UNKNOWN and self.evidence.get("window_errors"):
            return "incomplete_window"
        if self.evidence.get("field_present") is False:
            return "field_missing"
        if self.status is CheckStatus.UNKNOWN:
            return "inconclusive"
        return "postcondition_failed"

    def to_dict(self, *, inline_bytes: int = 4096, schema: int = REPORT_SCHEMA) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        if schema == 1:
            return data
        data["reason_code"] = self.reason_code
        references = {}
        for name in ("expected", "observed", "evidence", "summary", "error"):
            value = data[name]
            raw = canonical_json(value).encode("utf-8")
            if len(raw) <= inline_bytes:
                continue
            references[name] = {"encoding": "canonical-json-utf8", "type": type(value).__name__,
                                "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            if name in ("summary", "error"):
                data[name] = "(see value reference)"
            elif name == "evidence":
                data[name] = {}
            else:
                data[name] = None
        if references:
            data["evidence"]["value_references"] = references
        return data


@dataclass(frozen=True)
class VerificationContext:
    spec_path: Path
    root: Path
    allow_outside_root: bool = False
    allow_command: bool = False
    allow_network: bool = False
    _frame: Any = field(default=None, repr=False, compare=False)
    _session: Any = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        for name in ('allow_outside_root', 'allow_command', 'allow_network'):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f'{name} must be a boolean; permission requires explicit True')


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
    specification_sha256: str | None = None

    @property
    def required_passed(self) -> int:
        return sum(r.required and r.status is CheckStatus.PASS for r in self.results)

    @property
    def inline_value_bytes(self) -> int:
        return min(4096, 1_000_000 // max(1, len(self.results)))

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
            "results": [r.to_dict(schema=self.schema_version, inline_bytes=self.inline_value_bytes)
                        for r in self.results],
            "specification_sha256": self.specification_sha256,
        }
