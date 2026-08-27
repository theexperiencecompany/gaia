"""LangChain memory tools backed by the GAIA memory engine (plan F4).

Every tool streams one structured event to the frontend via the LangGraph
stream writer under the single registry key ``memory_data``. The payload is
discriminated on ``action`` — these exact JSON shapes are the frontend
contract (the tool cards mirror them):

    add      {"action": "add", "memories": [MemoryEntry], "folder": str,
              "outcome": "new" | "updated" | "extended" | "duplicate",
              "message": str}
    search   {"action": "search", "query": str, "folder": str | null,
              "memories": [MemoryEntry], "message": str}
    update   {"action": "update", "memories": [MemoryEntry], "message": str}
    forget   {"action": "forget", "memory_id": str, "reason": str,
              "message": str}
    journal  {"action": "journal", "query": str | null,
              "episodes": [{"date": "YYYY-MM-DD",
                            "entries": [{"time": str | null, "text": str,
                                         "source": str | null}],
                            "summary": str | null}],
              "message": str}
    document {"action": "document",
              "document": {"doc_type": str, "content": str, "version": int,
                           "updated_at": str},
              "updated": bool, "message": str}

``MemoryEntry`` items are serialized exactly as the REST API serializes
``app.models.memory_models.MemoryEntry`` (``model_dump(mode="json")``,
snake_case keys), with ``content`` capped at MEMORY_TOOL_CONTENT_MAX_CHARS.
Document ``content`` is capped at MEMORY_TOOL_DOCUMENT_MAX_CHARS. ``doc_type``
is a ``MemoryDocType`` value (``user_md`` ... ``people_md``).
"""

from datetime import date as date_type
from typing import Annotated, Any, Literal, TypeAlias, TypedDict

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.config import get_stream_writer

from app.constants.memory import (
    DEFAULT_RECALL_LIMIT,
    FREE_MEMORY_FACT_LIMIT,
    MEMORY_DOC_FILENAMES,
    MEMORY_TOOL_CONTENT_MAX_CHARS,
    MEMORY_TOOL_DOCUMENT_MAX_CHARS,
    MemoryDocType,
    MemorySourceType,
    ReconcileOutcome,
)
from app.decorators import with_doc
from app.decorators.rate_limiting import build_rate_limit_card
from app.memory.engine import memory_engine
from app.memory.ingestion import MemoryLimitReachedError
from app.memory.retrieval import EpisodeHit
from app.memory.user_time import local_today
from app.models.memory_models import MemoryDocument, MemoryEntry, MemoryEpisode
from app.models.payment_models import PlanType
from app.templates.docstrings.memory_tool_docs import (
    ADD_MEMORY,
    FORGET_MEMORY,
    GET_JOURNAL,
    READ_MEMORY_DOCUMENT,
    SEARCH_JOURNAL,
    SEARCH_MEMORY,
    UPDATE_MEMORY,
    UPDATE_MEMORY_DOCUMENT,
)
from app.utils.chat_utils import get_user_id_from_config
from shared.py.wide_events import MemoryContext, UserContext, log

_ERR_NO_USER_ID = "Error: user_id not found in config"


# ---------------------------------------------------------------------------
# The ``memory_data`` payload vocabulary — the frontend contract described in
# the module docstring, as a union discriminated on ``action``. Plain
# TypedDicts: these are built here and handed straight to the stream writer,
# so there is nothing to validate or coerce at runtime.
# ---------------------------------------------------------------------------

# A ``MemoryEntry``/``MemoryEpisodeEntry`` serialized with ``model_dump(mode="json")``
# — an arbitrary JSON object by the time it reaches the payload.
SerializedEntry: TypeAlias = dict[str, Any]


class JournalLinePayload(TypedDict):
    """One journal line inside an ``episodes`` entry."""

    time: str | None
    text: str
    source: str | None


class EpisodePayload(TypedDict):
    """One journal day of the ``journal`` payload."""

    date: str
    entries: list[JournalLinePayload]
    summary: str | None


class DocumentPayload(TypedDict):
    """The core document carried by the ``document`` payload."""

    doc_type: str
    content: str
    version: int
    updated_at: str


AddOutcome: TypeAlias = Literal["new", "updated", "extended", "duplicate"]


class AddMemoryPayload(TypedDict):
    action: Literal["add"]
    memories: list[SerializedEntry]
    folder: str
    outcome: AddOutcome
    message: str


class SearchMemoryPayload(TypedDict):
    action: Literal["search"]
    query: str
    folder: str | None
    memories: list[SerializedEntry]
    message: str


class UpdateMemoryPayload(TypedDict):
    action: Literal["update"]
    memories: list[SerializedEntry]
    message: str


class ForgetMemoryPayload(TypedDict):
    action: Literal["forget"]
    memory_id: str
    reason: str
    message: str


class JournalPayload(TypedDict):
    action: Literal["journal"]
    query: str | None
    episodes: list[EpisodePayload]
    message: str


class DocumentEventPayload(TypedDict):
    action: Literal["document"]
    document: DocumentPayload
    updated: bool
    message: str


MemoryDataPayload: TypeAlias = (
    AddMemoryPayload
    | SearchMemoryPayload
    | UpdateMemoryPayload
    | ForgetMemoryPayload
    | JournalPayload
    | DocumentEventPayload
)

# How reconciliation resolved an explicit add, as the frontend payload says it.
_ADD_OUTCOMES: dict[ReconcileOutcome, AddOutcome] = {
    ReconcileOutcome.NEW: "new",
    ReconcileOutcome.UPDATES: "updated",
    ReconcileOutcome.EXTENDS: "extended",
    ReconcileOutcome.DUPLICATE: "duplicate",
}

# Friendly doc names ('user', 'agenda', ...) plus the canonical enum values.
_DOC_TYPE_ALIASES: dict[str, MemoryDocType] = {
    **{doc_type.value: doc_type for doc_type in MemoryDocType},
    **{
        filename.removesuffix(".md"): doc_type
        for doc_type, filename in MEMORY_DOC_FILENAMES.items()
    },
}
_DOC_TYPE_CHOICES = ", ".join(
    filename.removesuffix(".md") for filename in MEMORY_DOC_FILENAMES.values()
)


def _stream_memory_data(payload: MemoryDataPayload) -> None:
    """Emit one ``memory_data`` event to the frontend (no-op outside a run)."""
    try:
        writer = get_stream_writer()
    except RuntimeError:
        return
    writer({"memory_data": payload})


def _stream_memory_limit_card() -> None:
    """Emit the in-chat rate-limit card for the free memory cap.

    Same ``rate_limit_data`` payload :func:`build_rate_limit_card` builds for
    ``@with_rate_limiting`` (see app/decorators/rate_limiting.py), so the frontend
    RateLimitCard with its upgrade CTA renders with zero new frontend work. The
    explicit ``message`` matters: memory is NOT plan-gated (free includes a capped
    amount), so the card must say the cap is full rather than the generic
    "not included in your plan" copy.
    """
    try:
        writer = get_stream_writer()
    except RuntimeError:
        return
    writer(
        build_rate_limit_card(
            feature="memory",
            plan_required=PlanType.PRO.value,
            reset_time=None,
            current_plan=PlanType.FREE.value,
            message=(
                f"Your free plan stores up to {FREE_MEMORY_FACT_LIMIT} "
                "memories and they are all used. Everything already "
                "saved keeps working. Upgrade to Pro for unlimited "
                "memories."
            ),
        )
    )


def _cap(text: str, limit: int) -> str:
    """Truncate text to a payload-friendly length."""
    return text if len(text) <= limit else f"{text[: limit - 3]}..."


def _entry_payload(entry: MemoryEntry) -> SerializedEntry:
    """Serialize a MemoryEntry exactly as the API does, with capped content."""
    data = entry.model_dump(mode="json")
    data["content"] = _cap(entry.content, MEMORY_TOOL_CONTENT_MAX_CHARS)
    return data


def _episode_payload(episode: MemoryEpisode) -> EpisodePayload:
    """Serialize a journal day for the ``journal`` tool-data payload."""
    return EpisodePayload(
        date=episode.date,
        entries=[
            JournalLinePayload(
                time=entry.time,
                text=_cap(entry.text, MEMORY_TOOL_CONTENT_MAX_CHARS),
                source=entry.source,
            )
            for entry in episode.entries
        ],
        summary=_cap(episode.summary, MEMORY_TOOL_CONTENT_MAX_CHARS) if episode.summary else None,
    )


def _document_payload(document: MemoryDocument) -> DocumentPayload:
    """Serialize a core document for the ``document`` tool-data payload."""
    return DocumentPayload(
        doc_type=document.doc_type.value,
        content=_cap(document.content, MEMORY_TOOL_DOCUMENT_MAX_CHARS),
        version=document.version,
        updated_at=document.updated_at.isoformat(),
    )


def _hits_to_episode_payloads(hits: list[EpisodeHit]) -> list[EpisodePayload]:
    """Group journal search hits by day into the shared episodes payload shape."""
    by_date: dict[date_type, EpisodePayload] = {}
    for hit in hits:
        day = by_date.setdefault(
            hit.date,
            EpisodePayload(date=hit.date.isoformat(), entries=[], summary=None),
        )
        text = _cap(hit.text, MEMORY_TOOL_CONTENT_MAX_CHARS)
        if hit.time is None:
            # Timeless hits are day-summary matches, not journal lines.
            day["summary"] = text
        else:
            day["entries"].append(JournalLinePayload(time=hit.time, text=text, source=None))
    return [by_date[day] for day in sorted(by_date, reverse=True)]


def _format_entry_line(index: int, entry: MemoryEntry) -> str:
    """One search-result line: content, id, folder, date, score."""
    details = [f"id: {entry.id}", f"folder: {entry.category_path}"]
    mentioned = entry.mentioned_at or entry.created_at
    if mentioned:
        details.append(f"date: {mentioned.date().isoformat()}")
    if entry.relevance_score is not None:
        details.append(f"score: {entry.relevance_score:.2f}")
    return f"{index}. {entry.content}\n   ({', '.join(details)})"


def _resolve_doc_type(doc_type: str) -> MemoryDocType | None:
    """Map a friendly or canonical document name onto MemoryDocType."""
    return _DOC_TYPE_ALIASES.get(doc_type.strip().lower().removesuffix(".md"))


@tool
@with_doc(ADD_MEMORY)
async def add_memory(
    config: RunnableConfig,
    content: Annotated[str, "The fact to remember, as one self-contained assertion"],
    folder: Annotated[
        str | None,
        "Optional folder to file under (e.g. 'work/gaia'); omit to auto-categorize",
    ] = None,
) -> str:
    user_id = get_user_id_from_config(config)
    if not user_id:
        return _ERR_NO_USER_ID

    try:
        retained = await memory_engine.retain_single(
            user_id, content, category_path=folder, source_type=MemorySourceType.TOOL
        )
    except MemoryLimitReachedError as e:
        # Free-plan cap: fail LOUD with the upgrade card + an agent-facing
        # instruction, so the user both sees the wall and hears why.
        log.info(
            "memory_cap_reached",
            event_name="memory_cap_reached",
            user_id=user_id,
            source="add_memory_tool",
            limit=e.limit,
        )
        log.set(memory=MemoryContext(operation="create", success=False))
        _stream_memory_limit_card()
        return (
            f"Memory limit reached: the free plan stores up to {e.limit} memories, "
            "and this user's memory is full. The new fact was NOT saved. Tell the "
            "user their saved memories are full and that upgrading to Pro unlocks "
            "unlimited memories (existing memories still work)."
        )
    except Exception as e:
        log.error(
            "memory_tool_failed",
            operation="create",
            error_type=type(e).__name__,
            error=str(e),
        )
        log.set(memory=MemoryContext(operation="create", success=False))
        return f"Error storing memory: {e}"

    entry = retained.entry
    outcome = _ADD_OUTCOMES[retained.outcome]
    log.set(
        user=UserContext(id=user_id),
        memory=MemoryContext(
            operation="create",
            success=True,
            memory_id=entry.id,
            content_length=len(content),
        ),
    )
    messages: dict[AddOutcome, str] = {
        "new": f"Memory stored under '{entry.category_path}'",
        "updated": f"Updated an existing memory under '{entry.category_path}'",
        "extended": f"Stored under '{entry.category_path}', extending a related memory",
        "duplicate": f"Already known: matched an existing memory under '{entry.category_path}'",
    }
    message = messages[outcome]
    _stream_memory_data(
        AddMemoryPayload(
            action="add",
            memories=[_entry_payload(entry)],
            folder=entry.category_path,
            outcome=outcome,
            message=message,
        )
    )
    return f"{message} (ID: {entry.id})"


@tool
@with_doc(SEARCH_MEMORY)
async def search_memory(
    config: RunnableConfig,
    query: Annotated[str, "Query string to search for"],
    limit: Annotated[int, "Maximum number of results to return"] = 5,
    folder: Annotated[
        str | None,
        "Optional folder to search within (e.g. 'relationships'); includes subfolders",
    ] = None,
) -> str:
    user_id = get_user_id_from_config(config)
    if not user_id:
        return _ERR_NO_USER_ID

    try:
        result = await memory_engine.recall(
            user_id, query, limit=limit or DEFAULT_RECALL_LIMIT, category_prefix=folder
        )
    except Exception as e:
        log.error(
            "memory_tool_failed",
            operation="recall",
            error_type=type(e).__name__,
            error=str(e),
        )
        log.set(memory=MemoryContext(operation="recall", success=False))
        raise

    log.set(
        user=UserContext(id=user_id),
        memory=MemoryContext(
            operation="recall",
            success=True,
            query=query,
            result_count=len(result.memories),
        ),
    )

    scope = f" in '{folder}'" if folder else ""
    message = (
        f"Found {len(result.memories)} memories{scope}"
        if result.memories
        else f"No matching memories{scope}"
    )
    _stream_memory_data(
        SearchMemoryPayload(
            action="search",
            query=query,
            folder=folder,
            memories=[_entry_payload(entry) for entry in result.memories],
            message=message,
        )
    )

    if not result.memories:
        return f"No matching memories found{scope}."
    lines = [_format_entry_line(index, entry) for index, entry in enumerate(result.memories, 1)]
    return f"{message}:\n\n" + "\n".join(lines)


@tool
@with_doc(UPDATE_MEMORY)
async def update_memory(
    config: RunnableConfig,
    memory_id: Annotated[str, "ID of the memory to correct (from search_memory)"],
    new_content: Annotated[str, "The corrected fact, as one self-contained assertion"],
) -> str:
    user_id = get_user_id_from_config(config)
    if not user_id:
        return _ERR_NO_USER_ID

    # A bad id RAISES (MemoryNotFoundError) rather than returning an error
    # string. The string version read back to the model as an ordinary result:
    # it typo'd an id, got "Error: ... not found", and told the user the
    # memory was fixed. A superseded id is not a failure — the engine resolves
    # it to the live head of its chain.
    try:
        entry = await memory_engine.update_memory(user_id, memory_id, new_content)
    except Exception as e:
        log.error(
            "memory_tool_failed",
            operation="update",
            error_type=type(e).__name__,
            error=str(e),
        )
        log.set(memory=MemoryContext(operation="update", success=False))
        raise

    log.set(
        user=UserContext(id=user_id),
        memory=MemoryContext(operation="update", success=True, memory_id=entry.id),
    )

    message = f"Memory corrected (now v{entry.version} under '{entry.category_path}')"
    _stream_memory_data(
        UpdateMemoryPayload(action="update", memories=[_entry_payload(entry)], message=message)
    )
    return f"{message}. New ID: {entry.id}"


@tool
@with_doc(FORGET_MEMORY)
async def forget_memory(
    config: RunnableConfig,
    memory_id: Annotated[str, "ID of the memory to forget (from search_memory)"],
    reason: Annotated[str, "Short reason why this memory is being forgotten"],
) -> str:
    user_id = get_user_id_from_config(config)
    if not user_id:
        return _ERR_NO_USER_ID

    try:
        forgotten = await memory_engine.forget_memory(user_id, memory_id, reason)
    except Exception as e:
        log.error(
            "memory_tool_failed",
            operation="delete",
            error_type=type(e).__name__,
            error=str(e),
        )
        log.set(memory=MemoryContext(operation="delete", success=False))
        raise

    if not forgotten:
        log.warning("memory_tool_memory_not_found", operation="delete", memory_id=memory_id)
        return f"Error: memory {memory_id} not found."

    log.set(
        user=UserContext(id=user_id),
        memory=MemoryContext(operation="delete", success=True, memory_id=memory_id),
    )

    message = "Memory forgotten"
    _stream_memory_data(
        ForgetMemoryPayload(action="forget", memory_id=memory_id, reason=reason, message=message)
    )
    return f"{message}: {memory_id} ({reason})"


@tool
@with_doc(SEARCH_JOURNAL)
async def search_journal(
    config: RunnableConfig,
    query: Annotated[str, "What to look for in past activity"],
) -> str:
    user_id = get_user_id_from_config(config)
    if not user_id:
        return _ERR_NO_USER_ID

    try:
        hits = await memory_engine.recall_episodes(user_id, query)
    except Exception as e:
        log.error(
            "memory_tool_failed",
            operation="recall_episodes",
            error_type=type(e).__name__,
            error=str(e),
        )
        log.set(memory=MemoryContext(operation="recall_episodes", success=False))
        raise

    episodes = _hits_to_episode_payloads(hits)
    log.set(
        user=UserContext(id=user_id),
        memory=MemoryContext(
            operation="recall_episodes",
            success=True,
            query=query,
            result_count=len(episodes),
        ),
    )
    message = f"Found journal activity on {len(episodes)} days" if hits else "No journal matches"
    _stream_memory_data(
        JournalPayload(action="journal", query=query, episodes=episodes, message=message)
    )

    if not hits:
        return f"No journal entries matching '{query}'."
    lines = [
        f"- {hit.date.isoformat()}{f' {hit.time}' if hit.time else ' (day summary)'}: {hit.text}"
        for hit in hits
    ]
    return f"{message}:\n" + "\n".join(lines)


@tool
async def search_conversations(
    config: RunnableConfig,
    query: Annotated[str, "What to look for verbatim in past conversations"],
) -> str:
    """Search raw past-conversation transcripts for verbatim details.

    Use when the user references something specific from an earlier chat that
    memory search does not surface, such as "that list you gave me", "the exact move
    you suggested", or "what did we say about X", and quote the matching passage.
    """
    user_id = get_user_id_from_config(config)
    if not user_id:
        return _ERR_NO_USER_ID

    try:
        hits = await memory_engine.recall_transcripts(user_id, query)
    except Exception as e:
        log.error(
            "memory_tool_failed",
            operation="recall_transcripts",
            error_type=type(e).__name__,
            error=str(e),
        )
        log.set(memory=MemoryContext(operation="recall_transcripts", success=False))
        raise

    log.set(
        user=UserContext(id=user_id),
        memory=MemoryContext(
            operation="recall_transcripts",
            success=True,
            query=query,
            result_count=len(hits),
        ),
    )
    if not hits:
        return f"No past-conversation passages matching '{query}'."
    blocks = [
        f"[{date}] (match {score:.2f})\n{_cap(text, MEMORY_TOOL_DOCUMENT_MAX_CHARS)}"
        for date, text, score in hits
    ]
    return "Matching conversation passages:\n\n" + "\n\n".join(blocks)


@tool
@with_doc(GET_JOURNAL)
async def get_journal(
    config: RunnableConfig,
    date: Annotated[str, "The day to read, as YYYY-MM-DD; omit for the user's local today"] = "",
) -> str:
    user_id = get_user_id_from_config(config)
    if not user_id:
        return _ERR_NO_USER_ID

    if date:
        try:
            day = date_type.fromisoformat(date)
        except ValueError:
            log.warning("memory_tool_invalid_date", operation="episodes", start=date)
            return f"Error: invalid date '{date}'. Use YYYY-MM-DD."
    else:
        # Journal days bucket on the user's wall clock: at 2am IST "today" is
        # still UTC's yesterday, so the default must be the LOCAL day.
        day = await local_today(user_id)
        date = day.isoformat()

    try:
        response = await memory_engine.get_episodes(user_id, day, day)
    except Exception as e:
        log.error(
            "memory_tool_failed",
            operation="episodes",
            error_type=type(e).__name__,
            error=str(e),
        )
        log.set(memory=MemoryContext(operation="episodes", success=False))
        raise

    episode = response.episodes[0] if response.episodes else None
    if episode is None or (not episode.entries and not episode.summary):
        log.set(
            user=UserContext(id=user_id),
            memory=MemoryContext(
                operation="episodes",
                success=True,
                result_count=0,
                start=date,
                end=date,
            ),
        )
        message = f"No journal entries for {date}"
        _stream_memory_data(
            JournalPayload(action="journal", query=None, episodes=[], message=message)
        )
        return f"{message}."

    log.set(
        user=UserContext(id=user_id),
        memory=MemoryContext(
            operation="episodes",
            success=True,
            result_count=len(episode.entries),
            start=date,
            end=date,
        ),
    )
    message = f"Journal for {date} ({len(episode.entries)} entries)"
    _stream_memory_data(
        JournalPayload(
            action="journal",
            query=None,
            episodes=[_episode_payload(episode)],
            message=message,
        )
    )

    lines = [f"- {entry.time} {entry.text}".rstrip() for entry in episode.entries]
    parts = [f"{message}:"]
    if episode.summary:
        parts.append(f"Summary: {episode.summary}")
    if lines:
        parts.append("\n".join(lines))
    return "\n".join(parts)


@tool
@with_doc(READ_MEMORY_DOCUMENT)
async def read_memory_document(
    config: RunnableConfig,
    doc_type: Annotated[str, "Which document: 'user', 'memory', 'agenda', 'people', or 'insights'"],
) -> str:
    user_id = get_user_id_from_config(config)
    if not user_id:
        return _ERR_NO_USER_ID

    resolved = _resolve_doc_type(doc_type)
    if resolved is None:
        log.warning("memory_tool_unknown_doc", operation="read_document", doc_type=doc_type)
        return f"Error: unknown document '{doc_type}'. Use one of: {_DOC_TYPE_CHOICES}."

    try:
        document = await memory_engine.get_document(user_id, resolved)
    except Exception as e:
        log.error(
            "memory_tool_failed",
            operation="read_document",
            error_type=type(e).__name__,
            error=str(e),
        )
        log.set(memory=MemoryContext(operation="read_document", success=False))
        raise

    log.set(
        user=UserContext(id=user_id),
        memory=MemoryContext(operation="read_document", success=True, doc_type=resolved.value),
    )
    if document is None or not document.content.strip():
        return (
            f"The '{doc_type}' document is empty: nothing has been written to it yet. "
            "It fills in automatically as memory accumulates."
        )

    _stream_memory_data(
        DocumentEventPayload(
            action="document",
            document=_document_payload(document),
            updated=False,
            message=f"Read the '{doc_type}' memory document (v{document.version})",
        )
    )
    return document.content


@tool
@with_doc(UPDATE_MEMORY_DOCUMENT)
async def update_memory_document(
    config: RunnableConfig,
    doc_type: Annotated[str, "Which document: 'user', 'memory', 'agenda', 'people', or 'insights'"],
    content: Annotated[str, "The complete new markdown content (full replace)"],
) -> str:
    user_id = get_user_id_from_config(config)
    if not user_id:
        return _ERR_NO_USER_ID

    resolved = _resolve_doc_type(doc_type)
    if resolved is None:
        log.warning("memory_tool_unknown_doc", operation="update_document", doc_type=doc_type)
        return f"Error: unknown document '{doc_type}'. Use one of: {_DOC_TYPE_CHOICES}."

    try:
        document = await memory_engine.update_document(user_id, resolved, content)
    except Exception as e:
        log.error(
            "memory_tool_failed",
            operation="update_document",
            error_type=type(e).__name__,
            error=str(e),
        )
        log.set(memory=MemoryContext(operation="update_document", success=False))
        raise

    log.set(
        user=UserContext(id=user_id),
        memory=MemoryContext(operation="update_document", success=True, doc_type=resolved.value),
    )
    message = f"Rewrote the '{doc_type}' memory document (now v{document.version})"
    _stream_memory_data(
        DocumentEventPayload(
            action="document",
            document=_document_payload(document),
            updated=True,
            message=message,
        )
    )
    return f"{message}. The full content was replaced; prior versions are kept as history."


tools = [
    add_memory,
    search_memory,
    update_memory,
    forget_memory,
    search_journal,
    search_conversations,
    get_journal,
    read_memory_document,
    update_memory_document,
]
