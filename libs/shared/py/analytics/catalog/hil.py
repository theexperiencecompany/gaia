"""Human-in-the-loop approval events."""

from typing import ClassVar, Literal

from shared.py.analytics.catalog.base import ServerEvent
from shared.py.analytics.catalog.properties import Identifier


class ApprovalDecided(ServerEvent):
    """A user decided one pending approval (decision) or a batch of them (batch, decisions, resolved)."""

    event: ClassVar[str] = "approval:decided"
    budget_per_user_day: ClassVar[int] = 10

    decision: Literal["approve", "deny"] | None = None
    batch: bool | None = None
    decisions: int | None = None
    resolved: int | None = None


class HilCardShown(ServerEvent):
    """A ledger approval card was registered, held for the run's drain or streamed."""

    event: ClassVar[str] = "hil:card_shown"
    budget_per_user_day: ClassVar[int] = 10

    approval_id: Identifier
    tool_name: Identifier
    ledger_version: int
    background: bool


#: Where an approval decision was made: a card tap, the batch review, a chat reply, or auto mode's judge.
HilDecisionVia = Literal["card", "batch", "chat", "auto"]


class HilDecisionSubmitted(ServerEvent):
    """A gated call was decided: a committed ledger decision, or auto mode's judge settling it with no card."""

    event: ClassVar[str] = "hil:decision_submitted"
    budget_per_user_day: ClassVar[int] = 10

    decision: Literal["approved", "denied"]
    tool_name: Identifier
    via: HilDecisionVia
    # Absent on an auto decision, which settles the call before any ledger row exists.
    approval_id: Identifier | None = None
    ledger_version: int | None = None
    card_age_seconds: float | None = None


class HilRevoked(ServerEvent):
    """A pending ledger approval was withdrawn by its proposer, the executor, or a cancelled run."""

    event: ClassVar[str] = "hil:revoked"
    budget_per_user_day: ClassVar[int] = 50

    approval_id: Identifier
    ledger_version: int
    revoker: Identifier


class HilResumed(ServerEvent):
    """A parked todo or workflow run was re-queued after its approval was granted."""

    event: ClassVar[str] = "hil:resumed"
    budget_per_user_day: ClassVar[int] = 50

    approval_id: Identifier
    owner_run_type: Literal["todo", "workflow"]
