"""Schemas for the browser-automation capability.

* ``BrowserCardSnapshot`` union — the ``browser_task_data`` SSE card payloads
  the runner streams (session header, per-step timeline, live-view handoff
  prompt, final result). The frontend folds the accumulated array by ``kind``.
* ``HandoffRequest`` — internal runner→tool contract for a mid-run handoff.
"""

from datetime import datetime
from typing import Any, Literal

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
    """Immutable snapshot of one browser session's state for the task record."""

    kind: Literal[BrowserEventKind.SESSION] = BrowserEventKind.SESSION
    task: str
    status: BrowserSessionStatus
    session_id: str | None = None
    live_view_url: str | None = None
    detail: str | None = None


class BrowserAction(BaseModel):
    """One action the browser agent invoked in a step — its name and arguments.

    The agent's own tool call. Kept structured (not flattened to a string) so the
    chat thread can render it like any other tool call, and so captions can use
    the real target ("Opening github.com") instead of just the verb.
    """

    name: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    # The element's own text, resolved from the DOM the agent was looking at —
    # "Add to cart" rather than the bare index the action carries. Grounded in
    # the page, so a caption states what was really touched, not what the model
    # claimed it would touch.
    target: str | None = None
    # Where on the step's screenshot this action acted, as (x, y) fractions of the
    # viewport in [0, 1] — so the UI can draw a pulse at the click/type point
    # without knowing the frame's pixel size. None for actions with no on-screen
    # target (navigate, scroll, wait) or a target scrolled out of view.
    point: tuple[float, float] | None = None


class BrowserActionOutput(BaseModel):
    """The result text of one executed browser action, by its position in the step.

    A step's action rows show what the agent *called*; this carries what each
    call *returned* (extracted text, or an error) so the tool thread can show the
    outcome, not just the attempt. Positional because it is matched back to the
    action row the mirror already emitted for the same step and position.
    """

    position: int
    output: str


class BrowserStepSnapshot(BaseModel):
    """Immutable snapshot of one agent step for the task record."""

    kind: Literal[BrowserEventKind.STEP] = BrowserEventKind.STEP
    index: int
    goal: str
    actions: list[BrowserAction] = Field(default_factory=list)
    url: str | None = None
    title: str | None = None
    screenshot: str | None = None
    # Wall-clock the agent spent reaching this step (previous step's LLM think +
    # action execution). Surfaced in the card so speed is visible per step.
    elapsed_ms: int | None = None


class BrowserHandoffSnapshot(BaseModel):
    """The agent paused at a sensitive step and needs the human to take over."""

    kind: Literal[BrowserEventKind.HANDOFF] = BrowserEventKind.HANDOFF
    handoff_id: str
    category: SensitiveCategory = SensitiveCategory.NONE
    reason: str
    session_id: str | None = None
    live_view_url: str | None = None
    #: Required, not defaulted: a snapshot that forgot to say it had been
    #: resolved would silently render as still-pending to the user.
    status: HandoffStatus


class BrowserResultSnapshot(BaseModel):
    """Immutable snapshot of the final result for the task record."""

    kind: Literal[BrowserEventKind.RESULT] = BrowserEventKind.RESULT
    status: BrowserSessionStatus
    success: bool
    summary: str
    steps: int = 0
    # A recap slideshow of every step's screenshot — surfaced on success or failure.
    replay_url: str | None = None


BrowserCardSnapshot = (
    BrowserSessionSnapshot | BrowserStepSnapshot | BrowserHandoffSnapshot | BrowserResultSnapshot
)


class HandoffRecord(BaseModel):
    """The Redis-side state of one live-view handoff (see ``services/browser/handoff.py``)."""

    status: HandoffStatus
    user_id: str
    conversation_id: str
    reason: str = ""
    # Optional free-text note the user sends back when continuing ("just grab the
    # photo, skip the login"). Delivered to the agent as guidance on resume.
    message: str | None = None


class HandoffOutcome(BaseModel):
    """How a handoff resolved: the terminal status plus the user's optional note."""

    status: HandoffStatus
    message: str | None = None


class LiveCodeRecord(BaseModel):
    """What a short live-view code resolves to: the session it opens and its owner."""

    session_id: str
    user_id: str


class ReplayRecord(BaseModel):
    """What a replay code opens: the screenshots the run actually uploaded."""

    session_id: str
    steps: int
    # The CDN URLs that really exist. Empty on codes minted before these were
    # stored, which fall back to deriving them from the session id.
    shots: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Sensitive-action classifier
# ---------------------------------------------------------------------------


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
    message: str | None = Field(default=None, max_length=2000)


class HandoffDecisionResponse(BaseModel):
    """Outcome of a handoff decision: accepted with note, cancelled, or errored."""

    handoff_id: str
    status: HandoffStatus


class LiveViewTokenResponse(BaseModel):
    """A short-lived takeover token for opening the cross-origin live view."""

    token: str
    expires_in: int = Field(description="Seconds until the token expires.")


class BrowserTaskFrame(BaseModel):
    """One recap frame: a step screenshot plus what the agent was doing."""

    url: str
    caption: str | None = None


class BrowserTaskResponse(BaseModel):
    """One row in the user's browser task history (settings)."""

    id: str
    task: str
    status: BrowserSessionStatus
    success: bool
    steps: int
    created_at: datetime | None
    conversation_id: str
    source: str
    frames: list[BrowserTaskFrame] = Field(
        default_factory=list, description="Recap frames (screenshot + caption), in order."
    )


class BrowserLoginResponse(BaseModel):
    """A saved browser login. Only the domain is exposed — never the encrypted state."""

    domain: str
    updated_at: datetime | None
    expires_at: datetime | None = None
