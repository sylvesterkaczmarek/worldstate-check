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
