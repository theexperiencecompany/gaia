"""reaction-ack suite: does the instant reaction tap the right messages, and never an upset one.

120 synthetic messages, each labelled must_not_react, should_react (with the emojis that fit) or
may_react. Every case goes through the production builder (reaction_request), the production
client (post_decisions) and the production rule (read_reaction), so the suite grades the bytes
production sends.

Run:  uv run --group backend python -m scripts.evals run --suite reaction-ack --concurrency 4

Promotion bar: zero reactions on must_not_react.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
import time
from typing import Final

import httpx
from pydantic import BaseModel

from app.constants.hil import HIL_JEV_MODEL_NAME
from app.constants.reactions import ReactionReason
from app.models.jev_models import JevDecisionsResponse
from app.services.conversation.ack import ReactionDecision, reaction_request, read_reaction
from app.services.hil.jev_client import JevUnconfiguredError, post_decisions
from scripts.evals.core.cost import EvalCostTracker
from scripts.evals.core.providers import EvalConfig, ProviderConfig
from scripts.evals.core.runner import register_suite
from scripts.evals.core.transport_suite import TransportSuite
from scripts.evals.core.types import Case, CaseRun, ProviderError

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "reaction-ack"
REACTION_GATE: Final = "reaction_expect"


class ReactionExpect(StrEnum):
    """What a case allows: no tap, a tap from its emojis, or either."""

    MUST_NOT_REACT = "must_not_react"
    SHOULD_REACT = "should_react"
    MAY_REACT = "may_react"


class ReactionCaseSetup(BaseModel):
    """A case's setup block: the user's message and the assistant message before it."""

    message: str
    previous_assistant: str = ""


class ReactionEndState(BaseModel):
    """What one graded case journals: the decision and JEV's whole answer."""

    decision: ReactionDecision
    response: dict[str, object]


def reaction_expect(case: Case, run: CaseRun) -> float:
    """Pass a run whose decision the label allows; a run with no decision fails."""
    decision = (run.end_state or {}).get("decision")
    if not isinstance(decision, dict) or "reason" not in decision:
        return 0.0
    emoji = decision.get("emoji")
    match ReactionExpect(case.expected["expect"]):
        case ReactionExpect.MUST_NOT_REACT:
            return 1.0 if emoji is None else 0.0
        case ReactionExpect.SHOULD_REACT:
            return 1.0 if emoji in case.expected["emojis"] else 0.0
        case ReactionExpect.MAY_REACT:
            return 1.0


EXTRA = {REACTION_GATE: reaction_expect}


def graded_decision(body: JevDecisionsResponse) -> ReactionDecision:
    """Return the decision production takes from an answer; an unreadable one is no reaction."""
    try:
        return read_reaction(body)
    except ValueError:
        return ReactionDecision(reason=ReactionReason.MALFORMED)


class ReactionTransport:
    """One message through the production builder, client and rule, journaled whole."""

    async def run(
        self,
        case: Case,
        cfg: EvalConfig,
        tracker: EvalCostTracker,
        provider: ProviderConfig,
    ) -> CaseRun:
        del cfg, tracker
        started = time.monotonic()
        setup = ReactionCaseSetup.model_validate(case.setup)
        try:
            body = await post_decisions(*reaction_request(setup.message, setup.previous_assistant))
        except (JevUnconfiguredError, httpx.HTTPError, ValueError) as e:
            raise ProviderError(provider.name, f"decisions API failed: {e}") from e
        decision = graded_decision(body)
        duration_s = time.monotonic() - started
        end_state = ReactionEndState(
            decision=decision, response=body.model_dump(mode="json", exclude_none=True)
        )
        graded = decision.emoji or decision.reason.value
        print(f"{case.id}: want={case.expected['expect']} got={graded} ({duration_s:.2f}s)")
        tokens_in, tokens_out = body.tokens()
        return CaseRun(
            case_id=case.id,
            provider=provider.name,
            model=HIL_JEV_MODEL_NAME,
            messages=[
                {"role": "user", "content": setup.message},
                {"role": "assistant", "content": graded},
            ],
            end_state=end_state.model_dump(mode="json"),
            text=graded,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            duration_s=duration_s,
        )


@register_suite("reaction-ack")
class ReactionAckSuite(TransportSuite):
    name = "reaction-ack"
    project = "gaia-reaction-ack"
    label = "Instant reaction (JEV tap-back)"
    data_dir = DATA_DIR
    extra = EXTRA
    transport_type = ReactionTransport
