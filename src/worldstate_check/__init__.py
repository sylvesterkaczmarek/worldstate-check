"""WorldState Check public API."""

from importlib.metadata import PackageNotFoundError, version

from .api import verify_spec, verify_spec_data
from .errors import SpecError
from .models import VerificationReport, Verdict

try:
    __version__ = version("worldstate-check")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"

__all__ = [
    "SpecError",
    "VerificationReport",
    "Verdict",
    "verify_spec",
    "verify_spec_data",
]
