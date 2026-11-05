"""Bounded regular-file reads with descriptor-relative POSIX path traversal."""
from __future__ import annotations
from contextlib import contextmanager
import os
from pathlib import Path
import stat

MAX_READ_BYTES = 64 * 1024 * 1024


def _redirected(info):
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0))


@contextmanager
def parent_descriptor(path: Path):
    """Input must already have been resolved and checked against the caller's root."""
    path = Path(os.path.abspath(path))
    fd = None
    try:
        if os.name == 'posix' and os.open in os.supports_dir_fd:
            flags = getattr(os, 'O_SEARCH', getattr(os, 'O_PATH', os.O_RDONLY)) | os.O_DIRECTORY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_CLOEXEC', 0)
            fd = os.open(path.anchor, flags)
            for part in path.parts[1:-1]:
                following = os.open(part, flags, dir_fd=fd)
                os.close(fd)
                fd = following
        else:
            for parent in reversed(path.parents):
                info = parent.lstat()
                if _redirected(info) or not stat.S_ISDIR(info.st_mode):
                    raise ValueError('path contains a redirected or non-directory parent')
        yield path, fd
    finally:
        if fd is not None:
            os.close(fd)


def _stat(path, directory):
    return os.stat(path.name, dir_fd=directory, follow_symlinks=False) if directory is not None else path.lstat()


def stat_regular_path(path):
    with parent_descriptor(path) as (name, directory):
        info = _stat(name, directory)
        if _redirected(info):
            raise ValueError('path changed to a redirected file')
        return info


def read_regular_bytes(path: Path, limit: int) -> tuple[bytes, os.stat_result]:
    if type(limit) is not int or not 0 < limit <= MAX_READ_BYTES:
        raise ValueError('read limit must be an integer in [1, 67108864]')
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_CLOEXEC', 0)
    with parent_descriptor(path) as (name, directory):
        before_open = _stat(name, directory)
        if _redirected(before_open) or not stat.S_ISREG(before_open.st_mode) or before_open.st_nlink != 1:
            raise ValueError('evidence must be a singly linked regular file')
        fd = os.open(name.name, flags, dir_fd=directory) if directory is not None else os.open(name, flags)
        with os.fdopen(fd, 'rb') as handle:
            before = os.fstat(handle.fileno())
            if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                    or (before.st_dev, before.st_ino) != (before_open.st_dev, before_open.st_ino)):
                raise ValueError('evidence file identity changed before reading')
            if before.st_size > limit:
                raise ValueError(f'evidence exceeds configured read limit ({limit} bytes)')
            raw = handle.read(limit + 1)
            after = os.fstat(handle.fileno())
            current = _stat(name, directory)
        if len(raw) > limit:
            raise ValueError(f'evidence exceeds configured read limit ({limit} bytes)')
        def identity(info):
            return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_nlink)
        # Windows stat and fstat can expose different ctime semantics. Compare
        # ctime only within the same API, while binding both views by identity,
        # size, modification time and link count. See CPython issue 157671.
        if (identity(before) != identity(after)
                or before.st_ctime_ns != after.st_ctime_ns
                or identity(before_open) != identity(current)
                or before_open.st_ctime_ns != current.st_ctime_ns
                or identity(after) != identity(current)
                or _redirected(current)):
            raise ValueError('evidence file changed during observation')
    return raw, after
