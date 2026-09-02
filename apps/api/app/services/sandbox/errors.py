"""Sandbox acquisition failures.

These live below both ``pool`` and ``lifecycle`` so the pool's cross-replica lock
can raise the same error the lifecycle raises, without ``pool`` importing
``lifecycle`` (which imports ``pool``).
"""


class SandboxAcquisitionError(RuntimeError):
    """Raised when a usable sandbox cannot be obtained for a user."""


class SandboxRateLimitError(SandboxAcquisitionError):
    """Raised when the user has exhausted their sandbox-creation rate limit."""
