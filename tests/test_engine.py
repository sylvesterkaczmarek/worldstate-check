import json
import threading
import time

from worldstate_check.engine import derive_verdict, verify
from worldstate_check.models import CheckResult, CheckStatus, VerificationContext, Verdict


def result(status, required=True):
    return CheckResult("x", "file", required, status, "x")


def test_verdict_verified():
    assert derive_verdict([result(CheckStatus.PASS)]) is Verdict.VERIFIED


def test_verdict_not_verified_precedes_unknown():
    assert derive_verdict([result(CheckStatus.UNKNOWN), result(CheckStatus.FAIL)]) is Verdict.NOT_VERIFIED


def test_optional_failure_does_not_block():
    assert derive_verdict([result(CheckStatus.PASS), result(CheckStatus.FAIL, required=False)]) is Verdict.VERIFIED


def test_wait_retries_until_file_changes(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"ready": False}), encoding="utf-8")
    spec = {"version": 1, "task": "wait", "checks": [{"id": "ready", "type": "json", "path": "state.json", "field": "ready", "operator": "eq", "value": True}]}
    ctx = VerificationContext(spec_path=tmp_path / "s", root=tmp_path)

    def flip():
        time.sleep(0.15)
        path.write_text(json.dumps({"ready": True}), encoding="utf-8")

    thread = threading.Thread(target=flip)
    thread.start()
    report = verify(spec, ctx, wait_seconds=1.0, poll_interval=0.05)
    thread.join()
    assert report.verdict is Verdict.VERIFIED
    assert report.attempts >= 2
