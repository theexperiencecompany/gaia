"""One chat turn recalls the user's memories once: comms recalls, the executor reuses it.

Runs the real comms context build, the real prepare_executor_execution and the
real cached recall pipeline; only the recall's stores (embedder, Chroma,
Postgres, reranker) and Redis are doubled. Every real recall embeds its query
exactly once, so the embedded queries are the recalls the turn paid for.
"""

from collections.abc import Iterator
from contextlib import AbstractContextManager, ExitStack
from datetime import UTC, datetime
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import fakeredis.aioredis
import pytest

from app.agents.context.slots import PromptSlot
from app.agents.core.messages import MessageScope, construct_langchain_messages
from app.agents.core.subagents.subagent_runner import (
    compose_executor_brief,
    prepare_executor_execution,
)
from app.constants.memory import MemoryKind
from app.db.redis import redis_cache
from app.helpers.agent_helpers import AgentIdentity, AgentTurn, build_agent_config
from app.memory import retrieval
from app.models import agent_models
from app.models.agent_models import AgentConfigurable
from app.models.memory_db_models import MemoryRecord
from app.models.message_models import MessageDict
from tests._harness.context_chain import message_in_slot, text_of
from tests._harness.context_sources import ContextSources, fake_context_sources

CONFIDENT_LOGIT = 5.0
WEAK_LOGIT = -9.0
WEAK_COSINE = 0.1


def _row(content: str) -> MemoryRecord:
    now = datetime.now(UTC)
    return MemoryRecord(
        id=uuid.uuid4(),
        user_id="user",
        kind=MemoryKind.FACT.value,
        content=content,
        category_path="general",
        importance=0.5,
        version=1,
        is_latest=True,
        is_forgotten=False,
        forget_after=None,
        parent_id=None,
        relation_type=None,
        mentioned_at=now,
        created_at=now,
        updated_at=now,
        source_type="conversation",
        metadata_json={},
    )


class MemoryStores:
    """The recall pipeline's stores: one memory, relevant to the queries named in relevant_to."""

    def __init__(self, content: str, *, relevant_to: str) -> None:
        self.row = _row(content)
        self.relevant_to = relevant_to
        self.embedded: list[str] = []

    async def embed(self, query: str, *, interactive: bool = False) -> list[float]:
        self.embedded.append(query)
        return [0.1] * 8

    async def rerank(
        self, query: str, documents: list[str], *, interactive: bool = False
    ) -> list[float]:
        logit = CONFIDENT_LOGIT if self.relevant_to in query else WEAK_LOGIT
        return [logit for _ in documents]

    def patches(self) -> Iterator[AbstractContextManager[object]]:
        yield patch.object(retrieval, "embed_query", new=self.embed)
        yield patch.object(
            retrieval.chroma_store,
            "query_similar",
            new=AsyncMock(return_value=[(str(self.row.id), WEAK_COSINE)]),
        )
        yield patch.object(retrieval.pg_store, "fts_search", new=AsyncMock(return_value=[]))
        yield patch.object(
            retrieval.pg_store, "get_memories_by_ids", new=AsyncMock(return_value=[self.row])
        )
        yield patch.object(
            retrieval.pg_store, "get_entities_for_memories", new=AsyncMock(return_value={})
        )
        yield patch.object(
            retrieval.pg_store, "get_memories_for_entities", new=AsyncMock(return_value=[])
        )
        yield patch.object(retrieval, "rerank", new=self.rerank)


async def _run_turn(stores: MemoryStores, request: str, task: str) -> str:
    """Build comms's context for request, then the executor's for the task comms delegates.

    Returns the executor's memory-recall slot text.
    """
    user_id = f"user-{uuid.uuid4()}"
    with ExitStack() as stack:
        stack.enter_context(fake_context_sources(ContextSources()))
        # Re-point the harness's recall double at the real cached pipeline.
        stack.enter_context(patch("app.memory.engine.memory_engine.recall", retrieval.recall))
        stack.enter_context(
            patch.object(redis_cache, "redis", fakeredis.aioredis.FakeRedis(decode_responses=True))
        )
        for patcher in stores.patches():
            stack.enter_context(patcher)
        stack.enter_context(
            patch(
                "app.agents.core.subagents.subagent_runner.GraphManager.get_graph",
                AsyncMock(return_value=MagicMock()),
            )
        )
        stack.enter_context(
            patch(
                "app.agents.core.subagents.subagent_runner.FileService.list_conversation_files",
                AsyncMock(return_value=[]),
            )
        )

        await construct_langchain_messages(
            messages=[cast(MessageDict, {"role": "user", "content": request})],
            query=request,
            scope=MessageScope(user_id=user_id, conversation_id="conv-1"),
        )
        comms_config = await build_agent_config(
            identity=AgentIdentity(
                conversation_id="conv-1",
                user={"user_id": user_id, "email": "ada@example.com", "name": "Ada"},
                agent_name="comms_agent",
            ),
            turn=AgentTurn(user_request=request),
        )
        configurable: AgentConfigurable = {**agent_models.agent_configurable(comms_config)}
        brief = compose_executor_brief(task, ["done"], verbatim_request=request)
        ctx, error = await prepare_executor_execution(brief, configurable)

    assert error is None and ctx is not None
    return text_of(message_in_slot(ctx.initial_state["messages"], PromptSlot.MEMORY_RECALL))


@pytest.mark.integration
class TestOneTurnOneRecall:
    @pytest.mark.regression
    async def test_the_executor_reuses_the_recall_comms_made_for_this_request(self) -> None:
        request = "go to news.ycombinator.com and tell me the top story"
        stores = MemoryStores(
            "Aryan tests the browser on Hacker News", relevant_to="news.ycombinator.com"
        )

        executor_recall = await _run_turn(
            stores, request, task="Open news.ycombinator.com and report the top story's title."
        )

        assert stores.embedded == [request]
        assert "Aryan tests the browser on Hacker News" in executor_recall

    async def test_a_request_that_matched_nothing_is_recalled_again_on_the_task(self) -> None:
        """A bare "yes do it" carries no subject: the memories live behind the task comms resolved."""
        request = "yes do it"
        task = "Email the user's manager that the quarterly report will be late."
        stores = MemoryStores("Aryan's manager is Priya", relevant_to="quarterly report")

        executor_recall = await _run_turn(stores, request, task=task)

        assert len(stores.embedded) == 2
        assert stores.embedded[0] == request
        assert task in stores.embedded[1]
        assert "Aryan's manager is Priya" in executor_recall
