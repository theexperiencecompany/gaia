"""Per-user browser fingerprint seed.

Canvas/audio/WebGL readback values are near-unique per machine, so a bare
headless browser is identifiable by them. Perturbing them defeats that — but
only if the perturbation is *stable for one user*: a fingerprint that changes
on every request is itself a strong bot signal (a real person's browser returns
the same values every time), and one that is identical for every user makes our
whole fleet a single recognisable device.

So the seed is derived from the user id: the same person always presents the
same device, different people present different ones. It travels on a
contextvar rather than a parameter because the injection point is inside a
patched Browser-Use method that has no access to GAIA's request context.
"""

from __future__ import annotations

import contextvars
import hashlib

# Anonymous/background runs share one seed rather than randomising per call — a run
# with no user is still better off looking like a consistent device.
_DEFAULT_SEED = 0x5EED

_current_seed: contextvars.ContextVar[int] = contextvars.ContextVar(
    "browser_fingerprint_seed", default=_DEFAULT_SEED
)


def seed_for_user(user_id: str | None) -> int:
    """A stable 32-bit seed for ``user_id`` (not secret, just deterministic)."""
    if not user_id:
        return _DEFAULT_SEED
    digest = hashlib.sha256(user_id.encode()).digest()
    return int.from_bytes(digest[:4], "big")


def set_fingerprint_seed(user_id: str | None) -> contextvars.Token[int]:
    """Pin this run's fingerprint to ``user_id``. Reset with the returned token."""
    return _current_seed.set(seed_for_user(user_id))


def reset_fingerprint_seed(token: contextvars.Token[int]) -> None:
    _current_seed.reset(token)


def current_fingerprint_seed() -> int:
    return _current_seed.get()
