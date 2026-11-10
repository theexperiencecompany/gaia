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
from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.core.background.executor_progress import RunProgress
from app.models.executor_activity_models import ExecutorActivity, ExecutorActivitySnapshot
from app.models.integration_models import UserIntegrationDocument
from app.models.memory_models import MemoryEntry, MemorySearchResult
from app.models.presence_models import PresenceSnapshot
from app.models.todo_models import TodoDocument
from app.services.browser.chat_task import ChatBrowserTasks
from app.services.gaia_knowledge_service import KnowledgeResult
from app.services.outbox.router import InApp, ProactiveTarget


def memory(content: str, *, mentioned: str | None = None) -> MemoryEntry:
    """Build a recalled memory; mentioned fixes the date entry_to_note renders."""
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
    #: Integrations holding several accounts, for the manifest's account lists.
    multi_account_records: list[UserIntegrationDocument] = field(default_factory=list)
    #: The user's "global" standing instructions, the only scope a context section reads.
    global_instructions: str = ""
    active_todo: TodoDocument | None = None
    #: Ground-truth block the workflow authoring tier folds into its human turn.
    workflow_integrations_hint: str = ""
    #: Task id of a live background executor run, or ``None`` for "not busy".
    executor_busy_task_id: str | None = None
    #: The browser tasks the chat controls; none by default.
    browser_tasks: ChatBrowserTasks = field(
        default_factory=lambda: ChatBrowserTasks(running=[], paused=None)
    )
    #: What the root's presence read returns; the default is a user never seen anywhere.
    presence: PresenceSnapshot = field(
        default_factory=lambda: PresenceSnapshot(captured_at=0, last_seen={})
    )
    #: The one place a proactive message would land on.
    proactive_target: ProactiveTarget = field(default_factory=lambda: InApp(reason="no_chat_app"))


#: The real clients underneath the faked edges, reachable from some context
#: section's call graph; fenced rather than stubbed so a section that grows
#: a new read fails loudly instead of silently hitting a real store.
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
        # The device manifest is a cached live read (Postgres) behind @Cacheable.
        # The fixture declares no devices, so pin the empty manifest rather than
        # letting the snapshot depend on whatever devices the environment holds.
        enter(
            patch(
                "app.agents.context.fetchers.get_device_manifest",
                AsyncMock(return_value=[]),
            )
        )
        enter(
            patch(
                "app.agents.context.fetchers.list_account_records",
                AsyncMock(return_value=list(sources.multi_account_records)),
            )
        )
        enter(
            patch(
                "app.agents.context.sections.get_instructions",
                AsyncMock(return_value=sources.global_instructions),
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
        # Roots with no presence read it (comms in _core_agent_logic, others in
        # build_agent_config); a background note reads it live with its target.
        for reader in (
            "app.agents.core.agent.read_presence",
            "app.helpers.agent_helpers.read_presence",
            "app.agents.context.presence_note.read_presence",
        ):
            enter(patch(reader, AsyncMock(return_value=sources.presence)))
        enter(
            patch(
                "app.agents.context.presence_note.resolve_proactive_target",
                AsyncMock(return_value=sources.proactive_target),
            )
        )
        enter(_patch_live_work(sources.executor_busy_task_id, sources.browser_tasks))
        for target in _FENCED_CLIENTS:
            enter(patch(target, _fence(target)))
        yield


@contextmanager
def _patch_live_work(task_id: str | None, browser_tasks: ChatBrowserTasks) -> Iterator[None]:
    """Pin what the comms turn-start live-work sections read.

    task_id None is an idle executor; otherwise a live run holding the lock with
    no subagents and no recorded progress.
    """
    snapshot = (
        ExecutorActivitySnapshot(ExecutorActivity.IDLE)
        if task_id is None
        else ExecutorActivitySnapshot(ExecutorActivity.RUNNING, task_id, f"stream-1:{task_id}")
    )
    running = MagicMock()
    running.return_value.live = AsyncMock(return_value=[])
    with (
        patch(
            "app.agents.context.live_work.read_executor_activity",
            AsyncMock(return_value=snapshot),
        ),
        patch("app.agents.context.live_work.RunningSubagents", running),
        patch("app.agents.context.live_work.read_progress", AsyncMock(return_value=RunProgress())),
        patch(
            "app.agents.context.live_work.chat_browser_tasks",
            AsyncMock(return_value=browser_tasks),
        ),
    ):
        yield
