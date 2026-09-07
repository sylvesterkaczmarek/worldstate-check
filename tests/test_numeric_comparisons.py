import json

import pytest

from worldstate_check import Verdict, verify_spec_data
from worldstate_check.models import CheckStatus


def verify_numbers(tmp_path, observed, assertions, source_type="json"):
    if source_type == "metric-csv":
        (tmp_path / "state.csv").write_text(f"counter\n{observed}\n", encoding="utf-8")
        source = {"type": "csv", "path": "state.csv", "column": "counter"}
        base = {"type": "metric", "source": source}
    else:
        (tmp_path / "state.json").write_text(json.dumps({"counter": observed}), encoding="utf-8")
        if source_type == "metric-json":
            source = {"type": "json", "path": "state.json", "field": "counter"}
            base = {"type": "metric", "source": source}
        else:
            base = {"type": "json", "path": "state.json", "field": "counter"}
    return verify_spec_data(
        {
            "version": 1,
            "task": "exact-numbers",
            "checks": [dict(base, id=f"number-{i}", **assertion) for i, assertion in enumerate(assertions)],
        },
        root=tmp_path,
    )


@pytest.mark.parametrize(
    "observed", [2**53 + 1, -(2**53) - 1, 10**400, -(10**400)],
    ids=["positive-counter", "negative-counter", "huge-positive", "huge-negative"],
)
@pytest.mark.parametrize("offset", [-1, 1])
def test_adjacent_integer_comparisons(tmp_path, observed, offset):
    expected = observed + offset
    assertions = [{"operator": op, "value": expected} for op in ("eq", "ne", "lt", "lte", "gt", "gte")]
    assertions.extend(
        [
            {"operator": "between", "min": expected, "max": expected},
            {"operator": "in", "values": [expected]},
        ]
    )
    report = verify_numbers(tmp_path, observed, assertions)
    statuses = (
        [False, True, False, False, True, True, False, False]
        if offset == -1
        else [False, True, True, True, False, False, False, False]
    )
    assert report.verdict is Verdict.NOT_VERIFIED
    assert [result.status for result in report.results] == [
        CheckStatus.PASS if passed else CheckStatus.FAIL for passed in statuses
    ]
    assert all(result.observed == observed for result in report.results)


@pytest.mark.parametrize(
    "observed", [2**53 + 1, -(2**53) - 1, 10**400],
    ids=["positive-counter", "negative-counter", "huge-positive"],
)
def test_nested_equality_and_membership_preserve_integer_values(tmp_path, observed):
    report = verify_numbers(
        tmp_path,
        {"items": [observed]},
        [
            {"operator": "eq", "value": {"items": [observed - 1]}},
            {"operator": "in", "values": [{"items": [observed - 1]}]},
            {"operator": "eq", "value": {"items": [observed]}},
            {"operator": "in", "values": [{"items": [observed]}]},
        ],
    )
    assert [result.status for result in report.results] == [
        CheckStatus.FAIL, CheckStatus.FAIL, CheckStatus.PASS, CheckStatus.PASS,
    ]


@pytest.mark.parametrize(
    "observed, expected, ordering",
    [(2**53 + 1, float(2**53), "gt"), (float(2**53), 2**53 + 1, "lt")],
)
def test_mixed_integer_float_comparison_and_absolute_tolerance(tmp_path, observed, expected, ordering):
    report = verify_numbers(
        tmp_path,
        observed,
        [
            {"operator": "eq", "value": expected},
            {"operator": ordering, "value": expected},
            {"operator": "eq", "value": expected, "tolerance": 0},
            {"operator": "eq", "value": expected, "tolerance": 0.5},
            {"operator": "eq", "value": expected, "tolerance": 1},
        ],
    )
    assert [result.status for result in report.results] == [
        CheckStatus.FAIL, CheckStatus.PASS, CheckStatus.FAIL, CheckStatus.FAIL, CheckStatus.PASS,
    ]


@pytest.mark.parametrize(
    "observed, expected, tolerance, passed",
    [
        (10**400, 10**400 - 1, 0, False),
        (10**400, 10**400 - 1, 1, True),
        (10**400, -(10**400), 2 * 10**400, True),
        (10**400, 1.0, 10**400 - 2, False),
        (10**400, 1.0, 10**400 - 1, True),
        (1e308, -1e308, 1.7e308, False),
        (0.1 + 0.2, 0.3, 1e-15, True),
        (5e-324, 0.0, 0.0, False),
        (5e-324, 0.0, 5e-324, True),
    ],
    ids=[
        "huge-zero-tolerance", "huge-unit-tolerance", "huge-span", "huge-mixed-outside",
        "huge-mixed-boundary", "float-difference-overflow", "ordinary-floats",
        "subnormal-outside", "subnormal-boundary",
    ],
)
def test_absolute_tolerance_is_exact_and_does_not_overflow(tmp_path, observed, expected, tolerance, passed):
    report = verify_numbers(
        tmp_path,
        observed,
        [{"operator": op, "value": expected, "tolerance": tolerance} for op in ("eq", "ne")],
    )
    assert [result.status for result in report.results] == (
        [CheckStatus.PASS, CheckStatus.FAIL] if passed else [CheckStatus.FAIL, CheckStatus.PASS]
    )


@pytest.mark.parametrize("source_type", ["metric-json", "metric-csv"])
def test_metric_sources_keep_large_integer_counters_exact(tmp_path, source_type):
    observed = 2**53 + 1
    report = verify_numbers(
        tmp_path,
        observed,
        [{"operator": "eq", "value": observed - 1}, {"operator": "gt", "value": observed - 1}],
        source_type=source_type,
    )
    assert report.verdict is Verdict.NOT_VERIFIED
    assert [result.status for result in report.results] == [CheckStatus.FAIL, CheckStatus.PASS]
    assert type(report.results[0].observed) is int
    assert report.results[0].observed == observed


def test_numeric_equality_keeps_boolean_distinction_and_equal_float_values(tmp_path):
    report = verify_numbers(
        tmp_path,
        {"items": [1, 0]},
        [
            {"operator": "eq", "value": {"items": [True, False]}},
            {"operator": "in", "values": [{"items": [True, False]}]},
            {"operator": "eq", "value": {"items": [1.0, 0.0]}},
        ],
    )
    assert [result.status for result in report.results] == [CheckStatus.FAIL, CheckStatus.FAIL, CheckStatus.PASS]
