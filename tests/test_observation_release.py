import copy
import json
import socket
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import pytest

from worldstate_check import SpecError, Verdict, verify_spec_data
from worldstate_check.cli import main
from worldstate_check.replay import fingerprint, replay_bundle, replay_data
from worldstate_check.report import report_payload, verify_json_report
from worldstate_check.util import canonical_json


def spec(*checks):
    return {"version": 1, "task": "test", "checks": list(checks)}


@contextmanager
def endpoint(readings):
    calls = []

    class Service(BaseHTTPRequestHandler):
        def do_GET(self):
            route = self.path.split("?")[0]
            calls.append(route)
            if route in ("/redirect", "/unexpected"):
                self.send_response(302)
                self.send_header(
                    "Location",
                    "/state?auth=example" if route == "/redirect" else "/login",
                )
                self.end_headers()
                return
            row = (
                readings[min(calls.count("/state") - 1, len(readings) - 1)]
                if route == "/state"
                else {}
            )
            body = json.dumps(row).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    with HTTPServer(("127.0.0.1", 0), Service) as server:
        thread = Thread(
            target=server.serve_forever, kwargs={"poll_interval": 0.005}, daemon=True
        )
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}", calls
        finally:
            server.shutdown()
            thread.join()


def http(url, key, value):
    return {
        "id": key,
        "type": "http",
        "url": url,
        "json_field": key,
        "operator": "eq",
        "value": value,
    }


def test_rollout_and_retry_use_one_response_per_attempt(tmp_path):
    readings = [{"v": 1, "up": True}, {"v": 2, "up": False}, {"v": 2, "up": True}]
    with endpoint(readings) as (base, calls):
        url = base + "/state"
        checks = spec(http(url, "up", True), http(url, "v", 2))
        first = verify_spec_data(checks, root=tmp_path, allow_network=True)
        assert first.verdict is Verdict.NOT_VERIFIED and calls == ["/state"]
        bundle = tmp_path / "run.json"
        result = verify_spec_data(
            checks,
            root=tmp_path,
            allow_network=True,
            record_to=bundle,
            wait_seconds=2,
            poll_interval=0.001,
        )
        assert result.attempts == 2 and result.verdict is Verdict.VERIFIED
        assert calls == ["/state"] * 3
        assert result.results[0].evidence == result.results[1].evidence
    replayed = replay_bundle(bundle)
    assert replayed.verdict == result.verdict and replayed.attempts == 2
    assert replayed.results[0].evidence == result.results[0].evidence


def test_distinct_samples_explicit_and_acquisition_options_consistent(tmp_path):
    with endpoint([{"a": 0}, {"a": 1}]) as (base, calls):
        a = http(base + "/state", "a", 0)
        b = {**a, "id": "b", "value": 1, "timeout_seconds": 1}
        with pytest.raises(SpecError):
            verify_spec_data(spec(a, b), root=tmp_path, allow_network=True)
        b["sample"] = "second"
        assert (
            verify_spec_data(spec(a, b), root=tmp_path, allow_network=True).verdict
            is Verdict.VERIFIED
        )
        assert len(calls) == 2


def test_redirect_observes_requested_resource_unless_destination_matches(tmp_path):
    with endpoint([{"up": True}]) as (base, calls):
        check = {
            "id": "health",
            "type": "http",
            "url": base + "/redirect",
            "status": 200,
        }

        def verify(**changes):
            return verify_spec_data(
                spec({**check, **changes}), root=tmp_path, allow_network=True
            )

        denied = verify()
        assert denied.verdict is Verdict.NOT_VERIFIED and calls == ["/redirect"]
        assert denied.results[0].evidence["effective_url"] == check["url"]
        assert denied.results[0].evidence["redirect_target"] == base + "/state"
        assert verify(status=302).verdict is Verdict.VERIFIED
        accepted = verify(redirect_to=base + "/state?auth=example")
        assert accepted.verdict is Verdict.VERIFIED
        assert accepted.results[0].evidence["effective_url"] == base + "/state"
        assert accepted.results[0].evidence["redirected"] is True
        assert "auth=example" not in canonical_json(report_payload(accepted))
        assert (
            verify(url=base + "/unexpected", redirect_to=base + "/state").verdict
            is Verdict.NOT_VERIFIED
        )
        assert "/login" not in calls


@pytest.mark.parametrize(
    "data,op,value,verdict",
    [
        ({}, "eq", 4, Verdict.UNCERTAIN),
        ({}, "exists", False, Verdict.VERIFIED),
        ({}, "exists", True, Verdict.NOT_VERIFIED),
        ({"v": None}, "exists", True, Verdict.VERIFIED),
        ({"v": None}, "eq", None, Verdict.VERIFIED),
        ({"v": None}, "lt", 5, Verdict.UNCERTAIN),
        ({"v": 6}, "lt", 5, Verdict.NOT_VERIFIED),
    ],
)
def test_adapter_parity(tmp_path, data, op, value, verdict):
    (tmp_path / "state").write_text(json.dumps(data))
    with endpoint([data]) as (base, _):
        checks = [
            {"type": "json", "path": "state", "field": "v"},
            {
                "type": "metric",
                "source": {"type": "json", "path": "state", "field": "v"},
            },
            {"type": "http", "url": base + "/state", "json_field": "v"},
        ]
        for check in checks:
            result = verify_spec_data(
                spec(dict(check, id="v", operator=op, value=value)),
                root=tmp_path,
                allow_network=True,
            )
            assert result.verdict is verdict


@pytest.mark.parametrize(
    "kind,field,timestamp",
    [("json", "field", "timestamp_field"), ("csv", "column", "timestamp_column")],
)
def test_timestamp_cannot_be_silently_ignored(tmp_path, kind, field, timestamp):
    check = {
        "type": "metric",
        "id": "v",
        "source": {"type": kind, "path": "x", field: "v", timestamp: "ts"},
        "operator": "gt",
        "value": 0,
    }
    with pytest.raises(SpecError, match="requires max_age_seconds"):
        verify_spec_data(spec(check), root=tmp_path)


def test_large_valid_report_parity_and_value_references(tmp_path, capsys):
    samples = [i % 100 for i in range(50000)]
    (tmp_path / "state.json").write_text(json.dumps({"data": samples}))
    specification = tmp_path / "spec.json"
    specification.write_text(
        json.dumps(
            spec(
                {
                    "id": "cal",
                    "type": "json",
                    "path": "state.json",
                    "field": "data",
                    "operator": "eq",
                    "value": samples,
                }
            )
        )
    )
    output = tmp_path / "report"
    assert main(["verify", str(specification)]) == 0
    capsys.readouterr()
    assert main(["verify", str(specification), "--json", "--report", str(output)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert verify_json_report(output) and json.loads(output.read_text()) == payload
    refs = payload["results"][0]["evidence"]["value_references"]
    assert refs["observed"]["sha256"] == fingerprint(samples)
    assert refs["observed"] == refs["expected"] and output.stat().st_size < 4096


def test_every_adapter_replays_without_live_access(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    now = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps({"v": 1, "event": now}))
    with endpoint([{"v": 1}]) as (base, _):
        checks = spec(
            {"type": "file", "id": "f", "path": "state.json", "contains": "event"},
            {
                "type": "json",
                "id": "j",
                "path": "state.json",
                "field": "v",
                "operator": "eq",
                "value": 1,
            },
            {
                "type": "metric",
                "id": "m",
                "source": {
                    "type": "json",
                    "path": "state.json",
                    "field": "v",
                    "timestamp_field": "event",
                    "max_age_seconds": 60,
                },
                "operator": "eq",
                "value": 1,
            },
            http(base + "/state", "v", 1),
            {
                "type": "tcp",
                "id": "t",
                "host": "127.0.0.1",
                "port": int(base.rsplit(":", 1)[-1]),
                "reachable": True,
            },
            {
                "type": "command",
                "id": "c",
                "argv": [sys.executable, "-c", "print(1)"],
                "stdout_contains": "1",
            },
        )
        bundle = tmp_path / "capture"
        report = verify_spec_data(
            checks,
            root=tmp_path,
            record_to=bundle,
            allow_command=True,
            allow_network=True,
        )
        assert report.verdict is Verdict.VERIFIED
    path.unlink()

    def forbidden(*args, **kwargs):
        pytest.fail("replay performed live I/O")

    monkeypatch.setattr("worldstate_check.observations.capture", forbidden)
    monkeypatch.setattr("worldstate_check.checks.command.run_bounded", forbidden)
    monkeypatch.setattr("worldstate_check.checks.http._open_response", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    replay = replay_bundle(bundle)
    assert replay.verdict is Verdict.VERIFIED
    assert (
        replay.results[2].evidence["age_seconds"]
        == report.results[2].evidence["age_seconds"]
    )
    assert [r.reason_code for r in replay.results] == [
        r.reason_code for r in report.results
    ]
    data = json.loads(bundle.read_text())
    damaged = copy.deepcopy(data)
    damaged["attempts"][0]["events"].clear()
    with pytest.raises(ValueError, match="checksum"):
        replay_data(damaged)
    damaged.pop("sha256")
    damaged["sha256"] = fingerprint(damaged)
    with pytest.raises(ValueError, match="missing recorded observation"):
        replay_data(damaged)


def test_record_output_collisions(tmp_path):
    (tmp_path / "state").write_text("ok")
    path = tmp_path / "spec.json"
    path.write_text(
        json.dumps(spec({"id": "f", "type": "file", "path": "state", "exists": True}))
    )
    original = path.read_bytes()
    assert main(["verify", str(path), "--record", str(path)]) == 2
    assert main(["verify", str(path), "--record", str(tmp_path / "state")]) == 2
    assert (
        main(
            [
                "verify",
                str(path),
                "--record",
                str(tmp_path / "one"),
                "--report",
                str(tmp_path / "one"),
            ]
        )
        == 2
    )
    assert path.read_bytes() == original and (tmp_path / "state").read_text() == "ok"


@pytest.mark.parametrize(
    "times,ids,values,verdict",
    [
        ([0, 0.5, 1], [0, 1, 2], [1, 1, 1], Verdict.VERIFIED),
        ([0, 1], [0, 1], [1, 1], Verdict.UNCERTAIN),
        ([0, 0.5, 1], [0, 1, 1], [1, 1, 1], Verdict.UNCERTAIN),
        ([0, 0.5, 0.4, 1], [0, 1, 2, 3], [1, 1, 1, 1], Verdict.UNCERTAIN),
        ([0, 0.5], [0, 1], [1, 0], Verdict.NOT_VERIFIED),
        ([0.5, 1], [0, 1], [1, 1], Verdict.UNCERTAIN),
    ],
)
def test_sample_window(tmp_path, times, ids, values, verdict):
    check = {
        "type": "window",
        "id": "stable",
        "path": "data",
        "series": "samples",
        "timestamp_field": "t",
        "sample_id_field": "id",
        "start": 0,
        "end": 1,
        "max_gap_seconds": 0.5,
        "field": "v",
        "operator": "eq",
        "value": 1,
    }
    rows = [{"t": t, "id": i, "v": v} for t, i, v in zip(times, ids, values)]
    (tmp_path / "data").write_text(json.dumps({"samples": rows}))
    assert verify_spec_data(spec(check), root=tmp_path).verdict is verdict


def test_installed_example(capsys):
    assert main(["replay", "--example", "placement", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["verdict"] == "NOT_VERIFIED"


def test_engine_preserves_resolved_acquisition_path_under_root_alias(tmp_path):
    from worldstate_check.engine import verify
    from worldstate_check.models import VerificationContext

    actual = tmp_path / "actual"
    actual.mkdir()
    (actual / "reading").write_text("ok")
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(actual, target_is_directory=True)
    except OSError:
        pytest.skip("directory aliases unavailable")
    ctx = VerificationContext(alias / "spec", alias)
    bundle = tmp_path / "recording"
    checks = spec({"id": "marker", "type": "file", "path": "reading", "contains": "ok"})
    report = verify(checks, ctx, record_to=bundle)
    assert report.verdict is Verdict.VERIFIED
    assert report.results[0].evidence["path"] == "reading"
    assert replay_bundle(bundle).verdict is Verdict.VERIFIED
