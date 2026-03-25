"""Tests for app/agents/tools/core/retrieval.py — tool retrieval functions."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# _get_user_context
# ---------------------------------------------------------------------------


class TestGetUserContext:
    @pytest.mark.asyncio
    async def test_no_user_id_returns_defaults(self):
        from app.agents.tools.core.retrieval import _get_user_context

        with patch("app.agents.tools.core.retrieval.OAUTH_INTEGRATIONS", []):
            ns, connected, internal = await _get_user_context(
                None, "general", include_subagents=True
            )
        assert "general" in ns
        assert connected == set()
        assert internal == set()

    @pytest.mark.asyncio
    async def test_includes_internal_subagents(self):
        from app.agents.tools.core.retrieval import _get_user_context

        integration = MagicMock()
        integration.id = "gmail"
        integration.managed_by = "internal"
        integration.subagent_config.has_subagent = True

        with patch("app.agents.tools.core.retrieval.OAUTH_INTEGRATIONS", [integration]):
            ns, connected, internal = await _get_user_context(
                None, "general", include_subagents=True
            )
        assert "gmail" in internal

    @pytest.mark.asyncio
    async def test_excludes_internal_subagents_when_disabled(self):
        from app.agents.tools.core.retrieval import _get_user_context

        integration = MagicMock()
        integration.id = "gmail"
        integration.managed_by = "internal"
        integration.subagent_config.has_subagent = True

        with patch("app.agents.tools.core.retrieval.OAUTH_INTEGRATIONS", [integration]):
            ns, connected, internal = await _get_user_context(
                None, "general", include_subagents=False
            )
        assert internal == set()

    @pytest.mark.asyncio
    async def test_with_user_id_gets_namespaces(self):
        from app.agents.tools.core.retrieval import _get_user_context

        with (
            patch("app.agents.tools.core.retrieval.OAUTH_INTEGRATIONS", []),
            patch(
                "app.agents.tools.core.retrieval.get_user_available_tool_namespaces",
                new_callable=AsyncMock,
                return_value=["general", "gmail", "subagents"],
            ),
            patch(
                "app.agents.tools.core.retrieval.get_integration_by_id",
                return_value=None,
            ),
        ):
            ns, connected, internal = await _get_user_context(
                "user1", "general", include_subagents=True
            )
        assert "general" in ns
        assert "gmail" in ns
        # gmail is not a platform integration -> treated as custom -> connected
        assert "gmail" in connected

    @pytest.mark.asyncio
    async def test_user_context_exception_returns_defaults(self):
        from app.agents.tools.core.retrieval import _get_user_context

        with (
            patch("app.agents.tools.core.retrieval.OAUTH_INTEGRATIONS", []),
            patch(
                "app.agents.tools.core.retrieval.get_user_available_tool_namespaces",
                new_callable=AsyncMock,
                side_effect=RuntimeError("db fail"),
            ),
        ):
            ns, connected, internal = await _get_user_context(
                "user1", "myspace", include_subagents=True
            )
        # Falls back to initial defaults
        assert "myspace" in ns
        assert "general" in ns

    @pytest.mark.asyncio
    async def test_connected_integrations_with_subagent_config(self):
        from app.agents.tools.core.retrieval import _get_user_context

        # Platform integration with subagent config
        platform_integ = MagicMock()
        platform_integ.id = "slack"
        platform_integ.managed_by = "composio"
        platform_integ.subagent_config.has_subagent = True

        with (
            patch(
                "app.agents.tools.core.retrieval.OAUTH_INTEGRATIONS", [platform_integ]
            ),
            patch(
                "app.agents.tools.core.retrieval.get_user_available_tool_namespaces",
                new_callable=AsyncMock,
                return_value=["general", "slack", "subagents"],
            ),
            patch(
                "app.agents.tools.core.retrieval.get_integration_by_id",
                return_value=platform_integ,
            ),
        ):
            ns, connected, internal = await _get_user_context(
                "user1", "general", include_subagents=True
            )
        assert "slack" in connected


# ---------------------------------------------------------------------------
# _build_search_tasks
# ---------------------------------------------------------------------------


class TestBuildSearchTasks:
    def test_tool_space_in_namespaces(self):
        from app.agents.tools.core.retrieval import _build_search_tasks

        store = MagicMock()
        store.asearch = AsyncMock(return_value=[])
        tasks = _build_search_tasks(
            store,
            "email",
            "gmail",
            {"gmail", "general"},
            include_subagents=False,
            limit=10,
        )
        # gmail search + general search (limited)
        assert len(tasks) == 2

    def test_general_space_no_duplicate(self):
        from app.agents.tools.core.retrieval import _build_search_tasks

        store = MagicMock()
        store.asearch = AsyncMock(return_value=[])
        tasks = _build_search_tasks(
            store, "email", "general", {"general"}, include_subagents=False, limit=10
        )
        # Only one search for general (tool_space == general, skip second general search)
        assert len(tasks) == 1

    def test_includes_subagent_searches(self):
        from app.agents.tools.core.retrieval import _build_search_tasks

        store = MagicMock()
        store.asearch = AsyncMock(return_value=[])
        tasks = _build_search_tasks(
            store, "email", "general", {"general"}, include_subagents=True, limit=10
        )
        # general + subagents search + public integrations search
        assert len(tasks) == 3

    def test_tool_space_not_in_namespaces(self):
        from app.agents.tools.core.retrieval import _build_search_tasks

        store = MagicMock()
        store.asearch = AsyncMock(return_value=[])
        tasks = _build_search_tasks(
            store, "email", "slack", {"general"}, include_subagents=False, limit=10
        )
        # Only general search (slack not in namespaces)
        assert len(tasks) == 1


# ---------------------------------------------------------------------------
# _process_public_integration_result
# ---------------------------------------------------------------------------


class TestProcessPublicIntegrationResult:
    def test_processes_results(self):
        from app.agents.tools.core.retrieval import _process_public_integration_result

        items = [
            {"integration_id": "abc123", "name": "My App", "relevance_score": 0.9},
            {"integration_id": "def456", "name": None, "relevance_score": 0.5},
        ]
        result = _process_public_integration_result(items, 0)
        assert len(result) == 2
        assert result[0]["id"] == "subagent:abc123 (My App)"
        assert result[0]["score"] == pytest.approx(0.9)
        assert result[1]["id"] == "subagent:def456"

    def test_skips_missing_integration_id(self):
        from app.agents.tools.core.retrieval import _process_public_integration_result

        items = [{"name": "No ID"}]
        result = _process_public_integration_result(items, 0)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# _process_chroma_search_result
# ---------------------------------------------------------------------------


class TestProcessChromaSearchResult:
    def _make_item(self, key: str, score: float = 0.8, namespace=None, value=None):
        item = MagicMock()
        item.key = key
        item.score = score
        item.namespace = namespace
        if value is not None:
            item.value = value
        return item

    def test_regular_tool_in_available(self):
        from app.agents.tools.core.retrieval import _process_chroma_search_result

        item = self._make_item("GMAIL_SEND", namespace=("gmail",))
        registry = MagicMock()
        registry.get_category_of_tool.return_value = None

        result = _process_chroma_search_result(
            [item], 0, {"GMAIL_SEND"}, registry, include_subagents=True
        )
        assert len(result) == 1
        assert result[0]["id"] == "GMAIL_SEND"

    def test_regular_tool_not_in_available(self):
        from app.agents.tools.core.retrieval import _process_chroma_search_result

        item = self._make_item("UNKNOWN_TOOL", namespace=("gmail",))
        registry = MagicMock()
        registry.get_category_of_tool.return_value = None

        result = _process_chroma_search_result(
            [item], 0, {"GMAIL_SEND"}, registry, include_subagents=True
        )
        assert len(result) == 0

    def test_subagent_namespace_items(self):
        from app.agents.tools.core.retrieval import _process_chroma_search_result

        item = self._make_item(
            "gmail", namespace=("subagents",), value={"name": "Gmail"}
        )
        registry = MagicMock()

        result = _process_chroma_search_result(
            [item], 0, set(), registry, include_subagents=True
        )
        assert len(result) == 1
        assert result[0]["id"] == "subagent:gmail (Gmail)"

    def test_subagent_namespace_skipped_when_disabled(self):
        from app.agents.tools.core.retrieval import _process_chroma_search_result

        item = self._make_item("gmail", namespace=("subagents",))
        registry = MagicMock()

        result = _process_chroma_search_result(
            [item], 0, set(), registry, include_subagents=False
        )
        assert len(result) == 0

    def test_subagent_prefix_key(self):
        from app.agents.tools.core.retrieval import _process_chroma_search_result

        item = self._make_item("subagent:gmail", namespace=("general",))
        registry = MagicMock()

        result = _process_chroma_search_result(
            [item], 0, set(), registry, include_subagents=True
        )
        assert len(result) == 1
        assert result[0]["id"] == "subagent:gmail"

    def test_subagent_prefix_skipped_when_disabled(self):
        from app.agents.tools.core.retrieval import _process_chroma_search_result

        item = self._make_item("subagent:gmail", namespace=("general",))
        registry = MagicMock()

        result = _process_chroma_search_result(
            [item], 0, set(), registry, include_subagents=False
        )
        assert len(result) == 0

    def test_general_namespace_filters_non_webpage_tools_for_subagent(self):
        from app.agents.tools.core.retrieval import _process_chroma_search_result

        # tool_space != "general" -> general namespace should filter non-webpage tools
        item = self._make_item("create_todo", namespace=("general",))
        registry = MagicMock()
        registry.get_category_of_tool.return_value = None

        result = _process_chroma_search_result(
            [item],
            0,
            {"create_todo"},
            registry,
            include_subagents=False,
            tool_space="gmail",
        )
        assert len(result) == 0

    def test_general_namespace_allows_webpage_tools(self):
        from app.agents.tools.core.retrieval import (
            WEBPAGE_TOOLS,
            _process_chroma_search_result,
        )

        webpage_tool = WEBPAGE_TOOLS[0]
        item = self._make_item(webpage_tool, namespace=("general",))
        registry = MagicMock()
        registry.get_category_of_tool.return_value = None

        result = _process_chroma_search_result(
            [item],
            0,
            {webpage_tool},
            registry,
            include_subagents=False,
            tool_space="gmail",
        )
        assert len(result) == 1

    def test_delegated_tools_filtered_when_subagents_included(self):
        from app.agents.tools.core.retrieval import _process_chroma_search_result

        item = self._make_item("GMAIL_SEND", namespace=("gmail",))
        registry = MagicMock()
        registry.get_category_of_tool.return_value = "email_category"
        category = MagicMock()
        category.is_delegated = True
        registry.get_category.return_value = category

        result = _process_chroma_search_result(
            [item], 0, {"GMAIL_SEND"}, registry, include_subagents=True
        )
        assert len(result) == 0

    def test_subagent_key_with_existing_prefix(self):
        from app.agents.tools.core.retrieval import _process_chroma_search_result

        item = self._make_item(
            "subagent:slack", namespace=("subagents",), value={"name": "Slack"}
        )
        registry = MagicMock()

        result = _process_chroma_search_result(
            [item], 0, set(), registry, include_subagents=True
        )
        assert result[0]["id"] == "subagent:slack (Slack)"


# ---------------------------------------------------------------------------
# _process_search_results
# ---------------------------------------------------------------------------


class TestProcessSearchResults:
    @pytest.mark.asyncio
    async def test_handles_exceptions_in_results(self):
        from app.agents.tools.core.retrieval import _process_search_results

        registry = MagicMock()
        results = [RuntimeError("search fail"), []]
        processed = await _process_search_results(
            results, set(), registry, include_subagents=False
        )
        assert processed == []

    @pytest.mark.asyncio
    async def test_handles_empty_results(self):
        from app.agents.tools.core.retrieval import _process_search_results

        registry = MagicMock()
        processed = await _process_search_results(
            [[], None], set(), registry, include_subagents=False
        )
        assert processed == []

    @pytest.mark.asyncio
    async def test_routes_dict_results_to_public(self):
        from app.agents.tools.core.retrieval import _process_search_results

        registry = MagicMock()
        public_results = [
            {"integration_id": "abc", "name": "App", "relevance_score": 0.9}
        ]
        processed = await _process_search_results(
            [public_results], set(), registry, include_subagents=True
        )
        assert len(processed) == 1
        assert "subagent:abc" in str(processed[0]["id"])


# ---------------------------------------------------------------------------
# _deduplicate_and_sort
# ---------------------------------------------------------------------------


class TestDeduplicateAndSort:
    def test_deduplicates(self):
        from app.agents.tools.core.retrieval import _deduplicate_and_sort

        results = [
            {"id": "a", "score": 0.9},
            {"id": "a", "score": 0.8},
            {"id": "b", "score": 0.7},
        ]
        out = _deduplicate_and_sort(results, 10)
        assert out == ["a", "b"]

    def test_respects_limit(self):
        from app.agents.tools.core.retrieval import _deduplicate_and_sort

        results = [
            {"id": "a", "score": 0.9},
            {"id": "b", "score": 0.8},
            {"id": "c", "score": 0.7},
        ]
        out = _deduplicate_and_sort(results, 2)
        assert len(out) == 2

    def test_sorts_by_score_descending(self):
        from app.agents.tools.core.retrieval import _deduplicate_and_sort

        results = [
            {"id": "c", "score": 0.3},
            {"id": "a", "score": 0.9},
            {"id": "b", "score": 0.6},
        ]
        out = _deduplicate_and_sort(results, 10)
        assert out == ["a", "b", "c"]

    def test_handles_none_score(self):
        from app.agents.tools.core.retrieval import _deduplicate_and_sort

        results = [
            {"id": "a", "score": None},
            {"id": "b", "score": 0.5},
        ]
        out = _deduplicate_and_sort(results, 10)
        assert out == ["b", "a"]


# ---------------------------------------------------------------------------
# _inject_available_subagents
# ---------------------------------------------------------------------------


class TestInjectAvailableSubagents:
    def test_noop_when_disabled(self):
        from app.agents.tools.core.retrieval import _inject_available_subagents

        result = _inject_available_subagents(
            ["tool_a"], {"internal"}, {"connected"}, include_subagents=False
        )
        assert result == ["tool_a"]

    def test_injects_internal_and_connected(self):
        from app.agents.tools.core.retrieval import _inject_available_subagents

        integ_internal = MagicMock()
        integ_internal.name = "Internal App"
        integ_connected = MagicMock()
        integ_connected.name = "Connected App"

        with patch(
            "app.agents.tools.core.retrieval.get_integration_by_id",
            side_effect=lambda x: integ_internal if x == "int1" else integ_connected,
        ):
            result = _inject_available_subagents(
                ["tool_a"], {"int1"}, {"conn1"}, include_subagents=True
            )
        assert "tool_a" in result
        assert "subagent:int1 (Internal App)" in result
        assert "subagent:conn1 (Connected App)" in result

    def test_no_duplicates(self):
        from app.agents.tools.core.retrieval import _inject_available_subagents

        with patch(
            "app.agents.tools.core.retrieval.get_integration_by_id",
            return_value=None,
        ):
            result = _inject_available_subagents(
                ["subagent:int1"], {"int1"}, set(), include_subagents=True
            )
        # "subagent:int1" already in discovered, should not add duplicate
        assert result.count("subagent:int1") == 1


# ---------------------------------------------------------------------------
# get_retrieve_tools_function / retrieve_tools
# ---------------------------------------------------------------------------


class TestGetRetrieveToolsFunction:
    def test_returns_callable(self):
        from app.agents.tools.core.retrieval import get_retrieve_tools_function

        fn = get_retrieve_tools_function()
        assert callable(fn)

    def test_docstring_includes_subagent_section(self):
        from app.agents.tools.core.retrieval import get_retrieve_tools_function

        fn = get_retrieve_tools_function(include_subagents=True)
        assert "SUBAGENT TOOLS" in fn.__doc__

    def test_docstring_excludes_subagent_section(self):
        from app.agents.tools.core.retrieval import get_retrieve_tools_function

        fn = get_retrieve_tools_function(include_subagents=False)
        assert "SUBAGENT TOOLS" not in fn.__doc__


class TestRetrieveToolsBinding:
    @pytest.mark.asyncio
    async def test_raises_when_no_args(self):
        from app.agents.tools.core.retrieval import get_retrieve_tools_function

        fn = get_retrieve_tools_function()
        store = MagicMock()
        config: dict = {"configurable": {"user_id": "u1"}}

        with patch(
            "app.agents.tools.core.retrieval.get_tool_registry",
            new_callable=AsyncMock,
        ):
            with pytest.raises(ValueError, match="Either 'query'"):
                await fn(store=store, config=config)

    @pytest.mark.asyncio
    async def test_binding_mode_validates_tools(self):
        from app.agents.tools.core.retrieval import get_retrieve_tools_function

        fn = get_retrieve_tools_function(include_subagents=True)
        store = MagicMock()
        config: dict = {"configurable": {"user_id": "u1"}}

        mock_registry = MagicMock()
        mock_registry.get_tool_names.return_value = ["TOOL_A", "TOOL_B"]

        with patch(
            "app.agents.tools.core.retrieval.get_tool_registry",
            new_callable=AsyncMock,
            return_value=mock_registry,
        ):
            result = await fn(
                store=store,
                config=config,
                exact_tool_names=["TOOL_A", "TOOL_C", "subagent:gmail"],
            )

        assert "TOOL_A" in result["tools_to_bind"]
        assert "subagent:gmail" in result["tools_to_bind"]
        assert "TOOL_C" not in result["tools_to_bind"]

    @pytest.mark.asyncio
    async def test_binding_mode_filters_subagents_when_disabled(self):
        from app.agents.tools.core.retrieval import get_retrieve_tools_function

        fn = get_retrieve_tools_function(include_subagents=False)
        store = MagicMock()
        config: dict = {"configurable": {"user_id": "u1"}}

        mock_registry = MagicMock()
        mock_registry.get_tool_names.return_value = ["TOOL_A"]

        with patch(
            "app.agents.tools.core.retrieval.get_tool_registry",
            new_callable=AsyncMock,
            return_value=mock_registry,
        ):
            result = await fn(
                store=store,
                config=config,
                exact_tool_names=["TOOL_A", "subagent:gmail"],
            )

        assert "TOOL_A" in result["tools_to_bind"]
        assert "subagent:gmail" not in result["tools_to_bind"]


class TestRetrieveToolsDiscovery:
    @pytest.mark.asyncio
    async def test_discovery_mode(self):
        from app.agents.tools.core.retrieval import get_retrieve_tools_function

        fn = get_retrieve_tools_function(include_subagents=False, limit=5)
        store = MagicMock()
        store.asearch = AsyncMock(return_value=[])
        config: dict = {"configurable": {"user_id": "u1"}}

        mock_registry = MagicMock()
        mock_registry.get_tool_names.return_value = ["TOOL_A"]

        with (
            patch(
                "app.agents.tools.core.retrieval.get_tool_registry",
                new_callable=AsyncMock,
                return_value=mock_registry,
            ),
            patch(
                "app.agents.tools.core.retrieval._get_user_context",
                new_callable=AsyncMock,
                return_value=({"general"}, set(), set()),
            ),
        ):
            result = await fn(store=store, config=config, query="send email")

        assert result["tools_to_bind"] == []
        assert isinstance(result["response"], list)

    @pytest.mark.asyncio
    async def test_discovery_uses_metadata_fallback_for_user_id(self):
        from app.agents.tools.core.retrieval import get_retrieve_tools_function

        fn = get_retrieve_tools_function(include_subagents=False)
        store = MagicMock()
        store.asearch = AsyncMock(return_value=[])
        config: dict = {
            "configurable": {},
            "metadata": {"user_id": "from_metadata"},
        }

        mock_registry = MagicMock()
        mock_registry.get_tool_names.return_value = []

        with (
            patch(
                "app.agents.tools.core.retrieval.get_tool_registry",
                new_callable=AsyncMock,
                return_value=mock_registry,
            ),
            patch(
                "app.agents.tools.core.retrieval._get_user_context",
                new_callable=AsyncMock,
                return_value=({"general"}, set(), set()),
            ) as mock_ctx,
        ):
            await fn(store=store, config=config, query="test")

        # user_id should have been resolved from metadata
        mock_ctx.assert_called_once()
        assert mock_ctx.call_args[0][0] == "from_metadata"
