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
is a ``MemoryDocType`` value (``user_md`` ... ``insights_md``).
"""

from datetime import date as date_type
from typing import Annotated, Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.config import get_stream_writer

from app.constants.memory import (
    DEFAULT_RECALL_LIMIT,
    MEMORY_DOC_FILENAMES,
    MEMORY_TOOL_CONTENT_MAX_CHARS,
    MEMORY_TOOL_DOCUMENT_MAX_CHARS,
    MemoryDocType,
    MemorySourceType,
    ReconcileOutcome,
)
from app.decorators import with_doc
from app.memory.engine import memory_engine
from app.memory.retrieval import EpisodeHit
from app.models.memory_models import MemoryDocument, MemoryEntry, MemoryEpisode
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
from shared.py.wide_events import log

_ERR_NO_USER_ID = "Error: user_id not found in config"

# How reconciliation resolved an explicit add, as the frontend payload says it.
_ADD_OUTCOMES: dict[ReconcileOutcome, str] = {
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


def _stream_memory_data(payload: dict[str, Any]) -> None:
    """Emit one ``memory_data`` event to the frontend (no-op outside a run)."""
    try:
        writer = get_stream_writer()
    except RuntimeError:
        return
    writer({"memory_data": payload})


def _cap(text: str, limit: int) -> str:
    """Truncate text to a payload-friendly length."""
    return text if len(text) <= limit else f"{text[: limit - 3]}..."


def _entry_payload(entry: MemoryEntry) -> dict[str, Any]:
    """Serialize a MemoryEntry exactly as the API does, with capped content."""
    data = entry.model_dump(mode="json")
    data["content"] = _cap(entry.content, MEMORY_TOOL_CONTENT_MAX_CHARS)
    return data


def _episode_payload(episode: MemoryEpisode) -> dict[str, Any]:
    """Serialize a journal day for the ``journal`` tool-data payload."""
    return {
        "date": episode.date,
        "entries": [
            {
                "time": entry.time,
                "text": _cap(entry.text, MEMORY_TOOL_CONTENT_MAX_CHARS),
                "source": entry.source,
            }
            for entry in episode.entries
        ],
        "summary": _cap(episode.summary, MEMORY_TOOL_CONTENT_MAX_CHARS)
        if episode.summary
        else None,
    }


def _document_payload(document: MemoryDocument) -> dict[str, Any]:
    """Serialize a core document for the ``document`` tool-data payload."""
    return {
        "doc_type": document.doc_type.value,
        "content": _cap(document.content, MEMORY_TOOL_DOCUMENT_MAX_CHARS),
        "version": document.version,
        "updated_at": document.updated_at.isoformat(),
    }


def _hits_to_episode_payloads(hits: list[EpisodeHit]) -> list[dict[str, Any]]:
    """Group journal search hits by day into the shared episodes payload shape."""
    by_date: dict[date_type, dict[str, Any]] = {}
    for hit in hits:
        day = by_date.setdefault(
            hit.date, {"date": hit.date.isoformat(), "entries": [], "summary": None}
        )
        text = _cap(hit.text, MEMORY_TOOL_CONTENT_MAX_CHARS)
        if hit.time is None:
            # Timeless hits are day-summary matches, not journal lines.
            day["summary"] = text
        else:
            day["entries"].append({"time": hit.time, "text": text, "source": None})
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
    except Exception as e:
        log.error(f"add_memory failed for user {user_id}: {e}")
        return f"Error storing memory: {e}"

    entry = retained.entry
    outcome = _ADD_OUTCOMES[retained.outcome]
    messages = {
        "new": f"Memory stored under '{entry.category_path}'",
        "updated": f"Updated an existing memory under '{entry.category_path}'",
        "extended": f"Stored under '{entry.category_path}', extending a related memory",
        "duplicate": f"Already known — matched an existing memory under '{entry.category_path}'",
    }
    message = messages[outcome]
    _stream_memory_data(
        {
            "action": "add",
            "memories": [_entry_payload(entry)],
            "folder": entry.category_path,
            "outcome": outcome,
            "message": message,
        }
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

    result = await memory_engine.recall(
        user_id, query, limit=limit or DEFAULT_RECALL_LIMIT, category_prefix=folder
    )

    scope = f" in '{folder}'" if folder else ""
    message = (
        f"Found {len(result.memories)} memories{scope}"
        if result.memories
        else f"No matching memories{scope}"
    )
    _stream_memory_data(
        {
            "action": "search",
            "query": query,
            "folder": folder,
            "memories": [_entry_payload(entry) for entry in result.memories],
            "message": message,
        }
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

    entry = await memory_engine.update_memory(user_id, memory_id, new_content)
    if entry is None:
        return (
            f"Error: memory {memory_id} not found or already superseded — "
            "search_memory for the current version and use its ID."
        )

    message = f"Memory corrected (now v{entry.version} under '{entry.category_path}')"
    _stream_memory_data(
        {"action": "update", "memories": [_entry_payload(entry)], "message": message}
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

    forgotten = await memory_engine.forget_memory(user_id, memory_id, reason)
    if not forgotten:
        return f"Error: memory {memory_id} not found."

    message = "Memory forgotten"
    _stream_memory_data(
        {"action": "forget", "memory_id": memory_id, "reason": reason, "message": message}
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

    hits = await memory_engine.recall_episodes(user_id, query)
    episodes = _hits_to_episode_payloads(hits)
    message = f"Found journal activity on {len(episodes)} days" if hits else "No journal matches"
    _stream_memory_data(
        {"action": "journal", "query": query, "episodes": episodes, "message": message}
    )

    if not hits:
        return f"No journal entries matching '{query}'."
    lines = [
        f"- {hit.date.isoformat()}{f' {hit.time}' if hit.time else ' (day summary)'}: {hit.text}"
        for hit in hits
    ]
    return f"{message}:\n" + "\n".join(lines)


@tool
@with_doc(GET_JOURNAL)
async def get_journal(
    config: RunnableConfig,
    date: Annotated[str, "The day to read, as YYYY-MM-DD"],
) -> str:
    user_id = get_user_id_from_config(config)
    if not user_id:
        return _ERR_NO_USER_ID

    try:
        day = date_type.fromisoformat(date)
    except ValueError:
        return f"Error: invalid date '{date}'. Use YYYY-MM-DD."

    response = await memory_engine.get_episodes(user_id, day, day)
    episode = response.episodes[0] if response.episodes else None
    if episode is None or (not episode.entries and not episode.summary):
        message = f"No journal entries for {date}"
        _stream_memory_data(
            {"action": "journal", "query": None, "episodes": [], "message": message}
        )
        return f"{message}."

    message = f"Journal for {date} ({len(episode.entries)} entries)"
    _stream_memory_data(
        {
            "action": "journal",
            "query": None,
            "episodes": [_episode_payload(episode)],
            "message": message,
        }
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
        return f"Error: unknown document '{doc_type}'. Use one of: {_DOC_TYPE_CHOICES}."

    document = await memory_engine.get_document(user_id, resolved)
    if document is None or not document.content.strip():
        return (
            f"The '{doc_type}' document is empty — nothing has been written to it yet. "
            "It fills in automatically as memory accumulates."
        )

    _stream_memory_data(
        {
            "action": "document",
            "document": _document_payload(document),
            "updated": False,
            "message": f"Read the '{doc_type}' memory document (v{document.version})",
        }
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
        return f"Error: unknown document '{doc_type}'. Use one of: {_DOC_TYPE_CHOICES}."

    document = await memory_engine.update_document(user_id, resolved, content)
    message = f"Rewrote the '{doc_type}' memory document (now v{document.version})"
    _stream_memory_data(
        {
            "action": "document",
            "document": _document_payload(document),
            "updated": True,
            "message": message,
        }
    )
    return f"{message}. The full content was replaced; prior versions are kept as history."


tools = [
    add_memory,
    search_memory,
    update_memory,
    forget_memory,
    search_journal,
    get_journal,
    read_memory_document,
    update_memory_document,
]
