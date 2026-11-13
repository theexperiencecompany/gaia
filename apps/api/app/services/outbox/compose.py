"""Compose: one structured model call that words a message for a batch of items.

No graph, no tools, no end hooks: the model sees the items, the destination thread
read-only, and what GAIA already sent, and returns a disposition per item and the
bubbles. A result that drops an item that must be said is refused once with the
violation stated; after that the items are said plainly (the degraded render), loudly.
Only record_in_thread writes to a comms thread, under the thread lock.
"""

from dataclasses import dataclass, field, replace
import json
from typing import TypedDict, cast

from langchain_core.messages import AIMessage, AnyMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from app.agents.core.graph_manager import GraphManager
from app.agents.core.thread_lock import comms_thread_lock
from app.agents.core.thread_writes import with_message_ids
from app.agents.llm.client import ainvoke_structured
from app.agents.prompts.compose_prompts import COMPOSE_RULES, OUTCOME_REPLY_SHAPES
from app.agents.templates.agent_template import get_comms_static_prompt
from app.constants.log_tags import LogTag
from app.constants.outbound import OUTBOUND_TTL_SECONDS_DEFAULT, OUTBOUND_TTL_SECONDS_GREETING
from app.constants.outbox import (
    COMPOSE_EARLIER_RUN_CHARS,
    COMPOSE_EARLIER_RUNS,
    COMPOSE_LEDGER_MESSAGES,
    COMPOSE_MAX_ATTEMPTS,
    COMPOSE_THREAD_SNAPSHOT_MESSAGES,
    OUTBOX_COMPOSE_LABEL,
)
from app.db.repositories.outbox_items import outbox_items_repository
from app.db.repositories.outbox_messages import outbox_messages_repository
from app.models.chat_models import ConversationSource
from app.models.outbox_models import OutboxItemDocument
from app.schemas.outbound import OutboundAttachment
from app.services.outbox.internals_guard import leaked_internals
from app.services.outbox.judge_models import Moment
from app.services.outbox.metrics import OUTBOX_COMPOSE_DEGRADED, OUTBOX_INTERNALS_LEAKED
from app.services.outbox.models import (
    ComposeMode,
    ComposeResult,
    Disposition,
    DropReason,
    ItemState,
    NoticeOutcome,
    NoticeReport,
    RunReport,
    facts_of,
)
from app.services.outbox.policy import must_include
from app.services.outbox.prerendered import (
    GREETING_KINDS,
    PrerenderedKind,
    prerendered_parts,
    prerendered_text,
)
from app.services.outbox.router import ChatChannel, ProactiveTarget, Route
from shared.py.wide_events import log


@dataclass(frozen=True, slots=True)
class Composed:
    """The words of one message: bubbles, which items they say, and whether they are the degraded render."""

    parts: list[str]
    included: list[str]
    skipped: list[str]
    degraded: bool
    #: Files the message carries, sent after its bubbles.
    attachments: list[OutboundAttachment] = field(default_factory=list)
    #: How long a chat app's queue holds the message before dropping it undelivered.
    ttl_seconds: int = OUTBOUND_TTL_SECONDS_DEFAULT
    #: Why skipped items were not told, when it was not the composer's own judgement.
    skip_reason: DropReason = DropReason.COMPOSE_SKIPPED


class _ThreadValues(TypedDict, total=False):
    messages: list[AnyMessage]


def _destination_source(target: ProactiveTarget) -> ConversationSource:
    return target.source if isinstance(target, ChatChannel) else ConversationSource.WEB


def _must_say(item: OutboxItemDocument) -> bool:
    if item.urgency is None:
        raise ValueError(f"outbox item {item.report_id} reached compose without an urgency")
    return must_include(item.urgency, item.report)


def _item_view(item: OutboxItemDocument) -> dict[str, object]:
    report = item.report
    view: dict[str, object] = {
        "item_id": item.report_id,
        "subject": report.subject.label,
        "must_say": _must_say(item),
    }
    verdict = item.judgement.verdict if item.judgement else None
    if verdict is not None and verdict.suspicious:
        view["suspicious"] = True
    if verdict is not None and verdict.moment is Moment.SOFTEN:
        view["soften"] = True
    match report:
        case RunReport():
            view["report"] = report.report.model_dump(mode="json", exclude_none=True)
            view["result"] = report.result
            view["how_to_say"] = _how_to_say(report)
            if report.review_problem is not None:
                view["review_problem"] = report.review_problem
            if report.interrupt_reason is not None:
                view["interrupt_reason"] = report.interrupt_reason
            if report.guidance is not None:
                view["guidance"] = report.guidance.model_dump(mode="json", exclude_none=True)
            if report.decided_approvals:
                view["decided_approvals"] = [
                    decided.model_dump(mode="json") for decided in report.decided_approvals
                ]
        case NoticeReport():
            view["outcome"] = report.outcome.value
            view["facts"] = report.facts
    return view


def _how_to_say(report: RunReport) -> str:
    outcome = report.report.outcome
    if outcome is None:
        raise ValueError(f"run report {report.report_id} reached compose without an outcome")
    return OUTCOME_REPLY_SHAPES[outcome]


def _is_verbatim(item: OutboxItemDocument) -> bool:
    report = item.report
    return (
        isinstance(report, RunReport) and report.guidance is not None and report.guidance.verbatim
    )


def _squashed(text: str) -> str:
    return " ".join(text.split())


async def _earlier_run_line(past: OutboxItemDocument) -> str:
    when = past.report.occurred_at.isoformat(timespec="minutes")
    if past.state is ItemState.DROPPED:
        reason = past.drop_reason.value if past.drop_reason is not None else "dropped"
        return f"{when}: kept quiet ({reason})"
    if past.compose_attempt_id is None:
        raise ValueError(f"sent outbox item {past.report_id} names no message")
    message = await outbox_messages_repository.get_by_attempt(past.user_id, past.compose_attempt_id)
    if message is None:
        raise ValueError(f"sent outbox item {past.report_id} has no ledger message")
    return f"{when}: told them: {' '.join(message.parts)[:COMPOSE_EARLIER_RUN_CHARS]}"


async def _earlier_runs(items: list[OutboxItemDocument]) -> dict[str, list[str]]:
    """Return, per item of a recurring producer, what GAIA did with its last runs, oldest first."""
    earlier: dict[str, list[str]] = {}
    for item in items:
        series = item.report.subject.series
        if series is None:
            continue
        past = await outbox_items_repository.list_settled_of_series(
            item.user_id, series, before=item.report.occurred_at, limit=COMPOSE_EARLIER_RUNS
        )
        earlier[item.report_id] = [await _earlier_run_line(p) for p in reversed(past)]
    return earlier


def _is_conversational(message: BaseMessage) -> bool:
    return isinstance(message, HumanMessage | AIMessage) and isinstance(message.content, str)


async def _thread_snapshot(conversation_id: str) -> list[dict[str, str]]:
    """Return the destination thread's recent exchange, read-only."""
    graph = await GraphManager.get_graph("comms_agent")
    state = await graph.aget_state(
        cast(RunnableConfig, {"configurable": {"thread_id": conversation_id}})
    )
    values: _ThreadValues = cast(_ThreadValues, state.values or {})
    recent = [m for m in values.get("messages", []) if _is_conversational(m)]
    return [
        {"from": "user" if isinstance(m, HumanMessage) else "gaia", "text": str(m.content)}
        for m in recent[-COMPOSE_THREAD_SNAPSHOT_MESSAGES:]
    ]


def _validate(result: ComposeResult, items: list[OutboxItemDocument]) -> str | None:
    """Return how result breaks the compose contract, or None when it keeps it."""
    by_id = {item.report_id: item for item in items}
    listed = [d.item_id for d in result.dispositions]
    if sorted(listed) != sorted(by_id):
        missing = sorted(by_id.keys() - set(listed))
        unknown = sorted(set(listed) - by_id.keys())
        return (
            f"dispositions must name each item exactly once; missing {missing}, unknown {unknown}, "
            f"or repeated"
        )
    chosen = {d.item_id: d.action for d in result.dispositions}
    for item_id, item in by_id.items():
        if _must_say(item) and chosen[item_id] is not Disposition.INCLUDE:
            return f"item {item_id} must be said and cannot be skipped"
    told = _squashed(" ".join(result.parts))
    for item_id, item in by_id.items():
        if (
            chosen[item_id] is Disposition.INCLUDE
            and _is_verbatim(item)
            and _squashed(cast(RunReport, item.report).result) not in told
        ):
            return f"item {item_id} must be told exactly as its result is written"
    includes = any(action is Disposition.INCLUDE for action in chosen.values())
    spoken = [part for part in result.parts if part.strip()]
    if includes and not spoken:
        return "an item is included but there are no parts"
    if not includes and result.parts:
        return "every item is skipped, so parts must be empty"
    return None


def _degraded_parts(items: list[OutboxItemDocument], locale: str) -> list[str]:
    lines = [prerendered_text(PrerenderedKind.COMPOSE_DEGRADED, locale)]
    for item in items:
        if not _must_say(item):
            continue
        facts = (
            cast(RunReport, item.report).result
            if _is_verbatim(item)
            else "; ".join(facts_of(item.report))
        )
        lines.append(f"{item.report.subject.label}: {facts}")
    return ["\n".join(lines)]


def _said_as_written(item: OutboxItemDocument) -> bool:
    """Whether the item's producer wrote its words, or it only carries a file: no model words it."""
    report = item.report
    return isinstance(report, NoticeReport) and (
        report.prerendered is not None
        or report.outcome is NoticeOutcome.PROGRESS
        or bool(report.artifacts)
    )


def _written_parts(report: NoticeReport, locale: str) -> list[str]:
    if report.prerendered is not None:
        return prerendered_parts(report.prerendered, locale)
    if report.artifacts:
        return []
    return ["\n".join(report.facts)]


async def compose(
    items: list[OutboxItemDocument],
    *,
    user_id: str,
    mode: ComposeMode,
    destination: Route,
    locale: str,
) -> Composed:
    """Say items as one message: the producers' own words as they wrote them, the rest worded as comms would."""
    written = [item for item in items if _said_as_written(item)]
    to_word = [item for item in items if not _said_as_written(item)]
    written_reports = [item.report for item in written if isinstance(item.report, NoticeReport)]
    attachments = [artifact for report in written_reports for artifact in report.artifacts]
    written_parts = [part for report in written_reports for part in _written_parts(report, locale)]
    ttl_seconds = (
        OUTBOUND_TTL_SECONDS_GREETING
        if any(
            r.prerendered is not None and r.prerendered.kind in GREETING_KINDS
            for r in written_reports
        )
        else OUTBOUND_TTL_SECONDS_DEFAULT
    )
    if not to_word:
        return Composed(
            parts=written_parts,
            included=[item.report_id for item in written],
            skipped=[],
            degraded=False,
            attachments=attachments,
            ttl_seconds=ttl_seconds,
        )
    worded = await _word(
        to_word,
        user_id=user_id,
        mode=mode,
        destination=destination,
        locale=locale,
    )
    return replace(
        worded,
        parts=[*worded.parts, *written_parts],
        included=[*worded.included, *(item.report_id for item in written)],
        attachments=attachments,
        ttl_seconds=ttl_seconds,
    )


async def _word(
    items: list[OutboxItemDocument],
    *,
    user_id: str,
    mode: ComposeMode,
    destination: Route,
    locale: str,
) -> Composed:
    source = _destination_source(destination.target)
    recent_sent = await outbox_messages_repository.recent_sent(
        user_id, limit=COMPOSE_LEDGER_MESSAGES
    )
    context: dict[str, object] = {
        "mode": mode.value,
        "locale": locale,
        "destination": source.value,
        "items": [_item_view(item) for item in items],
        "recent_thread": await _thread_snapshot(destination.alert_conversation_id),
        "already_sent": [part for message in recent_sent for part in message.parts],
    }
    if destination.requested_unavailable is not None:
        context["requested_channel_unavailable"] = destination.requested_unavailable.value
    if earlier_runs := await _earlier_runs(items):
        context["earlier_runs"] = earlier_runs
    messages: list[BaseMessage] = [
        SystemMessage(content=get_comms_static_prompt(source.value) + COMPOSE_RULES),
        HumanMessage(content=json.dumps(context, ensure_ascii=False)),
    ]
    await _flag_leaking_facts(items, user_id)
    violation: str | None = None
    leaked: list[str] = []
    for _ in range(COMPOSE_MAX_ATTEMPTS):
        if violation is not None:
            messages.append(
                HumanMessage(content=f"That answer broke a rule: {violation}. Answer again.")
            )
        result = await ainvoke_structured(ComposeResult, messages, label=OUTBOX_COMPOSE_LABEL)
        violation = _validate(result, items)
        if violation is None and (leaked := await leaked_internals(user_id, result.parts)):
            violation = (
                f"the message names GAIA internals ({', '.join(leaked)}); "
                "say what the user gets, never how it works"
            )
        if violation is None:
            return _composed(result)
    if leaked:
        return _leak_unresolved(items, leaked, user_id=user_id, locale=locale)
    OUTBOX_COMPOSE_DEGRADED.inc()
    log.error(
        f"{LogTag.NOTIFICATION} Outbox compose broke its contract twice; sending the degraded render",
        user_id=user_id,
        item_count=len(items),
        violation=violation,
    )
    return _degraded(items, locale)


async def _flag_leaking_facts(items: list[OutboxItemDocument], user_id: str) -> None:
    """Log and count a producer whose facts name internals; the words are still composed, never raised on."""
    for item in items:
        if leaked := await leaked_internals(user_id, facts_of(item.report)):
            OUTBOX_INTERNALS_LEAKED.labels(where="facts").inc()
            log.warning(
                f"{LogTag.NOTIFICATION} A report's facts name GAIA internals (producer bug)",
                user_id=user_id,
                report_id=item.report_id,
                producer=item.report.producer.value,
                leaked=leaked,
            )


def _degraded(items: list[OutboxItemDocument], locale: str) -> Composed:
    return Composed(
        parts=_degraded_parts(items, locale),
        included=[item.report_id for item in items if _must_say(item)],
        skipped=[item.report_id for item in items if not _must_say(item)],
        degraded=True,
    )


def _leak_unresolved(
    items: list[OutboxItemDocument], leaked: list[str], *, user_id: str, locale: str
) -> Composed:
    """Say what must be said from the facts alone and drop the rest: the composer kept naming internals."""
    OUTBOX_INTERNALS_LEAKED.labels(where="composed").inc()
    log.error(
        f"{LogTag.NOTIFICATION} Outbox compose kept naming GAIA internals through the recompose",
        user_id=user_id,
        item_count=len(items),
        leaked=leaked,
    )
    return replace(_degraded(items, locale), skip_reason=DropReason.LEAK_UNRESOLVED)


def _composed(result: ComposeResult) -> Composed:
    included = [d.item_id for d in result.dispositions if d.action is Disposition.INCLUDE]
    skipped = [d.item_id for d in result.dispositions if d.action is Disposition.SKIP]
    return Composed(
        parts=[part.strip() for part in result.parts if part.strip()],
        included=included,
        skipped=skipped,
        degraded=False,
    )


async def record_in_thread(conversation_id: str, text: str) -> None:
    """Append what GAIA told the user to the conversation's comms thread, under the thread lock; raises on failure."""
    async with comms_thread_lock(conversation_id):
        graph = await GraphManager.get_graph("comms_agent")
        await graph.aupdate_state(
            cast(RunnableConfig, {"configurable": {"thread_id": conversation_id}}),
            {"messages": with_message_ids([AIMessage(content=text)])},
            as_node="tools",
        )
