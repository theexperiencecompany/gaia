"""Typed shapes the hil-reply suite reads from its YAML cases and writes to its journal."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from app.constants.hil import ReplyChoice
from app.models.message_models import MessageDict


class ReplyBackend(StrEnum):
    """Which classifier a run drove — HIL_REPLY_EVAL_BACKEND, journaled on every row."""

    JEV = "jev"
    LLM = "llm"


class ReplyCaseAction(BaseModel):
    """One pending action as the case file declares it."""

    summary: str
    args: dict[str, object] = Field(default_factory=dict)


class ReplyCaseSetup(BaseModel):
    """A case's setup block: the user's reply to one or more pending actions."""

    reply: str
    actions: list[ReplyCaseAction] = Field(min_length=1)
    history: list[MessageDict] = Field(default_factory=list)


class JevReplyJournal(BaseModel):
    """The per-action JEV verdicts a row was graded on — what the offline sweep regrades."""

    choices: list[ReplyChoice]
    confidences: list[float]
    probabilities: list[dict[str, float]]


class ReplyEndState(BaseModel):
    """What one graded case journals; jev is present only on JEV-backend rows."""

    outcome: str
    backend: ReplyBackend
    questions_version: str
    dangerous: bool
    reply: str
    jev: JevReplyJournal | None = None
