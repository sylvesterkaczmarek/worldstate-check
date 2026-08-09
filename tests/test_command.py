import sys

from worldstate_check.checks.command import run_command_check
from worldstate_check.models import CheckStatus, VerificationContext


def test_command_disabled_by_default(tmp_path):
    ctx = VerificationContext(spec_path=tmp_path / "s", root=tmp_path)
    check = {"id": "c", "type": "command", "argv": [sys.executable, "-c", "print('OK')"], "exit_code": 0}
    assert run_command_check(check, ctx).status is CheckStatus.UNKNOWN


def test_command_runs_when_enabled(tmp_path):
    ctx = VerificationContext(spec_path=tmp_path / "s", root=tmp_path, allow_command=True)
    check = {"id": "c", "type": "command", "argv": [sys.executable, "-c", "print('OK')"], "exit_code": 0, "stdout_contains": "OK"}
    assert run_command_check(check, ctx).status is CheckStatus.PASS


def test_command_failure_is_reported(tmp_path):
    ctx = VerificationContext(spec_path=tmp_path / "s", root=tmp_path, allow_command=True)
    check = {"id": "c", "type": "command", "argv": [sys.executable, "-c", "raise SystemExit(4)"], "exit_code": 0}
    result = run_command_check(check, ctx)
    assert result.status is CheckStatus.FAIL
    assert result.observed["exit_code"] == 4


def test_command_output_limit_is_enforced(tmp_path):
    ctx = VerificationContext(spec_path=tmp_path / "s", root=tmp_path, allow_command=True)
    check = {
        "id": "c",
        "type": "command",
        "argv": [sys.executable, "-c", "print('x' * 50000)"],
        "exit_code": 0,
        "max_output_bytes": 1024,
    }
    result = run_command_check(check, ctx)
    assert result.status is CheckStatus.UNKNOWN
    assert "output exceeds" in result.summary


def test_command_report_does_not_copy_raw_arguments_or_output(tmp_path):
    ctx = VerificationContext(spec_path=tmp_path / "s", root=tmp_path, allow_command=True)
    check = {
        "id": "c",
        "type": "command",
        "argv": [sys.executable, "-c", "print('SECRET_OUTPUT')", "SECRET_ARGUMENT"],
        "exit_code": 0,
        "stdout_contains": "SECRET_OUTPUT",
    }
    result = run_command_check(check, ctx)
    assert result.status is CheckStatus.PASS
    serialized = repr(result.evidence)
    assert "SECRET_ARGUMENT" not in serialized
    assert "SECRET_OUTPUT" not in serialized
    assert "stdout_sha256" in result.evidence


def test_command_timeout_is_reported(tmp_path):
    ctx = VerificationContext(spec_path=tmp_path / "s", root=tmp_path, allow_command=True)
    check = {
        "id": "c",
        "type": "command",
        "argv": [sys.executable, "-c", "import time; time.sleep(1)"],
        "exit_code": 0,
        "timeout_seconds": 0.05,
    }
    result = run_command_check(check, ctx)
    assert result.status is CheckStatus.FAIL
    assert "timed out" in result.summary
