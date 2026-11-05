from __future__ import annotations
from typing import Any

from worldstate_check.errors import PathBoundaryError
from worldstate_check.models import CheckStatus, VerificationContext
from worldstate_check.observations import resolve_evidence_path, observation, observation_text
from .base import timed_result, unknown


def run_file_check(check: dict[str, Any], ctx: VerificationContext):
    try:
        path = resolve_evidence_path(ctx, check['path'])
    except PathBoundaryError as exc:
        return unknown(check, str(exc))

    def evaluate():
        content_required = any(key in check for key in ('contains', 'not_contains', 'sha256'))
        limit = check.get('max_read_bytes', 1_048_576)
        item = observation(path, ctx, limit if content_required else 0)
        evidence = item.evidence(path, ctx.root)
        expected = {key: check[key] for key in ('exists','contains','not_contains','sha256') if key in check}
        observed = {'exists': item.exists}
        failures, errors = [], []
        if item.exists is None:
            return CheckStatus.UNKNOWN, 'file existence could not be established', expected, observed, evidence, item.error
        if 'exists' in check and item.exists != check['exists']:
            failures.append(f'exists={item.exists}')
        if content_required:
            if not item.exists:
                failures.append('file content unavailable because the path does not exist')
            elif item.error:
                errors.append(item.error)
            elif not item.regular:
                errors.append('content evidence is not a regular file')
            elif item.raw is None or len(item.raw) > limit:
                errors.append(f'file exceeds configured read limit ({limit} bytes)')
            else:
                if 'sha256' in check:
                    expected['sha256'] = check['sha256'].lower()
                    observed['sha256'] = item.sha256
                    if item.sha256 != expected['sha256']: failures.append('sha256 mismatch')
                if 'contains' in check or 'not_contains' in check:
                    try:
                        content = observation_text(item, limit)
                    except (ValueError, UnicodeError) as exc:
                        errors.append(f'could not read file as UTF-8: {exc}')
                    else:
                        for key in ('contains','not_contains'):
                            if key not in check: continue
                            matched = check[key] in content if key == 'contains' else check[key] not in content
                            observed[key] = matched
                            if not matched: failures.append('required text missing' if key == 'contains' else 'forbidden text present')
        status = CheckStatus.FAIL if failures else CheckStatus.UNKNOWN if errors else CheckStatus.PASS
        summary = '; '.join(failures + errors) if failures or errors else 'file postcondition satisfied'
        return status, summary, expected, observed, evidence, '; '.join(errors) or None

    return timed_result(check, evaluate)
