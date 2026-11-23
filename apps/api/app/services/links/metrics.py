"""Count every short-link mint by how it ended, the signal the link-mint alert reads.

minted is a new link stored under a fresh slug; failed is a link GAIA was attaching to
something it handed over and could not mint. Both series are created at zero when the API
and the worker start serving metrics, so the first failure after a restart is an
increase increase() can see.
"""

from enum import StrEnum

from prometheus_client import Counter

from app.services.storage.metrics import _register_once


class LinkMintOutcome(StrEnum):
    """How one mint ended."""

    MINTED = "minted"
    FAILED = "failed"


LINK_MINT_TOTAL = _register_once(
    "gaia_link_mint_total",
    lambda: Counter(
        name="gaia_link_mint_total",
        documentation="Short-link mints by outcome; failed is a GAIA-attached link that could not be minted",
        labelnames=("outcome",),
    ),
)


def create_link_mint_series() -> None:
    """Create every link-mint series at zero, so its first increment is visible."""
    for outcome in LinkMintOutcome:
        LINK_MINT_TOTAL.labels(outcome.value)
