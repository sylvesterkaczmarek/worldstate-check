from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import PathBoundaryError, SpecError


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def resolve_path(root: Path, raw: str, allow_outside_root: bool) -> Path:
    try:
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = root / path
        path = path.resolve(strict=False)
        root = root.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise PathBoundaryError(f"could not resolve path: {raw}: {exc}") from exc
    if not allow_outside_root:
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise PathBoundaryError(f"path escapes verification root: {raw}") from exc
    return path


def evidence_path(path: Path, root: Path) -> str:
    """Return a portable evidence path when the path is inside the verification root."""
    try:
        path = path.resolve(strict=False)
        root = root.resolve(strict=False)
    except (OSError, RuntimeError):
        return str(path)
    try:
        relative = path.relative_to(root)
    except ValueError:
        return str(path)
    return str(relative) if str(relative) else "."


def redact_url_for_evidence(raw: str) -> str:
    """Remove userinfo, query parameters, and fragments from a URL before reporting it."""
    from urllib.parse import urlsplit, urlunsplit

    try:
        parts = urlsplit(raw)
        host = parts.hostname or ""
    except ValueError:
        return "<invalid-url>"
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    try:
        port = parts.port
    except ValueError:
        port = None
    if port is not None:
        host = f"{host}:{port}"
    return urlunsplit((parts.scheme, host, parts.path, "", ""))


def read_text_limited(path: Path, max_bytes: int) -> str:
    """Read UTF-8 text without allowing evidence input to exceed max_bytes."""
    with path.open("rb") as handle:
        raw = handle.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError(f"evidence exceeds configured read limit ({max_bytes} bytes)")
    return raw.decode("utf-8")


def strict_json_loads(raw: str) -> Any:
    if raw.startswith("\ufeff"):
        raw = raw[1:]

    def reject_constant(value: str):
        raise ValueError(f"non-standard JSON numeric constant: {value}")

    def finite_float(value: str) -> float:
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError(f"non-finite JSON number: {value}")
        return parsed

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON object key: {key}")
            result[key] = value
        return result

    return json.loads(
        raw,
        parse_constant=reject_constant,
        parse_float=finite_float,
        object_pairs_hook=unique_object,
    )


def extract_dotted(data: Any, path: str) -> Any:
    if path == "" or path is None:
        return data
    current = data
    for token in path.split("."):
        if isinstance(current, dict):
            if token not in current:
                raise KeyError(token)
            current = current[token]
        elif isinstance(current, list):
            try:
                index = int(token)
            except ValueError as exc:
                raise KeyError(token) from exc
            try:
                current = current[index]
            except IndexError as exc:
                raise KeyError(token) from exc
        else:
            raise KeyError(token)
    return current


def compare_value(observed: Any, operator: str, spec: dict[str, Any]) -> tuple[bool, Any]:
    if operator in {"eq", "ne"}:
        expected = spec.get("value")
        tolerance = spec.get("tolerance")
        if tolerance is not None:
            if not _is_number(observed) or not _is_number(expected) or not _is_number(tolerance) or float(tolerance) < 0:
                raise ValueError("tolerance comparison requires finite numeric observed, value, and tolerance")
            matched = math.isclose(float(observed), float(expected), abs_tol=float(tolerance), rel_tol=0.0)
        else:
            matched = _json_semantic_equal(observed, expected)
        return (matched if operator == "eq" else not matched), expected

    if operator in {"lt", "lte", "gt", "gte"}:
        expected = spec.get("value")
        if not _is_number(observed) or not _is_number(expected):
            raise ValueError("numeric comparison requires numeric observed and expected values")
        a = float(observed)
        b = float(expected)
        funcs = {
            "lt": lambda: a < b,
            "lte": lambda: a <= b,
            "gt": lambda: a > b,
            "gte": lambda: a >= b,
        }
        return funcs[operator](), expected

    if operator == "between":
        low = spec.get("min")
        high = spec.get("max")
        if not all(_is_number(v) for v in (observed, low, high)):
            raise ValueError("between comparison requires numeric observed, min, and max values")
        if float(low) > float(high):
            raise SpecError("between comparison requires min <= max")
        return float(low) <= float(observed) <= float(high), {"min": low, "max": high}

    if operator == "in":
        values = spec.get("values")
        if not isinstance(values, list):
            raise SpecError("operator 'in' requires a list field named 'values'")
        return any(_json_semantic_equal(observed, candidate) for candidate in values), values

    raise SpecError(f"unsupported operator: {operator}")


def parse_timestamp(value: Any) -> datetime:
    if _is_number(value):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if not isinstance(value, str):
        raise ValueError("timestamp must be an ISO-8601 string with timezone or Unix epoch number")
    normalized = value.strip()
    try:
        numeric = float(normalized)
    except ValueError:
        numeric = None
    if numeric is not None and math.isfinite(numeric):
        return datetime.fromtimestamp(numeric, tz=timezone.utc)
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        raise ValueError("ISO-8601 timestamp must include a timezone")
    return dt.astimezone(timezone.utc)


def freshness_age_seconds(value: Any, now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    dt = parse_timestamp(value)
    delta = (now - dt).total_seconds()
    if delta < -1.0:
        raise ValueError("timestamp is more than 1 second in the future")
    return max(0.0, delta)


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _json_semantic_equal(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left is right
    if _is_number(left) and _is_number(right):
        return float(left) == float(right)
    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, str) or isinstance(right, str):
        return isinstance(left, str) and isinstance(right, str) and left == right
    if isinstance(left, list) or isinstance(right, list):
        return (
            isinstance(left, list)
            and isinstance(right, list)
            and len(left) == len(right)
            and all(_json_semantic_equal(a, b) for a, b in zip(left, right))
        )
    if isinstance(left, dict) or isinstance(right, dict):
        return (
            isinstance(left, dict)
            and isinstance(right, dict)
            and left.keys() == right.keys()
            and all(_json_semantic_equal(left[key], right[key]) for key in left)
        )
    return type(left) is type(right) and left == right


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))
