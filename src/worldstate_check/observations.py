"""One bounded local-file observation per resolved path and evaluation attempt."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import stat

from .errors import PathBoundaryError
from .safe_io import MAX_READ_BYTES, read_regular_bytes, stat_regular_path
from .util import evidence_path, resolve_path


@dataclass(frozen=True)
class FileObservation:
    exists: bool | None
    regular: bool
    raw: bytes | None
    error: str | None
    observed_at: str
    size: int | None = None
    sha256: str | None = None

    def evidence(self, path, root):
        result = {'path': evidence_path(path, root), 'observed_at': self.observed_at}
        if self.size is not None: result['size_bytes'] = self.size
        if self.sha256 is not None: result['source_sha256'] = self.sha256
        return result


def capture(path, limit):
    when = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    try:
        info = stat_regular_path(path)
    except FileNotFoundError:
        return FileObservation(False, False, None, None, when)
    except (OSError, ValueError) as exc:
        return FileObservation(None, False, None, f'{type(exc).__name__}: {exc}', when)
    regular = stat.S_ISREG(info.st_mode)
    if not limit:
        return FileObservation(True, regular, None, None, when, info.st_size)
    try:
        raw, final = read_regular_bytes(path, limit)
    except (OSError, ValueError) as exc:
        return FileObservation(True, regular, None, f'{type(exc).__name__}: {exc}', when, info.st_size)
    return FileObservation(True, True, raw, None, when, final.st_size, hashlib.sha256(raw).hexdigest())


def local_input(check):
    if check['type'] == 'file':
        content = any(key in check for key in ('contains','not_contains','sha256'))
        return check['path'], check.get('max_read_bytes', 1_048_576) if content else 0
    if check['type'] == 'json': return check['path'], check.get('max_read_bytes', 1_048_576)
    if check['type'] == 'metric':
        source = check['source']
        return source['path'], source.get('max_read_bytes', 16 * 1024 * 1024)
    return None


class ObservationSession:
    def __init__(self, spec, ctx):
        self.paths = {}
        self.limits = {}
        self.observed = {}
        self.retained_bytes = 0
        for check in spec['checks']:
            item = local_input(check)
            if item is None: continue
            raw, limit = item
            try:
                path = resolve_path(ctx.root, raw, ctx.allow_outside_root)
            except (ValueError, PathBoundaryError) as exc:
                self.paths[raw] = exc
                continue
            self.paths[raw] = path
            self.limits[path] = max(self.limits.get(path, 0), limit)

    def get(self, path):
        if path not in self.observed:
            limit = self.limits[path]
            remaining = MAX_READ_BYTES - self.retained_bytes
            if limit and remaining <= 0:
                item = FileObservation(None, False, None, 'per-attempt evidence budget exhausted', datetime.now(timezone.utc).isoformat())
            else:
                item = capture(path, min(limit, remaining) if limit else 0)
            if item.raw is not None: self.retained_bytes += len(item.raw)
            self.observed[path] = item
        return self.observed[path]


def resolve_evidence_path(ctx, raw):
    if ctx._session is not None and raw in ctx._session.paths:
        value = ctx._session.paths[raw]
        if isinstance(value, Exception): raise value
        return value
    return resolve_path(ctx.root, raw, ctx.allow_outside_root)


def observation(path, ctx, limit=0):
    return ctx._session.get(path) if ctx._session is not None else capture(path, limit)


def observation_text(item, limit):
    if item.exists is False: raise FileNotFoundError('evidence file does not exist')
    if item.error is not None: raise ValueError(item.error)
    if item.raw is None: raise ValueError('no regular-file content was observed')
    if len(item.raw) > limit: raise ValueError(f'evidence exceeds configured read limit ({limit} bytes)')
    return item.raw.decode('utf-8')
