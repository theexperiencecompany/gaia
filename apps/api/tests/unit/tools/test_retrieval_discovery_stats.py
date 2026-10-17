"""retrieve_tools discovery mode: search failures, the hit counts it reports, and what it searches."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, call, patch

from langgraph.store.base import SearchItem
import pytest

from app.agents.tools.core import retrieval
from app.constants.log_tags import LogTag


def _item(key: str, namespace: tuple[str, ...]) -> SearchItem:
    now = datetime.now(UTC)
    return SearchItem(
        namespace=namespace, key=key, value={}, created_at=now, updated_at=now, score=0.5
    )


class TestEverySearchFailed:
    def test_a_partial_outage_is_logged_per_failure_and_degrades(self) -> None:
        with patch.object(retrieval, "log") as mock_log:
            retrieval._raise_if_every_search_failed([ValueError("chroma down"), []])

        mock_log.error.assert_called_once_with(
            f"{LogTag.TOOL} retrieve_tools search task failed",
            error="chroma down",
            error_type="ValueError",
        )

    def test_a_total_outage_raises_the_first_failure(self) -> None:
        first, second = ValueError("one"), RuntimeError("two")

        with patch.object(retrieval, "log"), pytest.raises(ValueError) as raised:
            retrieval._raise_if_every_search_failed([first, second])

        assert raised.value is first


class TestSearchHitStats:
    def test_hits_are_counted_per_source_and_per_namespace(self) -> None:
        stats = retrieval._search_hit_stats(
            [
                [],
                [{"id": "integration:linear"}, {"id": "integration:jira"}],
                [_item("GMAIL_SEND_EMAIL", ("gmail",)), _item("x", ("users", "u1"))],
                RuntimeError("search failed"),
                [{"id": "integration:asana"}],
                [_item("create_todo", ())],
            ]
        )

        assert stats.chroma_hits == 3
        assert stats.public_hits == 3
        assert stats.per_namespace_hits == {"gmail": 1, "users::u1": 1, "default": 1}

    def test_the_preview_stops_at_ten_hits_across_results(self) -> None:
        first = [_item(f"a{i}", ("general",)) for i in range(12)]
        second = [_item("b0", ("gmail",))]

        stats = retrieval._search_hit_stats([first, second])

        assert stats.chroma_preview == [f"('general',)::a{i}" for i in range(10)]

    def test_a_short_first_result_lets_the_preview_continue_into_the_next(self) -> None:
        first = [_item(f"a{i}", ("general",)) for i in range(9)]
        second = [_item("b0", ("gmail",)), _item("b1", ("gmail",))]

        stats = retrieval._search_hit_stats([first, second])

        assert stats.chroma_preview[-1] == "('gmail',)::b0"
        assert len(stats.chroma_preview) == 10


async def _discover(
    hits: list[SearchItem], mcp_names_for: dict[str, set[str]]
) -> tuple[dict, MagicMock, MagicMock]:
    store = MagicMock()
    store.asearch = AsyncMock(return_value=hits)
    registry = MagicMock()
    registry.get_tool_names.return_value = []
    registry.get_category_of_tool.return_value = None

    async def _mcp_names(user_id: str | None) -> set[str]:
        return mcp_names_for.get(user_id or "", set())

    with (
        patch.object(retrieval, "get_tool_registry", new=AsyncMock(return_value=registry)),
        patch.object(retrieval, "_get_user_context", new=AsyncMock(return_value=({"notion"}, {}))),
        patch.object(retrieval, "_user_mcp_tool_names", new=AsyncMock(side_effect=_mcp_names)),
        patch.object(retrieval, "get_active", new=AsyncMock(return_value=set())),
        patch.object(retrieval, "log") as mock_log,
    ):
        fn = retrieval.get_retrieve_tools_function(
            tool_space="notion", include_subagents=False, limit=3
        )
        result = await fn(
            store=store,
            config={"configurable": {"user_id": "u1"}},
            query="search my pages",
            exact_tool_names=[],
        )
    return result, store, mock_log


class TestDiscovery:
    async def test_the_query_and_limit_reach_the_search_and_the_users_mcp_tools_survive(
        self,
    ) -> None:
        result, store, _ = await _discover(
            [_item("notion-search", ("notion",))], {"u1": {"notion-search"}}
        )

        assert store.asearch.await_args_list[0] == call(
            ("notion",), query="search my pages", limit=3
        )
        assert result["response"] == ["notion-search"]

    async def test_an_empty_index_warns_the_operator(self) -> None:
        _, _, mock_log = await _discover([], {})

        mock_log.warning.assert_called_once_with(
            f"{LogTag.TOOL} retrieve_tools: 0 ChromaDB hits — check that index_tools_to_store "
            "actually wrote docs for this namespace",
            tool_space="notion",
            user_id="u1",
        )
