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
