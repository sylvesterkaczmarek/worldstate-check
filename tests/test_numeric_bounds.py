import pytest

from worldstate_check import Verdict, verify_spec_data
from worldstate_check.errors import SpecError
from worldstate_check.loader import validate_spec
from worldstate_check.models import CheckStatus


def numeric_spec(**assertion):
    return {
        "version": 1,
        "task": "numeric-bound",
        "checks": [{"id": "value", "type": "json", "path": "x.json", "field": "v", **assertion}],
    }


def test_accepts_large_integer_threshold_without_float_conversion(tmp_path):
    huge = 10**400
    (tmp_path / "x.json").write_text('{"v": ' + str(huge) + '}', encoding="utf-8")
    report = verify_spec_data(numeric_spec(operator="lte", value=huge), root=tmp_path)
    assert report.verdict is Verdict.VERIFIED
    assert report.results[0].expected == report.results[0].observed == huge


def test_large_observed_integer_is_compared_without_overflow(tmp_path):
    huge = 10**400
    (tmp_path / "x.json").write_text('{"v": ' + str(huge) + '}', encoding="utf-8")
    report = verify_spec_data(numeric_spec(operator="lte", value=10), root=tmp_path)
    assert report.verdict is Verdict.NOT_VERIFIED
    assert report.results[0].status is CheckStatus.FAIL
    assert report.results[0].error is None


@pytest.mark.parametrize(
    "low, high", [(2**53 + 1, 2**53), (2**53 + 1, float(2**53)), (10**400 + 1, 10**400)],
    ids=["adjacent-integers", "mixed-integer-float", "huge-integers"],
)
def test_reversed_integer_bounds_are_rejected(low, high):
    with pytest.raises(SpecError, match="min must not exceed"):
        validate_spec(numeric_spec(operator="between", min=low, max=high))


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan"), True])
def test_nonfinite_and_boolean_numeric_thresholds_remain_invalid(value):
    with pytest.raises(SpecError):
        validate_spec(numeric_spec(operator="lte", value=value))


@pytest.mark.parametrize("raw", ["NaN", "Infinity", "1e400"])
def test_nonfinite_json_evidence_remains_unknown(tmp_path, raw):
    (tmp_path / "x.json").write_text('{"v": ' + raw + '}', encoding="utf-8")
    report = verify_spec_data(numeric_spec(operator="lte", value=10), root=tmp_path)
    assert report.verdict is Verdict.UNCERTAIN
    assert report.results[0].status is CheckStatus.UNKNOWN


@pytest.mark.parametrize("check", [
    {"type": "tcp", "host": "localhost", "port": 1234, "timeout_seconds": 10**400},
    {
        "type": "metric",
        "source": {
            "type": "json", "path": "x.json", "field": "v", "timestamp_field": "time",
            "max_age_seconds": 10**400,
        },
        "operator": "eq",
        "value": 1,
    },
], ids=["network-timeout", "metric-freshness"])
def test_operational_time_limits_still_require_float_compatible_values(check):
    with pytest.raises(SpecError, match="finite"):
        validate_spec({"version": 1, "task": "time-bound", "checks": [dict(check, id="time")]})
