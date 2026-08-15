"""Per-user persistent E2B sandbox lifecycle.

The agent layer interacts with this package exclusively. Shard routing, pool
caching, pause/resume, and canary verification are all encapsulated here.
"""

from app.services.sandbox.lifecycle import (
    SandboxAcquisitionError,
    acquire_sandbox,
    mark_sandbox_dead,
    pause_sandbox_for_user,
)
from app.services.sandbox.pool import get_sandbox_pool
from app.services.sandbox.shard_router import shard_for, shard_meta_url

__all__ = [
    "SandboxAcquisitionError",
    "acquire_sandbox",
    "get_sandbox_pool",
    "mark_sandbox_dead",
    "pause_sandbox_for_user",
    "shard_for",
    "shard_meta_url",
]
