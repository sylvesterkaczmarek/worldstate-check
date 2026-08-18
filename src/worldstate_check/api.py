from __future__ import annotations

from pathlib import Path

from .engine import verify
from .loader import load_spec
from .models import VerificationContext, VerificationReport


def verify_spec(
    spec: str | Path,
    *,
    root: str | Path | None = None,
    allow_outside_root: bool = False,
    allow_command: bool = False,
    allow_network: bool = False,
    wait_seconds: float = 0.0,
    poll_interval: float = 0.5,
) -> VerificationReport:
    """Verify a WorldState Check specification using the same engine as the CLI."""
    spec_path = Path(spec).resolve()
    specification = load_spec(spec_path)
    verification_root = Path(root).resolve() if root is not None else spec_path.parent
    context = VerificationContext(
        spec_path=spec_path,
        root=verification_root,
        allow_outside_root=allow_outside_root,
        allow_command=allow_command,
        allow_network=allow_network,
    )
    return verify(
        specification,
        context,
        wait_seconds=wait_seconds,
        poll_interval=poll_interval,
    )
