"""Container-aware memory probe backing the host's memory-based admission control.

Reports (used_mb, limit_mb) for the environment the browser host runs in. The
limit that matters is the one the OOM killer enforces — the container's cgroup
memory limit (docker mem_limit), not the physical host RAM — so admission
gates on that. Off a container (dev/mac) it falls back to system memory, and an
explicit BROWSER_HOST_MEMORY_LIMIT_MB pins or caps the budget anywhere.
"""

from __future__ import annotations

from pathlib import Path

import psutil

from app.config.browser_host_settings import browser_host_settings

# cgroup v2 (unified) then v1 (legacy) locations.
_V2_CURRENT = Path("/sys/fs/cgroup/memory.current")
_V2_MAX = Path("/sys/fs/cgroup/memory.max")
_V1_USAGE = Path("/sys/fs/cgroup/memory/memory.usage_in_bytes")
_V1_LIMIT = Path("/sys/fs/cgroup/memory/memory.limit_in_bytes")

_BYTES_PER_MB = 1024 * 1024
# cgroup "no limit" is expressed as the literal "max" (v2) or a near-INT64 sentinel
# (v1); treat anything this large as unlimited rather than a real ceiling.
_UNLIMITED_BYTES = 1 << 62


def _read_int(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def _cgroup_used_and_limit_bytes() -> tuple[int, int | None] | None:
    """Return (used, limit) from the cgroup, limit None when unlimited; None off-cgroup."""
    for usage_path, limit_path in ((_V2_CURRENT, _V2_MAX), (_V1_USAGE, _V1_LIMIT)):
        used = _read_int(usage_path)
        if used is not None:
            limit = _read_int(limit_path)
            return used, (limit if limit is not None and limit < _UNLIMITED_BYTES else None)
    return None


def memory_usage_mb() -> tuple[float, float]:
    """Return the current (used_mb, limit_mb) for the host's environment.

    Prefers the cgroup (the container's real, OOM-enforced budget); falls back to
    system memory when no cgroup limit is readable. BROWSER_HOST_MEMORY_LIMIT_MB
    caps the detected limit (or supplies it when none is detectable).
    """
    override = browser_host_settings.BROWSER_HOST_MEMORY_LIMIT_MB
    cgroup = _cgroup_used_and_limit_bytes()

    if cgroup is not None and cgroup[1] is not None:
        used = cgroup[0] / _BYTES_PER_MB
        limit = cgroup[1] / _BYTES_PER_MB
        return used, (min(limit, float(override)) if override else limit)

    # No cgroup limit (unlimited, or not in a container): system memory for the
    # ceiling, the cgroup's own used figure when we have it, else system used.
    vm = psutil.virtual_memory()
    used = (
        (cgroup[0] / _BYTES_PER_MB)
        if cgroup is not None
        else (vm.total - vm.available) / _BYTES_PER_MB
    )
    limit = float(override) if override else vm.total / _BYTES_PER_MB
    return used, limit
