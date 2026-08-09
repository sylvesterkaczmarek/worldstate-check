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
