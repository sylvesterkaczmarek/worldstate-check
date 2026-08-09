import csv
import json
from datetime import datetime, timedelta, timezone

from worldstate_check.checks.metric import run_metric_check
from worldstate_check.models import CheckStatus, VerificationContext


def ctx(tmp_path):
    return VerificationContext(spec_path=tmp_path / "spec.yaml", root=tmp_path)


def test_json_metric_threshold(tmp_path):
    (tmp_path / "t.json").write_text(json.dumps({"sensor": {"temp": 62.4}}), encoding="utf-8")
    check = {"id": "m", "type": "metric", "source": {"type": "json", "path": "t.json", "field": "sensor.temp"}, "operator": "lte", "value": 75}
    assert run_metric_check(check, ctx(tmp_path)).status is CheckStatus.PASS


def test_csv_metric_uses_last_row(tmp_path):
    with (tmp_path / "t.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["v"])
        writer.writeheader()
        writer.writerow({"v": "10"})
        writer.writerow({"v": "2.5"})
    check = {"id": "m", "type": "metric", "source": {"type": "csv", "path": "t.csv", "column": "v"}, "operator": "lte", "value": 3}
    result = run_metric_check(check, ctx(tmp_path))
    assert result.status is CheckStatus.PASS
    assert result.observed == 2.5


def test_stale_metric_fails(tmp_path):
    old = (datetime.now(timezone.utc) - timedelta(seconds=20)).isoformat()
    (tmp_path / "t.json").write_text(json.dumps({"v": 1, "ts": old}), encoding="utf-8")
    check = {"id": "m", "type": "metric", "source": {"type": "json", "path": "t.json", "field": "v", "timestamp_field": "ts", "max_age_seconds": 5}, "operator": "eq", "value": 1}
    result = run_metric_check(check, ctx(tmp_path))
    assert result.status is CheckStatus.FAIL
    assert result.summary == "telemetry is stale"


def test_fresh_metric_passes(tmp_path):
    now = datetime.now(timezone.utc).isoformat()
    (tmp_path / "t.json").write_text(json.dumps({"v": 1, "ts": now}), encoding="utf-8")
    check = {"id": "m", "type": "metric", "source": {"type": "json", "path": "t.json", "field": "v", "timestamp_field": "ts", "max_age_seconds": 5}, "operator": "eq", "value": 1}
    assert run_metric_check(check, ctx(tmp_path)).status is CheckStatus.PASS


def test_future_timestamp_is_unknown(tmp_path):
    future = (datetime.now(timezone.utc) + timedelta(seconds=20)).isoformat()
    (tmp_path / "t.json").write_text(json.dumps({"v": 1, "ts": future}), encoding="utf-8")
    check = {"id": "m", "type": "metric", "source": {"type": "json", "path": "t.json", "field": "v", "timestamp_field": "ts", "max_age_seconds": 5}, "operator": "eq", "value": 1}
    assert run_metric_check(check, ctx(tmp_path)).status is CheckStatus.UNKNOWN


def test_metric_read_limit_is_enforced(tmp_path):
    (tmp_path / "t.csv").write_text("v\n" + "1\n" * 100, encoding="utf-8")
    check = {
        "id": "m",
        "type": "metric",
        "source": {"type": "csv", "path": "t.csv", "column": "v", "max_read_bytes": 16},
        "operator": "eq",
        "value": 1,
    }
    result = run_metric_check(check, ctx(tmp_path))
    assert result.status is CheckStatus.UNKNOWN
    assert "read limit" in (result.error or "")


def test_csv_missing_value_is_unknown(tmp_path):
    (tmp_path / "t.csv").write_text("v,other\n1\n", encoding="utf-8")
    check = {"id": "m", "type": "metric", "source": {"type": "csv", "path": "t.csv", "column": "other"}, "operator": "eq", "value": 1}
    result = run_metric_check(check, ctx(tmp_path))
    assert result.status is CheckStatus.UNKNOWN


def test_csv_duplicate_headers_are_unknown(tmp_path):
    (tmp_path / "t.csv").write_text("v,v\n1,2\n", encoding="utf-8")
    check = {"id": "m", "type": "metric", "source": {"type": "csv", "path": "t.csv", "column": "v"}, "operator": "eq", "value": 2}
    result = run_metric_check(check, ctx(tmp_path))
    assert result.status is CheckStatus.UNKNOWN


def test_csv_unix_epoch_freshness(tmp_path):
    now_epoch = datetime.now(timezone.utc).timestamp()
    (tmp_path / "t.csv").write_text(f"v,ts\n1,{now_epoch}\n", encoding="utf-8")
    check = {
        "id": "m",
        "type": "metric",
        "source": {"type": "csv", "path": "t.csv", "column": "v", "timestamp_column": "ts", "max_age_seconds": 5},
        "operator": "eq",
        "value": 1,
    }
    assert run_metric_check(check, ctx(tmp_path)).status is CheckStatus.PASS


def test_naive_iso_timestamp_is_unknown(tmp_path):
    (tmp_path / "t.json").write_text(json.dumps({"v": 1, "ts": "2026-08-09T12:00:00"}), encoding="utf-8")
    check = {
        "id": "m",
        "type": "metric",
        "source": {"type": "json", "path": "t.json", "field": "v", "timestamp_field": "ts", "max_age_seconds": 5},
        "operator": "eq",
        "value": 1,
    }
    assert run_metric_check(check, ctx(tmp_path)).status is CheckStatus.UNKNOWN
