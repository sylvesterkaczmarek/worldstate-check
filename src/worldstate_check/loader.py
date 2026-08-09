from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .errors import SpecError

SUPPORTED_TYPES = {"file", "json", "metric", "http", "tcp", "command"}
COMMON_FIELDS = {"id", "type", "required", "description"}
ALLOWED_FIELDS = {
    "file": COMMON_FIELDS | {"path", "exists", "contains", "not_contains", "sha256", "max_read_bytes"},
    "json": COMMON_FIELDS | {"path", "field", "operator", "value", "values", "min", "max", "tolerance"},
    "metric": COMMON_FIELDS | {"source", "operator", "value", "values", "min", "max", "tolerance"},
    "http": COMMON_FIELDS | {
        "url", "status", "timeout_seconds", "text_contains", "json_field", "operator", "value", "values", "min", "max", "tolerance"
    },
    "tcp": COMMON_FIELDS | {"host", "port", "reachable", "timeout_seconds"},
    "command": COMMON_FIELDS | {
        "argv", "cwd", "exit_code", "stdout_contains", "stderr_contains", "timeout_seconds", "max_output_bytes"
    },
}


def load_spec(path: Path) -> dict[str, Any]:
    path = path.resolve()
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SpecError(f"cannot read specification: {exc}") from exc
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise SpecError(f"invalid YAML: {exc}") from exc
    validate_spec(data)
    return data


def validate_spec(data: Any) -> None:
    if not isinstance(data, dict):
        raise SpecError("specification root must be a mapping")
    unknown_top = set(data) - {"version", "task", "description", "checks"}
    if unknown_top:
        raise SpecError(f"unknown top-level fields: {', '.join(sorted(unknown_top))}")
    if data.get("version") != 1:
        raise SpecError("version must be 1")
    task = data.get("task")
    if not isinstance(task, str) or not task.strip():
        raise SpecError("task must be a non-empty string")
    checks = data.get("checks")
    if not isinstance(checks, list) or not checks:
        raise SpecError("checks must be a non-empty list")

    seen: set[str] = set()
    for index, check in enumerate(checks):
        _validate_check(check, index, seen)


def _validate_check(check: Any, index: int, seen: set[str]) -> None:
    prefix = f"checks[{index}]"
    if not isinstance(check, dict):
        raise SpecError(f"{prefix} must be a mapping")
    check_id = check.get("id")
    if not isinstance(check_id, str) or not check_id.strip():
        raise SpecError(f"{prefix}.id must be a non-empty string")
    if check_id in seen:
        raise SpecError(f"duplicate check id: {check_id}")
    seen.add(check_id)
    check_type = check.get("type")
    if check_type not in SUPPORTED_TYPES:
        raise SpecError(f"{prefix}.type must be one of: {', '.join(sorted(SUPPORTED_TYPES))}")
    if "required" in check and not isinstance(check["required"], bool):
        raise SpecError(f"{prefix}.required must be boolean")
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


def _require_str(check: dict[str, Any], key: str, prefix: str) -> None:
    if not isinstance(check.get(key), str) or not check[key].strip():
        raise SpecError(f"{prefix}.{key} must be a non-empty string")


def _validate_operator(check: dict[str, Any], prefix: str, required: bool = True) -> None:
    op = check.get("operator")
    if not required and op is None:
        return
    if op not in {"eq", "ne", "lt", "lte", "gt", "gte", "between", "in"}:
        raise SpecError(f"{prefix}.operator is invalid")
    if op in {"eq", "ne", "lt", "lte", "gt", "gte"} and "value" not in check:
        raise SpecError(f"{prefix}.value is required for operator {op}")
    if op == "between" and ("min" not in check or "max" not in check):
        raise SpecError(f"{prefix}.min and {prefix}.max are required for operator between")
    if op == "in" and not isinstance(check.get("values"), list):
        raise SpecError(f"{prefix}.values must be a list for operator in")
    if "tolerance" in check and (not isinstance(check["tolerance"], (int, float)) or check["tolerance"] < 0):
        raise SpecError(f"{prefix}.tolerance must be a non-negative number")


def _validate_file(check: dict[str, Any], prefix: str) -> None:
    _require_str(check, "path", prefix)
    if "exists" in check and not isinstance(check["exists"], bool):
        raise SpecError(f"{prefix}.exists must be boolean")
    if not any(k in check for k in {"exists", "contains", "not_contains", "sha256"}):
        raise SpecError(f"{prefix} must declare at least one file assertion")
    if "max_read_bytes" in check and (not isinstance(check["max_read_bytes"], int) or check["max_read_bytes"] <= 0):
        raise SpecError(f"{prefix}.max_read_bytes must be a positive integer")


def _validate_json(check: dict[str, Any], prefix: str) -> None:
    _require_str(check, "path", prefix)
    _require_str(check, "field", prefix)
    _validate_operator(check, prefix)


def _validate_metric(check: dict[str, Any], prefix: str) -> None:
    source = check.get("source")
    if not isinstance(source, dict):
        raise SpecError(f"{prefix}.source must be a mapping")
    source_type = source.get("type")
    if source_type not in {"json", "csv"}:
        raise SpecError(f"{prefix}.source.type must be json or csv")
    allowed = {"type", "path", "field", "timestamp_field", "max_age_seconds"} if source_type == "json" else {
        "type", "path", "column", "timestamp_column", "max_age_seconds"
    }
    unknown = set(source) - allowed
    if unknown:
        raise SpecError(f"{prefix}.source has unknown fields: {', '.join(sorted(unknown))}")
    _require_str(source, "path", f"{prefix}.source")
    _require_str(source, "field" if source_type == "json" else "column", f"{prefix}.source")
    if "max_age_seconds" in source and (not isinstance(source["max_age_seconds"], (int, float)) or source["max_age_seconds"] < 0):
        raise SpecError(f"{prefix}.source.max_age_seconds must be non-negative")
    if "max_age_seconds" in source:
        timestamp_key = "timestamp_field" if source_type == "json" else "timestamp_column"
        _require_str(source, timestamp_key, f"{prefix}.source")
    _validate_operator(check, prefix)


def _validate_http(check: dict[str, Any], prefix: str) -> None:
    _require_str(check, "url", prefix)
    if not check["url"].startswith(("http://", "https://")):
        raise SpecError(f"{prefix}.url must use http or https")
    if "status" in check and (not isinstance(check["status"], int) or not 100 <= check["status"] <= 599):
        raise SpecError(f"{prefix}.status must be an HTTP status code")
    if not any(k in check for k in {"status", "text_contains", "json_field"}):
        raise SpecError(f"{prefix} must declare at least one HTTP assertion")
    if "json_field" in check:
        _require_str(check, "json_field", prefix)
        _validate_operator(check, prefix)
    if "timeout_seconds" in check and (not isinstance(check["timeout_seconds"], (int, float)) or check["timeout_seconds"] <= 0):
        raise SpecError(f"{prefix}.timeout_seconds must be positive")


def _validate_tcp(check: dict[str, Any], prefix: str) -> None:
    _require_str(check, "host", prefix)
    port = check.get("port")
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise SpecError(f"{prefix}.port must be 1..65535")
    if "reachable" in check and not isinstance(check["reachable"], bool):
        raise SpecError(f"{prefix}.reachable must be boolean")
    if "timeout_seconds" in check and (not isinstance(check["timeout_seconds"], (int, float)) or check["timeout_seconds"] <= 0):
        raise SpecError(f"{prefix}.timeout_seconds must be positive")


def _validate_command(check: dict[str, Any], prefix: str) -> None:
    argv = check.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(v, str) and v for v in argv):
        raise SpecError(f"{prefix}.argv must be a non-empty list of strings")
    if "cwd" in check:
        _require_str(check, "cwd", prefix)
    if "exit_code" in check and not isinstance(check["exit_code"], int):
        raise SpecError(f"{prefix}.exit_code must be an integer")
    if not any(k in check for k in {"exit_code", "stdout_contains", "stderr_contains"}):
        raise SpecError(f"{prefix} must declare at least one command assertion")
    if "timeout_seconds" in check and (not isinstance(check["timeout_seconds"], (int, float)) or check["timeout_seconds"] <= 0):
        raise SpecError(f"{prefix}.timeout_seconds must be positive")
    if "max_output_bytes" in check and (not isinstance(check["max_output_bytes"], int) or check["max_output_bytes"] <= 0):
        raise SpecError(f"{prefix}.max_output_bytes must be a positive integer")
