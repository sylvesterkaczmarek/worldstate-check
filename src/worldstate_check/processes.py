"""Bounded capture and best-effort cleanup for opted-in trusted verifier commands."""
from __future__ import annotations
from dataclasses import dataclass
import os
import signal
import subprocess
import tempfile
import time


@dataclass(frozen=True)
class CommandOutcome:
    returncode: int | None
    stdout: bytes
    stderr: bytes
    stdout_bytes: int
    stderr_bytes: int
    timed_out: bool
    output_limited: bool


def _stop(proc):
    if os.name == 'posix':
        try: os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError: pass
    elif proc.poll() is None:
        try:
            subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'], stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5, check=False)
        except (OSError, subprocess.SubprocessError): pass
    if proc.poll() is None:
        proc.kill()
    proc.wait()


def run_bounded(argv, *, cwd, env, timeout, max_bytes):
    # Spooling avoids unbounded Python capture. Size polling is not a disk quota.
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                stdout=out, stderr=err, shell=False, start_new_session=os.name == 'posix')
        deadline = time.monotonic() + timeout
        timed_out = output_limited = False
        try:
            while True:
                if max(os.fstat(out.fileno()).st_size, os.fstat(err.fileno()).st_size) > max_bytes:
                    output_limited = True
                    break
                if proc.poll() is not None: break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    break
                try: proc.wait(timeout=min(.02, remaining))
                except subprocess.TimeoutExpired: pass
        finally:
            _stop(proc)
        out_size, err_size = os.fstat(out.fileno()).st_size, os.fstat(err.fileno()).st_size
        output_limited = output_limited or max(out_size, err_size) > max_bytes
        out.seek(0); err.seek(0)
        return CommandOutcome(None if timed_out or output_limited else proc.returncode,
                              out.read(max_bytes), err.read(max_bytes), out_size, err_size,
                              timed_out, output_limited)
