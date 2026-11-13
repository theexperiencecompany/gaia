"""Per-suite dev identities for the live chat transport.

quality.ChatTransport is the harness's one transport over send + events
(core.live_chat), the wire every client uses. It pins
its dev user to the quality suite's email, which is right for one suite and wrong
for three: the comms agent runs a memory node on every turn, so suites sharing an
identity would recall each other's cases across runs, and a safety suite's
injection payloads are the last thing a comms case should have in its context.

:class:SuiteChatTransport binds that same transport to a suite's own dev user.
It overrides only the identity step; reading the events, multi-turn threading
and token estimation stay in the one implementation.

The HIL suite does NOT use this: an approval flow is send, decide, keep
following, which is a different shape of run, not a different user (see hil.py).
"""

from __future__ import annotations

from scripts.evals.suites.quality import ChatTransport


class SuiteChatTransport(ChatTransport):
    """The live chat transport, scoped to one suite's own identity space.

    prefix only names the suite so its users are recognisable; the identity
    itself is minted per case by the base transport, so comms, safety and
    quality cannot bleed state into each other or into their own later cases.
    """

    def __init__(self, prefix: str) -> None:
        super().__init__()
        self.user_prefix = prefix
