from pathlib import Path

import pytest

from worldstate_check.errors import SpecError
from worldstate_check.loader import validate_spec


def base(check):
    return {"version": 1, "task": "x", "checks": [check]}


def test_valid_file_spec():
    validate_spec(base({"id": "f", "type": "file", "path": "x", "exists": True}))


def test_rejects_unknown_top_field():
    data = base({"id": "f", "type": "file", "path": "x", "exists": True})
    data["typo"] = 1
    with pytest.raises(SpecError):
        validate_spec(data)


def test_rejects_duplicate_ids():
    data = {"version": 1, "task": "x", "checks": [
        {"id": "same", "type": "file", "path": "a", "exists": True},
        {"id": "same", "type": "file", "path": "b", "exists": True},
    ]}
    with pytest.raises(SpecError, match="duplicate"):
        validate_spec(data)


def test_rejects_bad_metric_source():
    with pytest.raises(SpecError):
        validate_spec(base({"id": "m", "type": "metric", "source": {"type": "xml", "path": "x", "field": "a"}, "operator": "eq", "value": 1}))


def test_rejects_command_string_instead_of_argv():
    with pytest.raises(SpecError):
        validate_spec(base({"id": "c", "type": "command", "argv": "echo ok", "exit_code": 0}))


def test_rejects_negative_tolerance():
    with pytest.raises(SpecError):
        validate_spec(base({"id": "j", "type": "json", "path": "x.json", "field": "x", "operator": "eq", "value": 1, "tolerance": -1}))


def test_rejects_duplicate_yaml_keys(tmp_path):
    from worldstate_check.loader import load_spec

    path = tmp_path / "s.yaml"
    path.write_text(
        "version: 1\ntask: x\nchecks:\n  - id: f\n    type: file\n    path: a\n    path: b\n    exists: true\n",
        encoding="utf-8",
    )
    with pytest.raises(SpecError, match="duplicate key"):
        load_spec(path)


def test_rejects_yaml_date_scalar(tmp_path):
    from worldstate_check.loader import load_spec

    path = tmp_path / "s.yaml"
    path.write_text(
        "version: 1\ntask: x\nchecks:\n  - id: j\n    type: json\n    path: x.json\n    field: date\n    operator: eq\n    value: 2026-01-01\n",
        encoding="utf-8",
    )
    with pytest.raises(SpecError, match="non-JSON-compatible"):
        load_spec(path)


@pytest.mark.parametrize(
    "check",
    [
        {"id": "f", "type": "file", "path": "x", "contains": 123},
        {"id": "f", "type": "file", "path": "x", "sha256": "abc"},
        {"id": "h", "type": "http", "url": "http://localhost/", "text_contains": 123},
        {"id": "c", "type": "command", "argv": ["echo", "ok"], "stdout_contains": 123},
        {"id": "j", "type": "json", "path": "x", "field": "v", "operator": "between", "min": 10, "max": 1},
        {"id": "j", "type": "json", "path": "x", "field": "v", "operator": "eq", "value": "1", "tolerance": 0.1},
    ],
)
def test_rejects_malformed_assertion_types(check):
    with pytest.raises(SpecError):
        validate_spec(base(check))


def test_rejects_non_absolute_http_url():
    with pytest.raises(SpecError):
        validate_spec(base({"id": "h", "type": "http", "url": "http://", "status": 200}))


def test_rejects_boolean_port():
    with pytest.raises(SpecError):
        validate_spec(base({"id": "t", "type": "tcp", "host": "localhost", "port": True}))


def test_spec_size_limit(tmp_path):
    from worldstate_check.loader import MAX_SPEC_BYTES, load_spec

    path = tmp_path / "large.yaml"
    path.write_bytes(b"#" * (MAX_SPEC_BYTES + 1))
    with pytest.raises(SpecError, match="read limit"):
        load_spec(path)


def test_rejects_invalid_http_port():
    with pytest.raises(SpecError):
        validate_spec(base({"id": "h", "type": "http", "url": "http://localhost:99999/", "status": 200}))


def test_rejects_control_characters_in_check_id():
    with pytest.raises(SpecError):
        validate_spec(base({"id": "bad\x1b[2J", "type": "file", "path": "x", "exists": True}))


def test_rejects_all_optional_spec():
    with pytest.raises(SpecError, match="at least one check"):
        validate_spec({"version": 1, "task": "x", "checks": [{"id": "f", "type": "file", "path": "x", "exists": True, "required": False}]})


def test_rejects_empty_in_values():
    with pytest.raises(SpecError):
        validate_spec(base({"id": "j", "type": "json", "path": "x", "field": "v", "operator": "in", "values": []}))
