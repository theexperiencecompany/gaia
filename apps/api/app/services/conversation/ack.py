"""Instant reaction: one JEV call decides whether a user's message gets an emoji tap, and which.

decide_reaction is the one I/O function and never raises: every failure is no reaction,
recorded with its reason. reaction_request and read_reaction are pure, so the eval sends and
grades the same bytes production does.
"""

import asyncio
import time
from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator

from app.constants.reactions import (
    REACTION_CONTEXT_MAX_CHARS,
    REACTION_EMOJI_INSTRUCTIONS,
    REACTION_EMOJI_QUESTION_KEY,
    REACTION_KIND_CRITERIA,
    REACTION_KIND_INSTRUCTIONS,
    REACTION_KIND_QUESTION_KEY,
    REACTION_PALETTE,
    REACTION_STATE_PREVIOUS_ASSISTANT,
    REACTION_STATE_USER_MESSAGE,
    REACTION_THRESHOLD,
    REACTION_TIMEOUT_SECONDS,
    REACTION_UPSET_CRITERIA,
    REACTION_UPSET_INSTRUCTIONS,
    REACTION_UPSET_QUESTION_KEY,
    ReactionKind,
    ReactionOutcome,
    ReactionReason,
)
from app.models.jev_models import JevDecisionsResponse
from app.services.hil.jev_client import jev_failure, post_decisions
from app.services.latency_metrics import observe_reaction_ack_decision
from shared.py.wide_events import log


class ReactionDecision(BaseModel):
    """Whether to tap an emoji on the message; emoji is set exactly when reason is REACTED."""

    model_config = ConfigDict(frozen=True)

    emoji: str | None = None
    upset: float | None = None
    p_task: float | None = None
    p_sign_off: float | None = None
    reason: ReactionReason

    @model_validator(mode="after")
    def _emoji_only_when_reacted(self) -> Self:
        if (self.emoji is not None) != (self.reason is ReactionReason.REACTED):
            raise ValueError(f"emoji {self.emoji!r} contradicts reason {self.reason.value!r}")
        return self

    @property
    def outcome(self) -> ReactionOutcome:
        return ReactionOutcome.REACTED if self.emoji else ReactionOutcome.NONE


def reaction_request(
    message_text: str, previous_assistant_text: str
) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    """Return the Decisions state and the three questions for one user message."""
    state: dict[str, object] = {
        REACTION_STATE_USER_MESSAGE: message_text,
        REACTION_STATE_PREVIOUS_ASSISTANT: previous_assistant_text[:REACTION_CONTEXT_MAX_CHARS],
    }
    questions: dict[str, dict[str, object]] = {
        REACTION_UPSET_QUESTION_KEY: {
            "type": "noul",
            "instructions": REACTION_UPSET_INSTRUCTIONS,
            "criteria": dict(REACTION_UPSET_CRITERIA),
        },
        REACTION_KIND_QUESTION_KEY: {
            "type": "choice",
            "instructions": REACTION_KIND_INSTRUCTIONS,
            "criteria": {kind.value: meaning for kind, meaning in REACTION_KIND_CRITERIA.items()},
        },
        REACTION_EMOJI_QUESTION_KEY: {
            "type": "choice",
            "instructions": REACTION_EMOJI_INSTRUCTIONS,
            "criteria": dict(REACTION_PALETTE),
        },
    }
    return state, questions


def read_reaction(body: JevDecisionsResponse) -> ReactionDecision:
    """Apply the reaction rule to JEV's answers; raise ValueError on a missing or malformed answer."""
    upset = body.noul(REACTION_UPSET_QUESTION_KEY)
    kind = body.choice(REACTION_KIND_QUESTION_KEY, set(ReactionKind), label="reaction kind ")
    emoji = body.choice(REACTION_EMOJI_QUESTION_KEY, REACTION_PALETTE, label="reaction emoji ")
    probabilities = kind.probabilities
    if not probabilities or not probabilities.keys() <= set(ReactionKind):
        raise ValueError(f"reaction kind answer has no usable probabilities: {probabilities!r}")
    p_task = probabilities.get(ReactionKind.TASK, 0.0)
    p_sign_off = probabilities.get(ReactionKind.SIGN_OFF, 0.0)
    calm, wordless = 1.0 - upset, p_task + p_sign_off
    if calm * wordless >= REACTION_THRESHOLD:
        reason = ReactionReason.REACTED
    elif calm < REACTION_THRESHOLD:
        reason = ReactionReason.UPSET
    elif wordless < REACTION_THRESHOLD:
        reason = ReactionReason.NEEDS_WORDS
    else:
        reason = ReactionReason.BELOW_THRESHOLD
    return ReactionDecision(
        emoji=emoji.choice if reason is ReactionReason.REACTED else None,
        upset=upset,
        p_task=p_task,
        p_sign_off=p_sign_off,
        reason=reason,
    )


async def decide_reaction(message_text: str, previous_assistant_text: str) -> ReactionDecision:
    """Ask JEV whether to react to the message and with which emoji; any failure is no reaction."""
    started = time.perf_counter()
    try:
        async with asyncio.timeout(REACTION_TIMEOUT_SECONDS):
            body = await post_decisions(*reaction_request(message_text, previous_assistant_text))
        decision = read_reaction(body)
    except Exception as e:
        # A missing tap-back is the whole degradation: the reply still comes.
        reason = ReactionReason(jev_failure(e))
        if reason is not ReactionReason.UNCONFIGURED:
            log.warning(
                "reaction_ack.jev_failed",
                reason=reason.value,
                error=str(e)[:300],
                error_type=type(e).__name__,
            )
        decision = ReactionDecision(reason=reason)
    _record(decision, latency_ms=int((time.perf_counter() - started) * 1000))
    return decision


def _record(decision: ReactionDecision, *, latency_ms: int) -> None:
    observe_reaction_ack_decision(outcome=decision.outcome.value, reason=decision.reason.value)
    log.set(
        reaction_ack={
            "outcome": decision.outcome.value,
            "reason": decision.reason.value,
            "emoji": decision.emoji,
            "upset": decision.upset,
            "p_task": decision.p_task,
            "p_sign_off": decision.p_sign_off,
            "latency_ms": latency_ms,
        }
    )
