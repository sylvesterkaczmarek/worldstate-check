"""Offline, versioned reproduction of verdicts from recorded acquisition data."""

from __future__ import annotations

import hashlib
import math
from dataclasses import replace
from importlib.metadata import version
from pathlib import Path

from .journal import CaptureBudget, Frame, MAX_BUNDLE_BYTES, ReplayError
from .loader import validate_spec
from .models import REPORT_SCHEMA, VerificationContext, VerificationReport, Verdict
from .observations import local_input
from .report import validate_report_data, validate_report_destination, write_atomic_text
from .util import (
    canonical_json,
    parse_timestamp,
    read_text_limited,
    strict_json_loads,
    utc_now_iso,
    validate_json_tree,
)

FORMAT = "worldstate-check/observations/1"
EVALUATOR = 2


def fingerprint(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def decisions(results):
    return [
        [result.check_id, result.status.value, result.reason_code] for result in results
    ]


class Recorder:
    def __init__(self, destination, spec, ctx):
        self.protected = [ctx.spec_path]
        for check in spec["checks"]:
            item = local_input(check)
            if item:
                self.protected.append(ctx.root / Path(item[0]).expanduser())
        self.destination = validate_report_destination(destination, self.protected)
        self.budget = CaptureBudget()
        self.frames = []
        self.document = {
            "format": FORMAT,
            "evaluator": EVALUATOR,
            "package_version": version("worldstate-check"),
            "specification": spec,
            "specification_sha256": fingerprint(spec),
            "permissions": {
                key: getattr(ctx, key)
                for key in ("allow_command", "allow_network", "allow_outside_root")
            },
            "attempts": self.frames,
        }
        self.budget.charge(self.document)

    def start(self):
        attempt = {"events": [], "observed_at": utc_now_iso()}
        self.frames.append(attempt)
        return Frame(attempt["events"], budget=self.budget)

    def finish_attempt(self, results):
        values = decisions(results)
        self.budget.charge(values)
        self.frames[-1]["decisions"] = values

    def save(self, report):
        self.document.update(
            started_at=report.started_at,
            finished_at=report.finished_at,
            duration_ms=report.duration_ms,
            verdict=report.verdict.value,
        )
        self.document["sha256"] = fingerprint(self.document)
        validate_json_tree(self.document, max_nodes=3_000_000, max_depth=96)
        content = canonical_json(self.document) + "\n"
        if len(content.encode("utf-8")) > MAX_BUNDLE_BYTES:
            raise ValueError("recording exceeds the 64 MiB bundle limit")
        write_atomic_text(self.destination, content, protected=self.protected)


def replay_data(data) -> VerificationReport:
    """Re-evaluate all recorded attempts without consulting the original resources."""
    from .engine import derive_verdict, evaluate_once

    try:
        if (
            data["format"] != FORMAT
            or type(data["evaluator"]) is not int
            or data["evaluator"] not in (1, EVALUATOR)
        ):
            raise ReplayError("unsupported recording format or evaluator")
        payload = dict(data)
        if payload.pop("sha256") != fingerprint(payload):
            raise ReplayError("recording checksum mismatch")
        if (
            not isinstance(data["package_version"], str)
            or not data["package_version"].strip()
        ):
            raise ReplayError("invalid package version")
        if (
            type(data["duration_ms"]) not in (int, float)
            or not math.isfinite(data["duration_ms"])
            or data["duration_ms"] < 0
        ):
            raise ReplayError("invalid recording duration")
        spec = data["specification"]
        validate_spec(spec)
        if data["specification_sha256"] != fingerprint(spec):
            raise ReplayError("recording specification hash mismatch")
        flags = data["permissions"]
        if set(flags) != {"allow_command", "allow_network", "allow_outside_root"}:
            raise ReplayError("invalid recording permission metadata")
        # Used solely to reproduce path labels. All acquisitions are served by Frame.
        root = Path.cwd().anchor
        ctx = VerificationContext(spec_path=Path(root), root=Path(root), **flags)
        attempts = data["attempts"]
        if not isinstance(attempts, list) or not attempts:
            raise ReplayError("recording has no attempts")
        for index, attempt in enumerate(attempts, 1):
            parse_timestamp(attempt["observed_at"])
            events = attempt["events"]
            if not isinstance(events, list):
                raise ReplayError("invalid attempt events")
            frame = Frame(events, replay=True, legacy_window_identity=data["evaluator"] == 1)
            results = evaluate_once(spec, replace(ctx, _frame=frame))
            verdict = derive_verdict(results)
            if (
                frame.position != len(events)
                or decisions(results) != attempt["decisions"]
            ):
                raise ReplayError(
                    f"replayed evidence disagrees with recorded attempt {index}"
                )
            if verdict is Verdict.VERIFIED and index < len(attempts):
                raise ReplayError("unexpected attempts after verification")
        if data["verdict"] != verdict.value:
            raise ReplayError("replayed verdict disagrees with the recording")
        if parse_timestamp(data["finished_at"]) < parse_timestamp(data["started_at"]):
            raise ReplayError("invalid recording timestamps")
        report = VerificationReport(
            REPORT_SCHEMA,
            spec["task"],
            verdict,
            data["started_at"],
            data["finished_at"],
            data["duration_ms"],
            len(attempts),
            results,
            fingerprint(spec),
        )
        validate_report_data(report.to_dict())
        return report
    except (KeyError, TypeError, AttributeError, IndexError, OverflowError) as exc:
        raise ReplayError("invalid recording structure") from exc


def replay_bundle(path: str | Path) -> VerificationReport:
    raw = read_text_limited(Path(path), MAX_BUNDLE_BYTES)
    return replay_data(strict_json_loads(raw, max_nodes=3_000_000, max_depth=96))
