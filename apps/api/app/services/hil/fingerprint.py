"""Canonical fingerprints for approval dedup (exact bytes, never fuzzy)."""

import hashlib
import json


def approval_fingerprint(tool_name: str, args: dict[str, object] | None) -> str:
    """Stable id for one exact call: same bytes in, same id out.

    Key order, nesting, and JSON round-trips do not move it; any byte of
    difference does. Rephrasing is a bypass vector, so there is deliberately
    no normalization beyond key sorting and no fuzzy match anywhere.
    """
    canonical = json.dumps({"tool": tool_name, "args": args or {}}, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:32]
