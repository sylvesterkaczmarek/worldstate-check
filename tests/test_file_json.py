import json
from pathlib import Path

from worldstate_check.checks.file import run_file_check
from worldstate_check.checks.json_check import run_json_check
from worldstate_check.models import CheckStatus, VerificationContext


def ctx(tmp_path):
    return VerificationContext(spec_path=tmp_path / "spec.yaml", root=tmp_path)


def test_file_exists_and_contains(tmp_path):
    (tmp_path / "x.txt").write_text("READY\n", encoding="utf-8")
    result = run_file_check({"id": "x", "type": "file", "path": "x.txt", "exists": True, "contains": "READY"}, ctx(tmp_path))
    assert result.status is CheckStatus.PASS


def test_missing_file_fails_exists_true(tmp_path):
    result = run_file_check({"id": "x", "type": "file", "path": "x.txt", "exists": True}, ctx(tmp_path))
    assert result.status is CheckStatus.FAIL


def test_absent_file_can_be_expected(tmp_path):
    result = run_file_check({"id": "x", "type": "file", "path": "x.txt", "exists": False}, ctx(tmp_path))
    assert result.status is CheckStatus.PASS


def test_path_escape_is_unknown(tmp_path):
    result = run_file_check({"id": "x", "type": "file", "path": "../secret", "exists": True}, ctx(tmp_path))
    assert result.status is CheckStatus.UNKNOWN


def test_json_nested_field_passes(tmp_path):
    (tmp_path / "s.json").write_text(json.dumps({"a": {"b": 3}}), encoding="utf-8")
    result = run_json_check({"id": "j", "type": "json", "path": "s.json", "field": "a.b", "operator": "lte", "value": 3}, ctx(tmp_path))
    assert result.status is CheckStatus.PASS


def test_json_missing_field_fails(tmp_path):
    (tmp_path / "s.json").write_text("{}", encoding="utf-8")
    result = run_json_check({"id": "j", "type": "json", "path": "s.json", "field": "a.b", "operator": "eq", "value": 3}, ctx(tmp_path))
    assert result.status is CheckStatus.FAIL


def test_invalid_json_is_unknown(tmp_path):
    (tmp_path / "s.json").write_text("{", encoding="utf-8")
    result = run_json_check({"id": "j", "type": "json", "path": "s.json", "field": "a", "operator": "eq", "value": 3}, ctx(tmp_path))
    assert result.status is CheckStatus.UNKNOWN


def test_json_evidence_read_limit_is_enforced(tmp_path):
    (tmp_path / "large.json").write_text(json.dumps({"value": "x" * 100}), encoding="utf-8")
    check = {
        "id": "j",
        "type": "json",
        "path": "large.json",
        "field": "value",
        "operator": "eq",
        "value": "x" * 100,
        "max_read_bytes": 16,
    }
    result = run_json_check(check, ctx(tmp_path))
    assert result.status is CheckStatus.UNKNOWN
    assert "read limit" in (result.error or "")


def test_json_rejects_non_standard_nan(tmp_path):
    (tmp_path / "s.json").write_text('{"value": NaN}', encoding="utf-8")
    check = {"id": "j", "type": "json", "path": "s.json", "field": "value", "operator": "eq", "value": 1}
    result = run_json_check(check, ctx(tmp_path))
    assert result.status is CheckStatus.UNKNOWN


def test_json_rejects_duplicate_object_keys(tmp_path):
    (tmp_path / "s.json").write_text('{"value": 1, "value": 2}', encoding="utf-8")
    check = {"id": "j", "type": "json", "path": "s.json", "field": "value", "operator": "eq", "value": 2}
    result = run_json_check(check, ctx(tmp_path))
    assert result.status is CheckStatus.UNKNOWN
    assert "duplicate JSON" in (result.error or "")


def test_json_rejects_overflow_to_infinity(tmp_path):
    (tmp_path / "s.json").write_text('{"value": 1e999}', encoding="utf-8")
    check = {"id": "j", "type": "json", "path": "s.json", "field": "value", "operator": "eq", "value": 1}
    result = run_json_check(check, ctx(tmp_path))
    assert result.status is CheckStatus.UNKNOWN


def test_json_boolean_does_not_equal_number(tmp_path):
    (tmp_path / "s.json").write_text('{"value": true}', encoding="utf-8")
    check = {"id": "j", "type": "json", "path": "s.json", "field": "value", "operator": "eq", "value": 1}
    result = run_json_check(check, ctx(tmp_path))
    assert result.status is CheckStatus.FAIL


def test_json_accepts_utf8_bom(tmp_path):
    (tmp_path / "s.json").write_bytes(bytes([0xEF, 0xBB, 0xBF]) + b'{"value": 2}')
    check = {"id": "j", "type": "json", "path": "s.json", "field": "value", "operator": "eq", "value": 2}
    result = run_json_check(check, ctx(tmp_path))
    assert result.status is CheckStatus.PASS


def test_symlink_loop_never_crashes(tmp_path):
    loop = tmp_path / "loop"
    try:
        loop.symlink_to(loop)
    except (OSError, NotImplementedError):
        return
    result = run_file_check({"id": "x", "type": "file", "path": "loop", "exists": True}, ctx(tmp_path))
    assert result.status in {CheckStatus.FAIL, CheckStatus.UNKNOWN}
