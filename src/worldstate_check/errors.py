class WorldStateCheckError(Exception):
    """Base exception for controlled user-facing errors."""


class SpecError(WorldStateCheckError):
    """Raised when a verification specification is invalid."""


class PathBoundaryError(WorldStateCheckError):
    """Raised when a specification path escapes the configured root."""
