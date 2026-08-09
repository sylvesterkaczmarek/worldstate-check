import pytest

from worldstate_check.checks.json_check import run_json_check
from worldstate_check.errors import SpecError
from worldstate_check.loader import validate_spec
from worldstate_check.models import CheckStatus, VerificationContext


def test_rejects_oversized_numeric_threshold_without_crashing():
    huge = 10 ** 400
    spec = {
        "version": 1,
        "task": "numeric-bound",
        "checks": [
            {"id": "value", "type": "json", "path": "x.json", "field": "v", "operator": "lte", "value": huge}
        ],
    }
    with pytest.raises(SpecError):
        validate_spec(spec)


def test_oversized_observed_number_becomes_unknown_not_crash(tmp_path):
    huge = 10 ** 400
    (tmp_path / "x.json").write_text('{"v": ' + str(huge) + '}', encoding="utf-8")
    ctx = VerificationContext(spec_path=tmp_path / "spec.yaml", root=tmp_path)
    check = {"id": "value", "type": "json", "path": "x.json", "field": "v", "operator": "lte", "value": 10}
    result = run_json_check(check, ctx)
    assert result.status is CheckStatus.UNKNOWN
    assert "numeric comparison" in (result.error or "")
