from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Any

from .models import REPORT_SCHEMA, CheckStatus, VerificationReport
from .util import canonical_json, parse_timestamp, read_text_limited, strict_json_loads, validate_json_tree


def safe_text(value):
    return ''.join(character if character.isprintable() else ascii(character)[1:-1] for character in str(value))


def _finite_nonnegative(value):
    return type(value) in (int, float) and value >= 0 and (type(value) is int or math.isfinite(value))


def validate_report_data(data):
    """Verify structure and recompute the declared verdict. This is not authentication."""
    validate_json_tree(data, max_nodes=3_000_000, max_depth=96)
    required = {'schema_version','task','verdict','started_at','finished_at','duration_ms','attempts',
                'required_passed','required_total','results'}
    if not isinstance(data, dict) or not required <= data.keys() or data.keys() - required - {'specification_sha256'}:
        raise ValueError('unsupported or incomplete report structure')
    if type(data['schema_version']) is not int or data['schema_version'] not in (1, REPORT_SCHEMA):
        raise ValueError('unsupported report schema')
    if not isinstance(data['task'], str) or not data['task'].strip() or not data['task'].isprintable():
        raise ValueError('invalid report task')
    if type(data['attempts']) is not int or data['attempts'] < 1 or not _finite_nonnegative(data['duration_ms']):
        raise ValueError('invalid report attempt count or duration')
    if not all(isinstance(data[key], str) and 'T' in data[key] for key in ('started_at', 'finished_at')):
        raise ValueError('report timestamps must be strings')
    if parse_timestamp(data['finished_at']) < parse_timestamp(data['started_at']):
        raise ValueError('report finish precedes its start')
    fingerprint = data.get('specification_sha256')
    if fingerprint is not None and (not isinstance(fingerprint, str) or re.fullmatch(r'[0-9a-f]{64}', fingerprint) is None):
        raise ValueError('invalid specification hash')
    rows = data['results']
    if not isinstance(rows, list) or not rows:
        raise ValueError('report must contain check results')
    seen, required_statuses = set(), []
    fields = {'check_id','check_type','required','status','summary','expected','observed','evidence','error','duration_ms'}
    if data["schema_version"] == REPORT_SCHEMA:
        fields.add("reason_code")
        if fingerprint is None:
            raise ValueError("schema-2 reports require a specification hash")
    reasons = {
        "PASS": ("satisfied",),
        "FAIL": ("stale", "field_missing", "postcondition_failed"),
        "UNKNOWN": ("field_missing", "incomplete_window", "inconclusive"),
    }
    for row in rows:
        if not isinstance(row, dict) or row.keys() != fields:
            raise ValueError('invalid check result structure')
        identifier = row['check_id']
        if not isinstance(identifier, str) or not identifier.strip() or not identifier.isprintable() or identifier in seen:
            raise ValueError('invalid or duplicate check identifier')
        seen.add(identifier)
        if row['check_type'] not in ('file','json','metric','http','tcp','command','window'):
            raise ValueError('unknown reported check type')
        if type(row['required']) is not bool or row['status'] not in ('PASS','FAIL','UNKNOWN'):
            raise ValueError('invalid check requirement or status')
        if "reason_code" in row and row["reason_code"] not in reasons[row["status"]]:
            raise ValueError("reason code contradicts check status")
        if (not isinstance(row['summary'], str) or not isinstance(row['evidence'], dict)
                or (row['error'] is not None and not isinstance(row['error'], str))
                or not _finite_nonnegative(row['duration_ms'])):
            raise ValueError('invalid check metadata')
        if row['status'] == 'PASS' and row['error'] is not None:
            raise ValueError('passing result contains an unresolved error')
        if data["schema_version"] == REPORT_SCHEMA and "value_references" in row["evidence"]:
            references = row["evidence"]["value_references"]
            if not isinstance(references, dict) or not references or references.keys() - {"expected", "observed", "evidence", "summary", "error"}:
                raise ValueError("invalid bounded value references")
            for key, reference in references.items():
                if (not isinstance(reference, dict) or reference.keys() != {"encoding", "type", "size_bytes", "sha256"}
                        or reference["encoding"] != "canonical-json-utf8" or type(reference["size_bytes"]) is not int
                        or reference["size_bytes"] < 1 or reference["type"] not in ("list", "dict", "str", "float", "int", "bool", "NoneType")
                        or not isinstance(reference["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", reference["sha256"])):
                    raise ValueError("invalid bounded value reference metadata")
                if key in ("expected", "observed") and row[key] is not None:
                    raise ValueError("referenced value also appears inline")
        if row['required']: required_statuses.append(row['status'])
    if not required_statuses:
        raise ValueError('report must contain a required result')
    for key, expected in (('required_total',len(required_statuses)),('required_passed',required_statuses.count('PASS'))):
        if type(data[key]) is not int or data[key] != expected:
            raise ValueError('report summary counts do not match evidence')
    verdict = 'NOT_VERIFIED' if 'FAIL' in required_statuses else 'UNCERTAIN' if 'UNKNOWN' in required_statuses else 'VERIFIED'
    if data['verdict'] != verdict:
        raise ValueError('report verdict does not match its required observations')


def report_payload(report: VerificationReport) -> dict[str, Any]:
    payload = report.to_dict()
    validate_report_data(payload)
    digest = hashlib.sha256(canonical_json(payload).encode('utf-8')).hexdigest()
    payload['report_sha256'] = digest
    return payload


def verify_json_report(path: Path) -> bool:
    try:
        data = strict_json_loads(read_text_limited(path, 64 * 1024 * 1024), max_nodes=3_000_000, max_depth=96)
        if not isinstance(data, dict): return False
        claimed = data.pop('report_sha256', None)
        if not isinstance(claimed, str) or re.fullmatch(r'[0-9a-f]{64}', claimed) is None: return False
        actual = hashlib.sha256(canonical_json(data).encode('utf-8')).hexdigest()
        if not hmac.compare_digest(actual, claimed): return False
        validate_report_data(data)
        return True
    except (ValueError, TypeError, RecursionError, UnicodeError, OverflowError):
        return False


def validate_report_destination(path, protected=()):
    path = Path(path).expanduser()
    if path.is_symlink(): raise ValueError('report destination must not be a symlink')
    resolved = path.resolve()
    for source in protected:
        source = Path(source).expanduser()
        if resolved == source.resolve() or (path.exists() and source.exists() and path.samefile(source)):
            raise ValueError('report destination would overwrite specification or evidence input')
    return path


def write_json_report(report: VerificationReport, path: Path, *, protected=()) -> Path:
    path = validate_report_destination(path, protected)
    content = canonical_json(report_payload(report)) + '\n'
    return write_atomic_text(path, content, protected=protected)


def write_atomic_text(path, content, *, protected=()):
    path = validate_report_destination(path, protected)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n', dir=path.parent,
                                         prefix='.'+path.name+'.', suffix='.tmp', delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        validate_report_destination(path, protected)
        os.replace(temporary, path)
    finally:
        if temporary is not None: temporary.unlink(missing_ok=True)
    return path.resolve()


def _display_value(row, name):
    reference = row["evidence"].get("value_references", {}).get(name)
    if reference is not None:
        return f'({reference["type"]}, {reference["size_bytes"]} bytes, sha256={reference["sha256"]})'
    value = row[name]
    if name in ("summary", "error"):
        return safe_text(value)
    return safe_text(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False))


def render_text(report: VerificationReport) -> str:
    lines = [f'WorldState Check: {safe_text(report.task)}', '']
    for result in report.results:
        row = result.to_dict(inline_bytes=report.inline_value_bytes)
        requirement = 'required' if result.required else 'optional'
        lines.append(f'[{result.status.value:<7}] {safe_text(result.check_id)} ({safe_text(result.check_type)}, {requirement})')
        lines.append(f'          {_display_value(row, "summary")}')
        if result.status is not CheckStatus.PASS:
            references = row["evidence"].get("value_references", {})
            for name in ("observed", "expected", "error"):
                if name == "error" and result.error == result.summary:
                    continue
                if row[name] is not None or name in references:
                    lines.append(f'          {name}: {_display_value(row, name)}')
    lines.extend(['',f'VERDICT: {report.verdict.value}', f'Required checks: {report.required_passed}/{report.required_total} passed',f'Attempts: {report.attempts}'])
    return '\n'.join(lines)
