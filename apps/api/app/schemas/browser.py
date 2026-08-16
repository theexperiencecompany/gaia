"""Schemas for the browser-automation capability.

* ``BrowserCardSnapshot`` union — the ``browser_task_data`` SSE card payloads
  the runner streams (session header, per-step timeline, live-view handoff
  prompt, final result). The frontend folds the accumulated array by ``kind``.
* ``SensitiveActionVerdict`` — structured output of the LLM sensitivity judge.
* ``HandoffRequest`` — internal runner→tool contract for a mid-run handoff.
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.constants.browser import (
    BrowserEventKind,
    BrowserSessionStatus,
    HandoffDecision,
    HandoffStatus,
    SensitiveCategory,
)

# ---------------------------------------------------------------------------
# SSE card snapshots (data of a `browser_task_data` tool_data entry)
# ---------------------------------------------------------------------------


class BrowserSessionSnapshot(BaseModel):
    kind: Literal[BrowserEventKind.SESSION] = BrowserEventKind.SESSION
    task: str
    status: BrowserSessionStatus
    session_id: str | None = None
    live_view_url: str | None = None
    detail: str | None = None


class BrowserStepSnapshot(BaseModel):
    kind: Literal[BrowserEventKind.STEP] = BrowserEventKind.STEP
    index: int
    goal: str
    action: str | None = None
    url: str | None = None
    title: str | None = None
    screenshot: str | None = None


class BrowserHandoffSnapshot(BaseModel):
    """The agent paused at a sensitive step and needs the human to take over."""

    kind: Literal[BrowserEventKind.HANDOFF] = BrowserEventKind.HANDOFF
    handoff_id: str
    category: SensitiveCategory = SensitiveCategory.NONE
    reason: str
    session_id: str | None = None
    live_view_url: str | None = None
    status: HandoffStatus = HandoffStatus.PENDING


class BrowserResultSnapshot(BaseModel):
    kind: Literal[BrowserEventKind.RESULT] = BrowserEventKind.RESULT
    status: BrowserSessionStatus
    success: bool
    summary: str
    steps: int = 0


BrowserCardSnapshot = (
    BrowserSessionSnapshot | BrowserStepSnapshot | BrowserHandoffSnapshot | BrowserResultSnapshot
)


class HandoffRecord(BaseModel):
    """The Redis-side state of one live-view handoff (see ``services/browser/handoff.py``)."""

    status: HandoffStatus
    user_id: str
    conversation_id: str
    reason: str = ""


class LiveCodeRecord(BaseModel):
    """What a short live-view code resolves to: the session it opens and its owner."""

    session_id: str
    user_id: str


# ---------------------------------------------------------------------------
# Sensitive-action classifier
# ---------------------------------------------------------------------------


class SensitiveActionVerdict(BaseModel):
    """Structured verdict from the sensitivity judge for one planned step."""

    requires_approval: bool = Field(
        description=(
            "True only if the planned action submits a payment, enters "
            "credentials/OTP, or performs an irreversible/hard-to-undo action."
        )
    )
    category: SensitiveCategory = Field(
        default=SensitiveCategory.NONE,
        description="Which kind of sensitive action this is, or 'none' if safe.",
    )
    reason: str = Field(
        default="",
        description="One short sentence: what the agent is about to do and why it is sensitive.",
    )


# ---------------------------------------------------------------------------
# Internal runner→tool contract
# ---------------------------------------------------------------------------


class HandoffRequest(BaseModel):
    """The runner asks the tool to hand off to the human for a sensitive step."""

    category: SensitiveCategory = SensitiveCategory.NONE
    reason: str


class HandoffDecisionRequest(BaseModel):
    """Body of ``POST /browser/handoffs/{handoff_id}/decision``."""

    decision: HandoffDecision


class HandoffDecisionResponse(BaseModel):
    handoff_id: str
    status: HandoffStatus


class LiveViewTokenResponse(BaseModel):
    """A short-lived takeover token for opening the cross-origin live view."""

    token: str
    expires_in: int = Field(description="Seconds until the token expires.")
