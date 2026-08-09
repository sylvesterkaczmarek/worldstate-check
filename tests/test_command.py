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
