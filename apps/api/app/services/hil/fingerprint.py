"""Canonical fingerprints for approval dedup (exact bytes, never fuzzy)."""

import hashlib
import json


def approval_fingerprint(
    tool_name: str, args: dict[str, object] | None, account: str | None = None
) -> str:
    """Stable id for one exact call: same bytes in, same id out.

    Key order, nesting, and JSON round-trips do not move it; any byte of
    difference does. Rephrasing is a bypass vector, so there is deliberately
    no normalization beyond key sorting and no fuzzy match anywhere.
    """
    call: dict[str, object] = {"tool": tool_name, "args": args or {}}
    # Only when named, so a primary-account call keeps the id it always had.
    if account:
        call["account"] = account
    canonical = json.dumps(call, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:32]
