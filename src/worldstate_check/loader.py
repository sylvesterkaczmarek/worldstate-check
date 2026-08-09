from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml
from yaml.constructor import ConstructorError

from .errors import SpecError
from .util import read_text_limited

MAX_SPEC_BYTES = 1_048_576
SUPPORTED_TYPES = {"file", "json", "metric", "http", "tcp", "command"}
COMMON_FIELDS = {"id", "type", "required", "description"}
ALLOWED_FIELDS = {
    "file": COMMON_FIELDS | {"path", "exists", "contains", "not_contains", "sha256", "max_read_bytes"},
    "json": COMMON_FIELDS | {"path", "field", "operator", "value", "values", "min", "max", "tolerance", "max_read_bytes"},
    "metric": COMMON_FIELDS | {"source", "operator", "value", "values", "min", "max", "tolerance"},
    "http": COMMON_FIELDS
    | {
        "url",
        "status",
        "timeout_seconds",
        "text_contains",
        "json_field",
        "operator",
        "value",
        "values",
        "min",
        "max",
        "tolerance",
    },
    "tcp": COMMON_FIELDS | {"host", "port", "reachable", "timeout_seconds"},
    "command": COMMON_FIELDS
    | {"argv", "cwd", "exit_code", "stdout_contains", "stderr_contains", "timeout_seconds", "max_output_bytes"},
}


class _UniqueKeySafeLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""


def _construct_unique_mapping(loader: _UniqueKeySafeLoader, node: yaml.MappingNode, deep: bool = False):
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable mapping key",
                key_node.start_mark,
            ) from exc
        if duplicate:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key: {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeySafeLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping)


def load_spec(path: Path) -> dict[str, Any]:
    try:
        path = path.resolve()
        raw = read_text_limited(path, MAX_SPEC_BYTES)
    except (OSError, UnicodeDecodeError, ValueError, RuntimeError) as exc:
        raise SpecError(f"cannot read specification: {exc}") from exc
    try:
        data = yaml.load(raw, Loader=_UniqueKeySafeLoader)
    except yaml.YAMLError as exc:
        raise SpecError(f"invalid YAML: {exc}") from exc
    validate_spec(data)
    return data


def validate_spec(data: Any) -> None:
    if not isinstance(data, dict):
        raise SpecError("specification root must be a mapping")
    _require_string_keys(data, "specification root")
    _require_json_compatible(data)

    unknown_top = set(data) - {"version", "task", "description", "checks"}
    if unknown_top:
        raise SpecError(f"unknown top-level fields: {', '.join(sorted(unknown_top))}")
    version = data.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version != 1:
        raise SpecError("version must be integer 1")
    task = data.get("task")
    if not _is_safe_label(task):
        raise SpecError("task must be a non-empty printable string")
    if "description" in data and (not isinstance(data["description"], str) or not data["description"].strip()):
        raise SpecError("description must be a non-empty string")
    checks = data.get("checks")
    if not isinstance(checks, list) or not checks:
        raise SpecError("checks must be a non-empty list")

    seen: set[str] = set()
    for index, check in enumerate(checks):
        _validate_check(check, index, seen)
    if not any(check.get("required", True) for check in checks):
        raise SpecError("at least one check must be required")


def _validate_check(check: Any, index: int, seen: set[str]) -> None:
    prefix = f"checks[{index}]"
    if not isinstance(check, dict):
        raise SpecError(f"{prefix} must be a mapping")
    _require_string_keys(check, prefix)
    check_id = check.get("id")
    if not _is_safe_label(check_id):
        raise SpecError(f"{prefix}.id must be a non-empty printable string")
    if check_id in seen:
        raise SpecError(f"duplicate check id: {check_id}")
    seen.add(check_id)
    check_type = check.get("type")
    if check_type not in SUPPORTED_TYPES:
        raise SpecError(f"{prefix}.type must be one of: {', '.join(sorted(SUPPORTED_TYPES))}")
    if "required" in check and not isinstance(check["required"], bool):
        raise SpecError(f"{prefix}.required must be boolean")
    if "description" in check and (not isinstance(check["description"], str) or not check["description"].strip()):
        raise SpecError(f"{prefix}.description must be a non-empty string")
    unknown = set(check) - ALLOWED_FIELDS[check_type]
    if unknown:
        raise SpecError(f"{prefix} has unknown fields: {', '.join(sorted(unknown))}")

    validators = {
        "file": _validate_file,
        "json": _validate_json,
        "metric": _validate_metric,
        "http": _validate_http,
        "tcp": _validate_tcp,
        "command": _validate_command,
    }
    validators[check_type](check, prefix)


def _require_string_keys(mapping: dict[Any, Any], prefix: str) -> None:
    if not all(isinstance(key, str) for key in mapping):
        raise SpecError(f"{prefix} keys must be strings")
    if any(not key.isprintable() for key in mapping):
        raise SpecError(f"{prefix} keys must be printable")


def _require_json_compatible(data: Any) -> None:
    try:
        json.dumps(data, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise SpecError(f"specification contains a non-JSON-compatible value: {exc}") from exc


def _is_safe_label(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value.isprintable()


def _require_str(check: dict[str, Any], key: str, prefix: str) -> None:
    if not isinstance(check.get(key), str) or not check[key].strip():
        raise SpecError(f"{prefix}.{key} must be a non-empty string")


def _is_finite_number(value: Any) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except (OverflowError, ValueError):
        return False


def _is_positive_number(value: Any) -> bool:
    return _is_finite_number(value) and float(value) > 0


def _is_positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _validate_operator(check: dict[str, Any], prefix: str, required: bool = True) -> None:
    op = check.get("operator")
    if not required and op is None:
        return
    if op not in {"eq", "ne", "lt", "lte", "gt", "gte", "between", "in"}:
        raise SpecError(f"{prefix}.operator is invalid")
    if op in {"eq", "ne", "lt", "lte", "gt", "gte"} and "value" not in check:
        raise SpecError(f"{prefix}.value is required for operator {op}")
    if op in {"lt", "lte", "gt", "gte"} and not _is_finite_number(check.get("value")):
        raise SpecError(f"{prefix}.value must be a finite number for operator {op}")
    if op == "between":
        if "min" not in check or "max" not in check:
            raise SpecError(f"{prefix}.min and {prefix}.max are required for operator between")
        if not _is_finite_number(check["min"]) or not _is_finite_number(check["max"]):
            raise SpecError(f"{prefix}.min and {prefix}.max must be finite numbers")
        if float(check["min"]) > float(check["max"]):
            raise SpecError(f"{prefix}.min must not exceed {prefix}.max")
    if op == "in":
        values = check.get("values")
        if not isinstance(values, list) or not values:
            raise SpecError(f"{prefix}.values must be a non-empty list for operator in")
    if "tolerance" in check:
        if op not in {"eq", "ne"}:
            raise SpecError(f"{prefix}.tolerance is only valid with eq or ne")
        if not _is_finite_number(check["tolerance"]) or float(check["tolerance"]) < 0:
            raise SpecError(f"{prefix}.tolerance must be a finite non-negative number")
        if not _is_finite_number(check.get("value")):
            raise SpecError(f"{prefix}.value must be numeric when tolerance is used")


def _validate_file(check: dict[str, Any], prefix: str) -> None:
    _require_str(check, "path", prefix)
    if "exists" in check and not isinstance(check["exists"], bool):
        raise SpecError(f"{prefix}.exists must be boolean")
    for key in ("contains", "not_contains"):
        if key in check:
            _require_str(check, key, prefix)
    if "sha256" in check:
        _require_str(check, "sha256", prefix)
        if re.fullmatch(r"[0-9a-fA-F]{64}", check["sha256"]) is None:
            raise SpecError(f"{prefix}.sha256 must contain exactly 64 hexadecimal characters")
    if not any(k in check for k in {"exists", "contains", "not_contains", "sha256"}):
        raise SpecError(f"{prefix} must declare at least one file assertion")
    if "max_read_bytes" in check and not _is_positive_int(check["max_read_bytes"]):
        raise SpecError(f"{prefix}.max_read_bytes must be a positive integer")


def _validate_json(check: dict[str, Any], prefix: str) -> None:
    _require_str(check, "path", prefix)
    _require_str(check, "field", prefix)
    if "max_read_bytes" in check and not _is_positive_int(check["max_read_bytes"]):
        raise SpecError(f"{prefix}.max_read_bytes must be a positive integer")
    _validate_operator(check, prefix)


def _validate_metric(check: dict[str, Any], prefix: str) -> None:
    source = check.get("source")
    if not isinstance(source, dict):
        raise SpecError(f"{prefix}.source must be a mapping")
    _require_string_keys(source, f"{prefix}.source")
    source_type = source.get("type")
    if source_type not in {"json", "csv"}:
        raise SpecError(f"{prefix}.source.type must be json or csv")
    allowed = (
        {"type", "path", "field", "timestamp_field", "max_age_seconds", "max_read_bytes"}
        if source_type == "json"
        else {"type", "path", "column", "timestamp_column", "max_age_seconds", "max_read_bytes"}
    )
    unknown = set(source) - allowed
    if unknown:
        raise SpecError(f"{prefix}.source has unknown fields: {', '.join(sorted(unknown))}")
    _require_str(source, "path", f"{prefix}.source")
    _require_str(source, "field" if source_type == "json" else "column", f"{prefix}.source")
    if "max_read_bytes" in source and not _is_positive_int(source["max_read_bytes"]):
        raise SpecError(f"{prefix}.source.max_read_bytes must be a positive integer")
    if "max_age_seconds" in source and (
        not _is_finite_number(source["max_age_seconds"]) or float(source["max_age_seconds"]) < 0
    ):
        raise SpecError(f"{prefix}.source.max_age_seconds must be a finite non-negative number")
    if "max_age_seconds" in source:
        timestamp_key = "timestamp_field" if source_type == "json" else "timestamp_column"
        _require_str(source, timestamp_key, f"{prefix}.source")
    _validate_operator(check, prefix)


def _validate_http(check: dict[str, Any], prefix: str) -> None:
    _require_str(check, "url", prefix)
    try:
        parsed = urlparse(check["url"])
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise SpecError(f"{prefix}.url is malformed: {exc}") from exc
    if parsed.scheme not in {"http", "https"} or not host:
        raise SpecError(f"{prefix}.url must be an absolute http or https URL")
    if port is not None and not 1 <= port <= 65535:
        raise SpecError(f"{prefix}.url port must be 1..65535")
    if "status" in check and (
        not isinstance(check["status"], int) or isinstance(check["status"], bool) or not 100 <= check["status"] <= 599
    ):
        raise SpecError(f"{prefix}.status must be an HTTP status code")
    if "text_contains" in check:
        _require_str(check, "text_contains", prefix)
    if not any(k in check for k in {"status", "text_contains", "json_field"}):
        raise SpecError(f"{prefix} must declare at least one HTTP assertion")
    if "json_field" in check:
        _require_str(check, "json_field", prefix)
        _validate_operator(check, prefix)
    if "timeout_seconds" in check and not _is_positive_number(check["timeout_seconds"]):
        raise SpecError(f"{prefix}.timeout_seconds must be a finite positive number")


def _validate_tcp(check: dict[str, Any], prefix: str) -> None:
    _require_str(check, "host", prefix)
    port = check.get("port")
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise SpecError(f"{prefix}.port must be 1..65535")
    if "reachable" in check and not isinstance(check["reachable"], bool):
        raise SpecError(f"{prefix}.reachable must be boolean")
    if "timeout_seconds" in check and not _is_positive_number(check["timeout_seconds"]):
        raise SpecError(f"{prefix}.timeout_seconds must be a finite positive number")


def _validate_command(check: dict[str, Any], prefix: str) -> None:
    argv = check.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(v, str) and v.strip() for v in argv):
        raise SpecError(f"{prefix}.argv must be a non-empty list of non-empty strings")
    if "cwd" in check:
        _require_str(check, "cwd", prefix)
    if "exit_code" in check and (not isinstance(check["exit_code"], int) or isinstance(check["exit_code"], bool)):
        raise SpecError(f"{prefix}.exit_code must be an integer")
    for key in ("stdout_contains", "stderr_contains"):
        if key in check:
            _require_str(check, key, prefix)
    if not any(k in check for k in {"exit_code", "stdout_contains", "stderr_contains"}):
        raise SpecError(f"{prefix} must declare at least one command assertion")
    if "timeout_seconds" in check and not _is_positive_number(check["timeout_seconds"]):
        raise SpecError(f"{prefix}.timeout_seconds must be a finite positive number")
    if "max_output_bytes" in check and not _is_positive_int(check["max_output_bytes"]):
        raise SpecError(f"{prefix}.max_output_bytes must be a positive integer")
