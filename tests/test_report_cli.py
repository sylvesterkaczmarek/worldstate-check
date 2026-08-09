import json
from pathlib import Path

from worldstate_check.cli import main
from worldstate_check.models import CheckResult, CheckStatus, VerificationReport, Verdict
from worldstate_check.report import report_payload, verify_json_report, write_json_report


def sample_report():
    return VerificationReport(1, "x", Verdict.VERIFIED, "2026-01-01T00:00:00Z", "2026-01-01T00:00:01Z", 1000.0, 1, [
        CheckResult("a", "file", True, CheckStatus.PASS, "ok")
    ])


def test_report_has_digest(tmp_path):
    payload = report_payload(sample_report())
    assert len(payload["report_sha256"]) == 64
    path = write_json_report(sample_report(), tmp_path / "r.json")
    saved = json.loads(path.read_text())
    assert saved["verdict"] == "VERIFIED"
    assert verify_json_report(path)


def test_report_digest_detects_change(tmp_path):
    path = write_json_report(sample_report(), tmp_path / "r.json")
    data = json.loads(path.read_text())
    data["verdict"] = "NOT_VERIFIED"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert not verify_json_report(path)


def test_cli_validate(tmp_path, capsys):
    spec = tmp_path / "s.yaml"
    spec.write_text("version: 1\ntask: x\nchecks:\n  - id: f\n    type: file\n    path: missing\n    exists: false\n", encoding="utf-8")
    assert main(["validate", str(spec)]) == 0
    assert "VALID" in capsys.readouterr().out


def test_cli_verify_exit_code(tmp_path):
    spec = tmp_path / "s.yaml"
    spec.write_text("version: 1\ntask: x\nchecks:\n  - id: f\n    type: file\n    path: missing\n    exists: true\n", encoding="utf-8")
    assert main(["verify", str(spec)]) == 1


def test_cli_init_refuses_overwrite(tmp_path):
    target = tmp_path / "x.yaml"
    assert main(["init", str(target)]) == 0
    assert main(["init", str(target)]) == 2


def test_cli_verify_report(tmp_path):
    path = write_json_report(sample_report(), tmp_path / "r.json")
    assert main(["verify-report", str(path)]) == 0


def test_demo_verified_exit_code():
    assert main(["demo", "--scenario", "verified"]) == 0


def test_demo_partial_exit_code():
    assert main(["demo", "--scenario", "partial"]) == 1
