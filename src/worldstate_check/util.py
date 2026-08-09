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
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = root / path
    path = path.resolve(strict=False)
    root = root.resolve(strict=False)
    if not allow_outside_root:
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise PathBoundaryError(f"path escapes verification root: {raw}") from exc
    return path


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
        if tolerance is not None and isinstance(observed, (int, float)) and isinstance(expected, (int, float)):
            if isinstance(observed, bool) or isinstance(expected, bool):
                raise SpecError("tolerance cannot be used with booleans")
            matched = math.isclose(float(observed), float(expected), abs_tol=float(tolerance), rel_tol=0.0)
        else:
            matched = observed == expected
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
        return float(low) <= float(observed) <= float(high), {"min": low, "max": high}

    if operator == "in":
        values = spec.get("values")
        if not isinstance(values, list):
            raise SpecError("operator 'in' requires a list field named 'values'")
        return observed in values, values

    raise SpecError(f"unsupported operator: {operator}")


def parse_timestamp(value: Any) -> datetime:
    if _is_number(value):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if not isinstance(value, str):
        raise ValueError("timestamp must be an ISO-8601 string or Unix epoch number")
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def freshness_age_seconds(value: Any, now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    dt = parse_timestamp(value)
    delta = (now - dt).total_seconds()
    if delta < -1.0:
        raise ValueError("timestamp is more than 1 second in the future")
    return max(0.0, delta)


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))
