"""Deterministic stand-ins for every external read a context section performs.

A section's *text* is the thing under test; the store it reads from is not. This
module pins each of those reads to a declared value and — just as importantly —
fences the real clients underneath them, so a section that grows a new read
fails loudly here instead of quietly reaching Mongo/Redis/Chroma in a unit test
and passing for the wrong reason.
"""

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from app.models.memory_models import MemoryEntry, MemorySearchResult
from app.models.todo_models import TodoDocument
from app.services.gaia_knowledge_service import KnowledgeResult


def memory(content: str, *, mentioned: str | None = None) -> MemoryEntry:
    """A recalled memory. ``mentioned`` fixes the date ``entry_to_note`` renders."""
    return MemoryEntry(
        content=content,
        mentioned_at=datetime.fromisoformat(mentioned).replace(tzinfo=UTC) if mentioned else None,
    )


def knowledge(content: str) -> KnowledgeResult:
    return KnowledgeResult(content=content, relevance_score=1.0, metadata={})


@dataclass(frozen=True)
class ContextSources:
    """What each faked IO edge returns for one assembly run."""

    core_memory: str = ""
    memories: list[MemoryEntry] = field(default_factory=list)
    gaia_knowledge: list[KnowledgeResult] = field(default_factory=list)
    tracked_todos: str = ""
    skills: str = ""
    #: ``get_connected_integrations_named`` shape: ``[{"id": ..., "name": ...}]``.
    connected_integrations: list[dict[str, str]] = field(default_factory=list)
    provider_metadata: dict[str, str] = field(default_factory=dict)
    custom_instructions: str = ""
    active_todo: TodoDocument | None = None
    #: Ground-truth block the workflow authoring tier folds into its human turn.
    workflow_integrations_hint: str = ""
    #: Task id of a live background executor run, or ``None`` for "not busy".
    executor_busy_task_id: str | None = None
    #: Comms-only: the onboarding system prompt for this turn, or ``None`` when
    #: the conversation is not an onboarding one.
    onboarding_prompt: str | None = None


#: The real clients underneath the faked edges. Every one of these is reachable
#: from some context section's call graph, so leaving them live would let a
#: section that grows a new read pass by silently hitting a store instead of a
#: declared fake. Fenced rather than stubbed: a hit is a bug in the harness's
#: coverage, not a value to guess at.
_FENCED_CLIENTS = (
    "app.db.mongodb.collections.get_async_collection",
    "app.db.redis.get_cache",
    "app.db.redis.set_cache",
    "app.db.chroma.chromadb.ChromaClient.get_langchain_client",
    "app.agents.llm.client.init_llm",
)


class EscapedIO(AssertionError):
    """A context section reached a real client instead of a declared fake."""


def _fence(name: str) -> AsyncMock:
    async def _raise(*args: object, **kwargs: object) -> object:
        raise EscapedIO(
            f"{name} was called with no fake declared — the harness only covers the "
            "IO edges the context sections are known to touch. Declare a fake for "
            "this edge rather than letting the test reach a real client."
        )

    return AsyncMock(side_effect=_raise)


@contextmanager
def fake_context_sources(sources: ContextSources) -> Iterator[None]:
    """Pin every context IO edge, and fence the clients beneath them."""
    recalled = MemorySearchResult(
        memories=list(sources.memories), total_count=len(sources.memories)
    )

    with ExitStack() as stack:
        enter = stack.enter_context
        enter(patch("app.memory.engine.memory_engine.recall", AsyncMock(return_value=recalled)))
        enter(
            patch(
                "app.memory.engine.memory_engine.get_core_context",
                AsyncMock(return_value=sources.core_memory),
            )
        )
        enter(
            patch(
                "app.services.gaia_knowledge_service.gaia_knowledge_service.search_knowledge",
                AsyncMock(return_value=list(sources.gaia_knowledge)),
            )
        )
        enter(
            patch(
                "app.services.tracked_todo_service.tracked_todo_service.get_active_tracked_summary",
                AsyncMock(return_value=sources.tracked_todos),
            )
        )
        enter(
            patch(
                "app.db.repositories.todos.todo_repository.get",
                AsyncMock(return_value=sources.active_todo),
            )
        )
        enter(
            patch(
                "app.agents.context.fetchers.get_connected_integrations_named",
                AsyncMock(return_value=list(sources.connected_integrations)),
            )
        )
        enter(
            patch(
                "app.agents.context.sections.get_provider_metadata",
                AsyncMock(return_value=dict(sources.provider_metadata)),
            )
        )
        enter(
            patch(
                "app.agents.context.sections.get_instructions",
                AsyncMock(return_value=sources.custom_instructions),
            )
        )
        enter(
            patch(
                "app.agents.context.sections.get_available_skills_text",
                AsyncMock(return_value=sources.skills),
            )
        )
        enter(
            patch(
                "app.services.workflow.workflow_subagent.build_connected_integrations_hint",
                AsyncMock(return_value=sources.workflow_integrations_hint),
            )
        )
        # Whether a turn is an onboarding turn is decided by a Mongo probe plus
        # the user document. That resolution is its own subject with its own
        # tests; here only its answer matters, so the answer is what is pinned.
        enter(
            patch(
                "app.agents.core.messages.get_onboarding_system_prompt_if_applicable",
                AsyncMock(return_value=sources.onboarding_prompt),
            )
        )
        # Redis: the tracked-todos section's own short cache. An in-memory dict
        # keeps the real caching branch live without a server, so a change to
        # what gets cached still runs through the code that does the caching.
        cache: dict[str, str] = {}

        async def _get_cache(key: str) -> str | None:
            return cache.get(key)

        async def _set_cache(key: str, value: str, ttl: int | None = None) -> None:
            del ttl  # expiry is not observable in a single test run
            cache[key] = value

        enter(patch("app.agents.context.fetchers.get_cache", _get_cache))
        enter(patch("app.agents.context.fetchers.set_cache", _set_cache))
        enter(_patch_executor_lock(sources.executor_busy_task_id))
        for target in _FENCED_CLIENTS:
            enter(patch(target, _fence(target)))
        yield


@contextmanager
def _patch_executor_lock(task_id: str | None) -> Iterator[None]:
    """Pin the comms executor-busy lock ``executor_status_hook`` reads.

    The hook treats a missing client as "not busy", which is the same observable
    state as an unheld lock — so ``None`` covers both without a Redis server.
    """
    with patch("app.agents.core.nodes.executor_status.redis_cache") as fake_cache:
        if task_id is None:
            fake_cache.client = None
        else:
            fake_cache.client = AsyncMock()
            fake_cache.client.get = AsyncMock(return_value=f"stream-1:{task_id}")
        yield
