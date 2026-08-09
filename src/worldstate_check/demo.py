from __future__ import annotations

import json
import tempfile
from pathlib import Path

from .engine import verify
from .models import VerificationContext, Verdict
from .report import render_text


def run_demo(scenario: str = "partial") -> Verdict:
    if scenario not in {"verified", "partial"}:
        raise ValueError("scenario must be verified or partial")
    with tempfile.TemporaryDirectory(prefix="worldstate-check-") as raw:
        root = Path(raw)
        (root / "command-ack.txt").write_text("SAFE_MODE_ACK\n", encoding="utf-8")
        attitude = 1.8 if scenario == "verified" else 14.7
        telemetry = {
            "mode": "SAFE",
            "payload": {"power": "off"},
            "attitude": {"error_deg": attitude},
            "battery": {"soc": 71.0},
        }
        (root / "telemetry.json").write_text(json.dumps(telemetry), encoding="utf-8")
        spec = {
            "version": 1,
            "task": "enter-safe-mode",
            "checks": [
                {"id": "command-ack", "type": "file", "path": "command-ack.txt", "contains": "SAFE_MODE_ACK"},
                {"id": "payload-power", "type": "json", "path": "telemetry.json", "field": "payload.power", "operator": "eq", "value": "off"},
                {
                    "id": "attitude-error",
                    "type": "metric",
                    "source": {"type": "json", "path": "telemetry.json", "field": "attitude.error_deg"},
                    "operator": "lte",
                    "value": 3.0,
                },
                {
                    "id": "battery-soc",
                    "type": "metric",
                    "source": {"type": "json", "path": "telemetry.json", "field": "battery.soc"},
                    "operator": "gte",
                    "value": 25.0,
                },
            ],
        }
        report = verify(spec, VerificationContext(spec_path=root / "demo.yaml", root=root))
        print(render_text(report))
        return report.verdict
