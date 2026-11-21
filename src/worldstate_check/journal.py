"""Ordered acquisition records for one attempt. Playback never calls a collector."""

from __future__ import annotations

import base64
from typing import Callable

from .util import canonical_json


MAX_BUNDLE_BYTES = 64 * 1024 * 1024
_BINARY_FIELDS = {"raw", "body", "stdout", "stderr"}


class ReplayError(ValueError):
    """The supplied recording is incomplete, inconsistent or unsupported."""


class Frame:
    def __init__(self, events, *, replay=False, budget=None, legacy_window_identity=False):
        self.events = events
        self.replay = replay
        self.position = 0
        self.budget = budget
        self.legacy_window_identity = legacy_window_identity

    def sample(self, kind: str, key: str, collect: Callable):
        if self.replay:
            if self.position >= len(self.events):
                raise ReplayError("missing recorded observation")
            event = self.events[self.position]
            self.position += 1
            if (event["kind"], event["key"]) != (kind, key):
                raise ReplayError(
                    "recorded observation does not match the specification"
                )
            return {
                k: base64.b64decode(v, validate=True)
                if k in _BINARY_FIELDS and v is not None
                else v
                for k, v in event["data"].items()
            }
        data = collect()
        encoded = {
            k: base64.b64encode(v).decode("ascii") if isinstance(v, bytes) else v
            for k, v in data.items()
        }
        event = {"kind": kind, "key": key, "data": encoded}
        self.budget.charge(event)
        self.events.append(event)
        return data


def sample(ctx, kind, key, collect):
    if ctx._frame is None:
        return collect()
    return ctx._frame.sample(kind, key, collect)


class CaptureBudget:
    def __init__(self):
        self.used = 0

    def charge(self, value):
        self.used += len(canonical_json(value).encode("utf-8")) + 1
        if self.used > MAX_BUNDLE_BYTES:
            raise ValueError("recording exceeds the 64 MiB bundle limit")
