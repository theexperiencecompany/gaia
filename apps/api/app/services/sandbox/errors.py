"""Sandbox acquisition failures.

These live below both pool and lifecycle so the pool's cross-replica lock
can raise the same error the lifecycle raises, without pool importing
lifecycle (which imports pool).
"""

from app.constants.sandbox import CODE_EXECUTION_DISABLED_MESSAGE


class SandboxAcquisitionError(RuntimeError):
    """Raised when a usable sandbox cannot be obtained for a user."""


class SandboxRateLimitError(SandboxAcquisitionError):
    """Raised when the user has exhausted their sandbox-creation rate limit."""


class CodeExecutionDisabledError(SandboxAcquisitionError):
    """Raised on a self-host instance with neither an E2B key nor the opt-in local sandbox."""

    def __init__(self) -> None:
        super().__init__(CODE_EXECUTION_DISABLED_MESSAGE)
