"""The compose suite: the words GAIA tells the user, from items the outbox hands the composer.

Each case is the batch of items one message would cover, the mode and destination, and what the
message must do. The suite runs the production compose end to end (the comms persona and compose
rules, the structured call, the contract check, the internals guard and its one recompose, the
degraded render) and grades what reaches the user:

* one item, in each outcome's shape: done, partly done, failed, needs the user, unprompted finding,
  nothing new, interrupt, unverified;
* combined items: several subjects in one message, each said, a routine one skipped;
* the internals guard: facts that name GAIA machinery must come out as what the user gets.

Gates are mechanical: which items were included or skipped, the specifics that must be said, the
claims that must not be made, no internals in the message, a bounded number of bubbles, and not the
degraded render. Prose is never graded.

Cases keep a dev/holdout split (expected.split); tune the compose prompt on dev only.

Run: uv run --group backend python -m scripts.evals run --suite compose --concurrency 4
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from functools import partial
import json
from pathlib import Path
import time
from typing import Final, Literal

from bson import ObjectId
from pydantic import BaseModel, ConfigDict, Field

from app.agents.llm.exceptions import LLMNotConfiguredError
from app.constants.chat import ConversationSource
from app.models.outbox_models import OutboxItemDocument
from app.models.ownership_models import DeliveryPolicy
from app.models.task_report_models import TaskReport
from app.services.outbox.compose import compose
from app.services.outbox.internals_guard import leaked_internals
from app.services.outbox.models import (
    ComposeMode,
    Initiative,
    ItemState,
    NoticeOutcome,
    NoticeReport,
    OutboxReport,
    ProducerGuidance,
    ProducerKind,
    RunReport,
    Subject,
    SubjectKind,
    UrgencyClass,
)
from app.services.outbox.router import ChatChannel, InApp, Route
from scripts.evals.core.app_boot import ensure_app_registered
from scripts.evals.core.cost import EvalCostTracker, estimate_tokens
from scripts.evals.core.providers import EvalConfig, ProviderConfig
from scripts.evals.core.runner import register_suite
from scripts.evals.core.split import Split
from scripts.evals.core.transport_suite import TransportSuite
from scripts.evals.core.types import Case, CaseRun, ProviderError

DATA_DIR: Final = Path(__file__).resolve().parent.parent / "data" / "compose"
#: The clock every case's items happened at, so a "today" in a fact means one day.
EVAL_NOW: Final = datetime.fromisoformat("2026-11-13T10:00:00+00:00")
#: How long an item the case builds stays valid.
ITEM_LIFETIME: Final = timedelta(days=1)
#: The chat app account a case's chat-app destination reaches: none.
EVAL_PLATFORM_USER_ID: Final = "eval-compose"


class ComposeGate(StrEnum):
    """The gates a compose case declares beyond communicate and must_not_communicate."""

    DISPOSITIONS = "compose_dispositions"
    INTERNALS = "compose_internals"
    PARTS = "compose_parts"
    DEGRADED = "compose_degraded"


class RunItem(BaseModel):
    """An item from an executor run: the report it filed and the deliverable it handed back."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["run"]
    id: str
    subject: str
    urgency: UrgencyClass
    report: TaskReport
    result: str = ""
    initiative: Initiative = Initiative.ASKED
    review_problem: str | None = None
    interrupt_reason: str | None = None
    guidance: ProducerGuidance | None = None


class NoticeItem(BaseModel):
    """An item from a producer with no model: facts its own code wrote."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["notice"]
    id: str
    subject: str
    urgency: UrgencyClass
    producer: ProducerKind = ProducerKind.ACCOUNT
    outcome: NoticeOutcome = NoticeOutcome.INFO
    facts: list[str]
    initiative: Initiative = Initiative.SELF_INITIATED


class ComposeSetup(BaseModel):
    """A case's batch: the items one message covers, how it is for, and where it goes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: ComposeMode
    destination: ConversationSource = ConversationSource.WEB
    locale: str = "en"
    items: list[RunItem | NoticeItem] = Field(min_length=1)


class ComposeExpected(BaseModel):
    """What the message must do: which items it tells, what it says and never says, how long it is."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    category: str
    split: Split
    #: Items the message must tell, and items it must leave out; any other item is the composer's call.
    include: list[str]
    skip: list[str] = Field(default_factory=list)
    communicate: list[str] = Field(default_factory=list)
    must_not_communicate: list[str] = Field(default_factory=list)
    max_parts: int | None = None
    #: A case may expect the degraded render only when it is the thing under test.
    degraded: bool = False
    score: dict[str, list[str]]


class ComposeEndState(BaseModel):
    """What one run journals: what compose returned, and what the internals guard finds in it."""

    #: A run journaled in another shape (a forgery, an older record) reads as one that filed nothing.
    model_config = ConfigDict(extra="ignore")

    parts: list[str] = Field(default_factory=list)
    included: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    degraded: bool = False
    leaked: list[str] = Field(default_factory=list)
    composed: bool = False


def _report_of(item: RunItem | NoticeItem, user_id: str) -> OutboxReport:
    subject = Subject(
        kind=SubjectKind.ASK, id=item.id, label=item.subject, owner_conversation_id=None
    )
    if isinstance(item, NoticeItem):
        return NoticeReport(
            report_id=item.id,
            recipient=user_id,
            producer=item.producer,
            subject=subject,
            occurred_at=EVAL_NOW,
            initiative=item.initiative,
            delivery_policy=DeliveryPolicy(),
            outcome=item.outcome,
            facts=item.facts,
        )
    return RunReport(
        report_id=item.id,
        recipient=user_id,
        producer=ProducerKind.EXECUTOR,
        subject=subject,
        occurred_at=EVAL_NOW,
        initiative=item.initiative,
        delivery_policy=DeliveryPolicy(),
        report=item.report,
        result=item.result,
        review_problem=item.review_problem,
        interrupt_reason=item.interrupt_reason,
        guidance=item.guidance,
    )


def build_items(setup: ComposeSetup, user_id: str) -> list[OutboxItemDocument]:
    """Return the outbox items a case's batch is, as compose receives them."""
    return [
        OutboxItemDocument(
            user_id=user_id,
            report_id=item.id,
            report=_report_of(item, user_id),
            state=ItemState.COMPOSING,
            urgency=item.urgency,
            mode=setup.mode,
            expires_at=EVAL_NOW + ITEM_LIFETIME,
        )
        for item in setup.items
    ]


def build_route(setup: ComposeSetup) -> Route:
    """Return where the case's message goes: the GAIA app, or a chat app's direct message."""
    conversation_id = str(ObjectId())
    if setup.destination in (
        ConversationSource.WEB,
        ConversationSource.MOBILE,
        ConversationSource.DESKTOP,
    ):
        target: InApp | ChatChannel = InApp(reason="active_in_app")
    else:
        target = ChatChannel(
            source=setup.destination,
            platform_user_id=EVAL_PLATFORM_USER_ID,
            basis="recent_activity",
        )
    return Route(
        alert_conversation_id=conversation_id, recorded_in=(conversation_id,), target=target
    )


def grade_compose(expected: ComposeExpected, state: ComposeEndState) -> dict[ComposeGate, float]:
    """Return each compose gate's score from what the run journaled; a run that composed nothing fails all."""
    if not state.composed:
        return dict.fromkeys(ComposeGate, 0.0)
    results = {
        ComposeGate.DISPOSITIONS: set(expected.include) <= set(state.included)
        and set(expected.skip) <= set(state.skipped),
        ComposeGate.INTERNALS: not state.leaked,
        ComposeGate.PARTS: expected.max_parts is None or len(state.parts) <= expected.max_parts,
        ComposeGate.DEGRADED: state.degraded is expected.degraded,
    }
    return {gate: float(kept) for gate, kept in results.items()}


def gate_score(gate: ComposeGate, case: Case, run: CaseRun) -> float:
    """Score one gate of a journaled run; a run that journaled nothing scores 0."""
    if not run.end_state:
        return 0.0
    expected = ComposeExpected.model_validate(case.expected)
    return grade_compose(expected, ComposeEndState.model_validate(run.end_state))[gate]


class ComposeTransport:
    """One case: the production compose over the case's items, then the guard over what it said."""

    async def run(
        self,
        case: Case,
        cfg: EvalConfig,
        tracker: EvalCostTracker,
        provider: ProviderConfig,
    ) -> CaseRun:
        del cfg, tracker
        started = time.monotonic()
        await ensure_app_registered()
        setup = ComposeSetup.model_validate(case.setup)
        user_id = str(ObjectId())
        try:
            composed = await compose(
                build_items(setup, user_id),
                user_id=user_id,
                mode=setup.mode,
                destination=build_route(setup),
                locale=setup.locale,
            )
        except LLMNotConfiguredError as e:
            raise ProviderError(provider.name, f"no model for compose: {e}") from e
        state = ComposeEndState(
            parts=composed.parts,
            included=composed.included,
            skipped=composed.skipped,
            degraded=composed.degraded,
            leaked=await leaked_internals(user_id, composed.parts),
            composed=True,
        )
        told = "\n".join(composed.parts)
        print(f"[compose] {case.id}: included={state.included} skipped={state.skipped}")
        return CaseRun(
            case_id=case.id,
            provider=provider.name,
            model=provider.model,
            messages=[
                {"role": "user", "content": "\n".join(i.subject for i in setup.items)},
                *({"role": "assistant", "content": part} for part in composed.parts),
            ],
            end_state=state.model_dump(mode="json"),
            text=told,
            tokens_in=estimate_tokens(json.dumps(case.setup)),
            tokens_out=estimate_tokens(told),
            duration_s=time.monotonic() - started,
        )


EXTRA: Final = {gate.value: partial(gate_score, gate) for gate in ComposeGate}


@register_suite("compose")
class ComposeSuite(TransportSuite):
    name = "compose"
    project = "gaia-compose"
    label = "Compose (the words the user is told)"
    data_dir = DATA_DIR
    extra = EXTRA
    transport_type = ComposeTransport
