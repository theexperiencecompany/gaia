"""Compose: one structured model call that words a message for a batch of items.

No graph, no tools, no end hooks: the model sees the items, the destination thread
read-only, and what GAIA already sent, and returns a disposition per item and the
bubbles. A result that drops an item that must be said is refused once with the
violation stated; after that the items are said plainly (the degraded render), loudly.
Only record_in_thread writes to a comms thread, under the thread lock.
"""

from dataclasses import dataclass
import json
from typing import TypedDict, cast

from langchain_core.messages import AIMessage, AnyMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from app.agents.core.graph_manager import GraphManager
from app.agents.core.thread_lock import comms_thread_lock
from app.agents.core.thread_writes import with_message_ids
from app.agents.llm.client import ainvoke_structured
from app.agents.prompts.compose_prompts import COMPOSE_RULES
from app.agents.templates.agent_template import get_comms_static_prompt
from app.constants.log_tags import LogTag
from app.constants.outbox import (
    COMPOSE_LEDGER_MESSAGES,
    COMPOSE_MAX_ATTEMPTS,
    COMPOSE_THREAD_SNAPSHOT_MESSAGES,
    OUTBOX_COMPOSE_LABEL,
)
from app.db.repositories.outbox_messages import outbox_messages_repository
from app.models.chat_models import ConversationSource
from app.models.outbox_models import OutboxItemDocument
from app.services.outbox.metrics import OUTBOX_COMPOSE_DEGRADED
from app.services.outbox.models import (
    ComposeMode,
    ComposeResult,
    Disposition,
    NoticeReport,
    OutboxReport,
    RunReport,
)
from app.services.outbox.policy import must_include
from app.services.outbox.prerendered import PrerenderedKind, prerendered_text
from app.services.outbox.router import ChatChannel, ProactiveTarget
from shared.py.wide_events import log


@dataclass(frozen=True, slots=True)
class Composed:
    """The words of one message: bubbles, which items they say, and whether they are the degraded render."""

    parts: list[str]
    included: list[str]
    skipped: list[str]
    degraded: bool


class _ThreadValues(TypedDict, total=False):
    messages: list[AnyMessage]


def _destination_source(target: ProactiveTarget) -> ConversationSource:
    return target.source if isinstance(target, ChatChannel) else ConversationSource.WEB


def _must_say(item: OutboxItemDocument) -> bool:
    if item.urgency is None:
        raise ValueError(f"outbox item {item.report_id} reached compose without an urgency")
    return must_include(item.urgency, item.report)


def _facts_of(report: OutboxReport) -> list[str]:
    if isinstance(report, RunReport):
        return [fact.text for fact in report.report.facts]
    return report.facts


def _item_view(item: OutboxItemDocument) -> dict[str, object]:
    report = item.report
    view: dict[str, object] = {
        "item_id": item.report_id,
        "subject": report.subject.label,
        "must_say": _must_say(item),
    }
    match report:
        case RunReport():
            view["report"] = report.report.model_dump(mode="json", exclude_none=True)
        case NoticeReport():
            view["outcome"] = report.outcome.value
            view["facts"] = report.facts
    return view


def _is_conversational(message: BaseMessage) -> bool:
    return isinstance(message, HumanMessage | AIMessage) and isinstance(message.content, str)


async def _thread_snapshot(conversation_id: str) -> list[dict[str, str]]:
    """Return the destination thread's recent exchange, read-only."""
    graph = await GraphManager.get_graph("comms_agent")
    state = await graph.aget_state(
        cast(RunnableConfig, {"configurable": {"thread_id": conversation_id}})
    )
    values = cast(_ThreadValues, state.values or {})
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
        if _must_say(item):
            lines.append(f"{item.report.subject.label}: " + "; ".join(_facts_of(item.report)))
    return ["\n".join(lines)]


async def compose(
    items: list[OutboxItemDocument],
    *,
    user_id: str,
    mode: ComposeMode,
    target: ProactiveTarget,
    conversation_id: str,
    locale: str,
) -> Composed:
    """Word one message for items, as comms would say it in the destination thread."""
    source = _destination_source(target)
    recent_sent = await outbox_messages_repository.recent_sent(
        user_id, limit=COMPOSE_LEDGER_MESSAGES
    )
    context = {
        "mode": mode.value,
        "locale": locale,
        "destination": source.value,
        "items": [_item_view(item) for item in items],
        "recent_thread": await _thread_snapshot(conversation_id),
        "already_sent": [part for message in recent_sent for part in message.parts],
    }
    messages: list[BaseMessage] = [
        SystemMessage(content=get_comms_static_prompt(source.value) + COMPOSE_RULES),
        HumanMessage(content=json.dumps(context, ensure_ascii=False)),
    ]
    violation: str | None = None
    for _ in range(COMPOSE_MAX_ATTEMPTS):
        if violation is not None:
            messages.append(
                HumanMessage(content=f"That answer broke a rule: {violation}. Answer again.")
            )
        result = await ainvoke_structured(ComposeResult, messages, label=OUTBOX_COMPOSE_LABEL)
        violation = _validate(result, items)
        if violation is None:
            return _composed(result)
    OUTBOX_COMPOSE_DEGRADED.inc()
    log.error(
        f"{LogTag.NOTIFICATION} Outbox compose broke its contract twice; sending the degraded render",
        user_id=user_id,
        item_count=len(items),
        violation=violation,
    )
    return Composed(
        parts=_degraded_parts(items, locale),
        included=[item.report_id for item in items if _must_say(item)],
        skipped=[item.report_id for item in items if not _must_say(item)],
        degraded=True,
    )


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
