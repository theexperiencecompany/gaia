"""Tests for app/agents/tools/core/retrieval.py — tool retrieval functions."""

import asyncio
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest


def _make_subagent_mock(
    id: str, managed_by: str = "internal", name: str | None = None
) -> MagicMock:
    """Build a Subagent-shaped MagicMock for retrieval tests."""
    sa = MagicMock()
    sa.id = id
    sa.name = name or id.title()
    sa.managed_by = managed_by
    return sa


class _FlakyKey:
    """A key whose str() fails exactly once, then behaves — pins the preview
    logging failure path in _process_search_results."""

    def __init__(self, value: str) -> None:
        self._value = value
        self.calls = 0

    def __str__(self) -> str:
        self.calls += 1
        if self.calls == 1:
            raise ValueError("boom")
        return self._value


def _make_registry(
    names: list[str] | None = None, category: str | None = None
) -> MagicMock:
    registry = MagicMock()
    registry.get_tool_names.return_value = names or []
    registry.get_category_of_tool.return_value = category
    return registry


# ---------------------------------------------------------------------------
# _user_mcp_tool_names
# ---------------------------------------------------------------------------


class TestUserMcpToolNames:
    @pytest.mark.asyncio
    async def test_no_user_id_returns_empty_without_client_lookup(self):
        from app.agents.tools.core.retrieval import _user_mcp_tool_names

        with patch(
            "app.agents.tools.core.retrieval.get_mcp_client",
            new_callable=AsyncMock,
        ) as mock_client:
            names = await _user_mcp_tool_names(None)
        assert names == set()
        mock_client.assert_not_called()

    @pytest.mark.asyncio
    async def test_collects_names_across_integrations(self):
        from app.agents.tools.core.retrieval import _user_mcp_tool_names

        client = SimpleNamespace(
            _tools={
                "integration_a": [
                    SimpleNamespace(name="TOOL_1"),
                    SimpleNamespace(name="TOOL_2"),
                ],
                "integration_b": [SimpleNamespace(name="TOOL_3")],
            }
        )
        with patch(
            "app.agents.tools.core.retrieval.get_mcp_client",
            new_callable=AsyncMock,
            return_value=client,
        ) as mock_client:
            names = await _user_mcp_tool_names("u1")
        assert names == {"TOOL_1", "TOOL_2", "TOOL_3"}
        mock_client.assert_called_once_with(user_id="u1")

    @pytest.mark.asyncio
    async def test_empty_tool_map_returns_empty(self):
        from app.agents.tools.core.retrieval import _user_mcp_tool_names

        with patch(
            "app.agents.tools.core.retrieval.get_mcp_client",
            new_callable=AsyncMock,
            return_value=SimpleNamespace(_tools={}),
        ):
            names = await _user_mcp_tool_names("u1")
        assert names == set()

    @pytest.mark.asyncio
    async def test_client_failure_returns_empty_and_warns(self):
        from app.agents.tools.core.retrieval import _user_mcp_tool_names

        with (
            patch(
                "app.agents.tools.core.retrieval.get_mcp_client",
                new_callable=AsyncMock,
                side_effect=RuntimeError("conn fail"),
            ),
            patch("app.agents.tools.core.retrieval.log") as mock_log,
        ):
            names = await _user_mcp_tool_names("u1")
        assert names == set()
        mock_log.warning.assert_called_once()
        assert "failed" in mock_log.warning.call_args.args[0]
        assert mock_log.warning.call_args.kwargs == {
            "user_id": "u1",
            "error_type": "RuntimeError",
        }


# ---------------------------------------------------------------------------
# _is_platform_tool_space
# ---------------------------------------------------------------------------


class TestIsPlatformToolSpace:
    @staticmethod
    def _integration(
        tool_space: str | None,
        available: bool = True,
        has_config: bool = True,
    ) -> SimpleNamespace:
        cfg = SimpleNamespace(tool_space=tool_space) if has_config else None
        return SimpleNamespace(available=available, subagent_config=cfg)

    def test_true_for_available_platform_integration(self):
        from app.agents.tools.core.retrieval import _is_platform_tool_space

        with patch(
            "app.agents.tools.core.retrieval.OAUTH_INTEGRATIONS",
            [self._integration("gmail")],
        ):
            assert _is_platform_tool_space("gmail") is True

    def test_false_for_unavailable_integration(self):
        from app.agents.tools.core.retrieval import _is_platform_tool_space

        with patch(
            "app.agents.tools.core.retrieval.OAUTH_INTEGRATIONS",
            [self._integration("gmail", available=False)],
        ):
            assert _is_platform_tool_space("gmail") is False

    def test_false_when_subagent_config_missing(self):
        from app.agents.tools.core.retrieval import _is_platform_tool_space

        with patch(
            "app.agents.tools.core.retrieval.OAUTH_INTEGRATIONS",
            [self._integration("gmail", has_config=False)],
        ):
            assert _is_platform_tool_space("gmail") is False

    def test_false_when_no_integration_matches(self):
        from app.agents.tools.core.retrieval import _is_platform_tool_space

        with patch(
            "app.agents.tools.core.retrieval.OAUTH_INTEGRATIONS",
            [self._integration("gmail")],
        ):
            assert _is_platform_tool_space("slack") is False

    def test_any_semantics_with_multiple_integrations(self):
        from app.agents.tools.core.retrieval import _is_platform_tool_space

        with patch(
            "app.agents.tools.core.retrieval.OAUTH_INTEGRATIONS",
            [
                self._integration("gmail", has_config=False),
                self._integration("slack"),
            ],
        ):
            assert _is_platform_tool_space("slack") is True
            assert _is_platform_tool_space("gmail") is False

    def test_matches_exact_tool_space_only(self):
        from app.agents.tools.core.retrieval import _is_platform_tool_space

        with patch(
            "app.agents.tools.core.retrieval.OAUTH_INTEGRATIONS",
            [self._integration("googlecalendar")],
        ):
            assert _is_platform_tool_space("googlecalendar") is True
            assert _is_platform_tool_space("googlecalendar2") is False


# ---------------------------------------------------------------------------
# _get_user_context
# ---------------------------------------------------------------------------


class TestGetUserContext:
    @pytest.mark.asyncio
    async def test_no_user_id_returns_defaults(self):
        from app.agents.tools.core.retrieval import _get_user_context

        with patch(
            "app.agents.tools.core.retrieval.all_subagents",
            return_value=(),
        ):
            ns, connected, internal = await _get_user_context(
                None, "general", include_subagents=True
            )
        assert "general" in ns
        assert connected == {}
        assert internal == set()

    @pytest.mark.asyncio
    async def test_includes_internal_subagents(self):
        from app.agents.tools.core.retrieval import _get_user_context

        with patch(
            "app.agents.tools.core.retrieval.all_subagents",
            return_value=(_make_subagent_mock("gmail", "internal"),),
        ):
            ns, connected, internal = await _get_user_context(
                None, "general", include_subagents=True
            )
        assert "gmail" in internal

    @pytest.mark.asyncio
    async def test_excludes_internal_subagents_when_disabled(self):
        from app.agents.tools.core.retrieval import _get_user_context

        with patch(
            "app.agents.tools.core.retrieval.all_subagents",
            return_value=(_make_subagent_mock("gmail", "internal"),),
        ):
            ns, connected, internal = await _get_user_context(
                None, "general", include_subagents=False
            )
        assert internal == set()

    @pytest.mark.asyncio
    async def test_internal_subagents_only_managed_by_internal(self):
        from app.agents.tools.core.retrieval import _get_user_context

        ext = _make_subagent_mock("external_sa", managed_by="composio")
        internal = _make_subagent_mock("int_sa", managed_by="internal")
        with patch(
            "app.agents.tools.core.retrieval.all_subagents",
            return_value=(ext, internal),
        ):
            ns, connected, internal_set = await _get_user_context(
                None, "general", include_subagents=True
            )
        assert internal_set == {"int_sa"}

    @pytest.mark.asyncio
    async def test_with_user_id_resolves_namespaces_and_connected(self):
        from app.agents.tools.core.retrieval import _get_user_context

        sa_gmail = _make_subagent_mock("gmail", name="Gmail")
        with (
            patch(
                "app.agents.tools.core.retrieval.all_subagents",
                return_value=(),
            ),
            patch(
                "app.agents.tools.core.retrieval.get_user_available_tool_namespaces",
                new_callable=AsyncMock,
                return_value=["general", "gmail", "custom_1"],
            ),
            patch(
                "app.agents.tools.core.retrieval.get_all_integrations_status",
                new_callable=AsyncMock,
                return_value={"gmail": True, "custom_1": True},
            ),
            patch(
                "app.agents.tools.core.retrieval.get_subagent_by_id",
                side_effect=lambda iid: sa_gmail if iid == "gmail" else None,
            ),
            patch(
                "app.agents.tools.core.retrieval.get_user_integrations",
                new_callable=AsyncMock,
                return_value=SimpleNamespace(
                    integrations=[
                        SimpleNamespace(
                            integration_id="custom_1",
                            integration=SimpleNamespace(name="Custom One"),
                        )
                    ]
                ),
            ),
        ):
            ns, connected, internal = await _get_user_context(
                "user1", "general", include_subagents=True
            )
        assert "general" in ns
        assert "gmail" in ns
        assert connected == {"gmail": "Gmail", "custom_1": "Custom One"}
        assert internal == set()

    @pytest.mark.asyncio
    async def test_connected_integrations_with_subagent_config(self):
        from app.agents.tools.core.retrieval import _get_user_context

        slack_subagent = _make_subagent_mock("slack", "composio", name="Slack")

        with (
            patch(
                "app.agents.tools.core.retrieval.all_subagents",
                return_value=(slack_subagent,),
            ),
            patch(
                "app.agents.tools.core.retrieval.get_user_available_tool_namespaces",
                new_callable=AsyncMock,
                return_value=["general", "slack", "subagents"],
            ),
            patch(
                "app.agents.tools.core.retrieval.get_all_integrations_status",
                new_callable=AsyncMock,
                return_value={"slack": True},
            ),
            patch(
                "app.agents.tools.core.retrieval.get_subagent_by_id",
                return_value=slack_subagent,
            ),
        ):
            ns, connected, internal = await _get_user_context(
                "user1", "general", include_subagents=True
            )
        assert connected == {"slack": "Slack"}
        assert internal == set()

    @pytest.mark.asyncio
    async def test_platform_tool_space_seeded_when_cache_empty(self):
        from app.agents.tools.core.retrieval import _get_user_context

        with (
            patch(
                "app.agents.tools.core.retrieval.all_subagents",
                return_value=(),
            ),
            patch(
                "app.agents.tools.core.retrieval.get_user_available_tool_namespaces",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            ns, _, _ = await _get_user_context("u1", "gmail", include_subagents=False)
        assert ns == {"general", "gmail"}

    @pytest.mark.asyncio
    async def test_platform_seed_survives_union_with_cache_namespaces(self):
        from app.agents.tools.core.retrieval import _get_user_context

        with (
            patch(
                "app.agents.tools.core.retrieval.all_subagents",
                return_value=(),
            ),
            patch(
                "app.agents.tools.core.retrieval.get_user_available_tool_namespaces",
                new_callable=AsyncMock,
                return_value=["custom_mcp"],
            ),
        ):
            ns, _, _ = await _get_user_context("u1", "gmail", include_subagents=False)
        assert ns == {"general", "gmail", "custom_mcp"}

    @pytest.mark.asyncio
    async def test_custom_tool_space_not_seeded(self):
        from app.agents.tools.core.retrieval import _get_user_context

        with (
            patch(
                "app.agents.tools.core.retrieval.all_subagents",
                return_value=(),
            ),
            patch(
                "app.agents.tools.core.retrieval.get_user_available_tool_namespaces",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            ns, _, _ = await _get_user_context(
                "u1", "my_custom_mcp", include_subagents=False
            )
        assert ns == {"general"}
        assert "my_custom_mcp" not in ns

    @pytest.mark.asyncio
    async def test_no_user_id_skips_namespace_query(self):
        from app.agents.tools.core.retrieval import _get_user_context

        with (
            patch(
                "app.agents.tools.core.retrieval.all_subagents",
                return_value=(),
            ),
            patch(
                "app.agents.tools.core.retrieval.get_user_available_tool_namespaces",
                new_callable=AsyncMock,
            ) as mock_ns,
        ):
            ns, connected, internal = await _get_user_context(
                None, "general", include_subagents=True
            )
        mock_ns.assert_not_called()
        assert ns == {"general"}
        assert connected == {}
        assert internal == set()

    @pytest.mark.asyncio
    async def test_subagents_disabled_skips_connected_resolution(self):
        from app.agents.tools.core.retrieval import _get_user_context

        with (
            patch(
                "app.agents.tools.core.retrieval.all_subagents",
                return_value=(),
            ),
            patch(
                "app.agents.tools.core.retrieval.get_user_available_tool_namespaces",
                new_callable=AsyncMock,
                return_value=["gmail"],
            ),
            patch(
                "app.agents.tools.core.retrieval._resolve_connected_subagents",
                new_callable=AsyncMock,
            ) as mock_resolve,
        ):
            ns, connected, internal = await _get_user_context(
                "u1", "general", include_subagents=False
            )
        mock_resolve.assert_not_called()
        assert "gmail" in ns
        assert connected == {}
        assert internal == set()

    @pytest.mark.asyncio
    async def test_user_context_exception_returns_defaults(self):
        from app.agents.tools.core.retrieval import _get_user_context

        with (
            patch(
                "app.agents.tools.core.retrieval.all_subagents",
                return_value=(),
            ),
            patch(
                "app.agents.tools.core.retrieval.get_user_available_tool_namespaces",
                new_callable=AsyncMock,
                side_effect=RuntimeError("db fail"),
            ),
            patch("app.agents.tools.core.retrieval.log") as mock_log,
        ):
            ns, connected, internal = await _get_user_context(
                "user1", "myspace", include_subagents=True
            )
        assert "general" in ns
        assert "myspace" not in ns
        assert connected == {}
        mock_log.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_namespace_failure_with_subagents_disabled_still_returns_defaults(
        self,
    ):
        from app.agents.tools.core.retrieval import _get_user_context

        with (
            patch(
                "app.agents.tools.core.retrieval.all_subagents",
                return_value=(),
            ),
            patch(
                "app.agents.tools.core.retrieval.get_user_available_tool_namespaces",
                new_callable=AsyncMock,
                side_effect=RuntimeError("db down"),
            ),
            patch("app.agents.tools.core.retrieval.log") as mock_log,
        ):
            ns, connected, internal = await _get_user_context(
                "u1", "general", include_subagents=False
            )
        assert ns == {"general"}
        assert connected == {}
        assert internal == set()
        mock_log.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_logs_resolved_namespaces(self):
        from app.agents.tools.core.retrieval import _get_user_context

        with (
            patch(
                "app.agents.tools.core.retrieval.all_subagents",
                return_value=(),
            ),
            patch(
                "app.agents.tools.core.retrieval.get_user_available_tool_namespaces",
                new_callable=AsyncMock,
                return_value=["gmail"],
            ),
            patch("app.agents.tools.core.retrieval.log") as mock_log,
        ):
            await _get_user_context("u1", "general", include_subagents=False)
        mock_log.info.assert_called_once()
        assert mock_log.info.call_args.kwargs == {
            "user_id": "u1",
            "namespaces": {"general", "gmail"},
        }


# ---------------------------------------------------------------------------
# _resolve_connected_subagents
# ---------------------------------------------------------------------------


class TestResolveConnectedSubagents:
    @pytest.mark.asyncio
    async def test_platform_names_from_registry_custom_from_user_integrations(self):
        from app.agents.tools.core.retrieval import _resolve_connected_subagents

        sa_gmail = _make_subagent_mock("gmail", name="Gmail")
        with (
            patch(
                "app.agents.tools.core.retrieval.get_all_integrations_status",
                new_callable=AsyncMock,
                return_value={"gmail": True, "custom_1": True},
            ),
            patch(
                "app.agents.tools.core.retrieval.get_subagent_by_id",
                side_effect=lambda iid: sa_gmail if iid == "gmail" else None,
            ),
            patch(
                "app.agents.tools.core.retrieval.get_user_integrations",
                new_callable=AsyncMock,
                return_value=SimpleNamespace(
                    integrations=[
                        SimpleNamespace(
                            integration_id="custom_1",
                            integration=SimpleNamespace(name="Custom One"),
                        )
                    ]
                ),
            ) as mock_user_ints,
        ):
            connected = await _resolve_connected_subagents("u1")
        assert connected == {"gmail": "Gmail", "custom_1": "Custom One"}
        mock_user_ints.assert_called_once_with("u1")

    @pytest.mark.asyncio
    async def test_custom_without_user_integration_name_resolves_none(self):
        from app.agents.tools.core.retrieval import _resolve_connected_subagents

        with (
            patch(
                "app.agents.tools.core.retrieval.get_all_integrations_status",
                new_callable=AsyncMock,
                return_value={"custom_1": True},
            ),
            patch(
                "app.agents.tools.core.retrieval.get_subagent_by_id",
                return_value=None,
            ),
            patch(
                "app.agents.tools.core.retrieval.get_user_integrations",
                new_callable=AsyncMock,
                return_value=SimpleNamespace(integrations=[]),
            ),
        ):
            connected = await _resolve_connected_subagents("u1")
        assert connected == {"custom_1": None}

    @pytest.mark.asyncio
    async def test_disconnected_integrations_skipped(self):
        from app.agents.tools.core.retrieval import _resolve_connected_subagents

        with (
            patch(
                "app.agents.tools.core.retrieval.get_all_integrations_status",
                new_callable=AsyncMock,
                return_value={"zombie": False, "gmail": False},
            ),
            patch(
                "app.agents.tools.core.retrieval.get_subagent_by_id",
                return_value=None,
            ) as mock_subagent,
            patch(
                "app.agents.tools.core.retrieval.get_user_integrations",
                new_callable=AsyncMock,
            ) as mock_user_ints,
        ):
            connected = await _resolve_connected_subagents("u1")
        assert connected == {}
        mock_subagent.assert_not_called()
        mock_user_ints.assert_not_called()


# ---------------------------------------------------------------------------
# _build_search_tasks
# ---------------------------------------------------------------------------


class TestBuildSearchTasks:
    @pytest.mark.asyncio
    async def test_exact_asearch_calls_for_tool_space_and_general(self):
        from app.agents.tools.core.retrieval import _build_search_tasks

        store = MagicMock()
        store.asearch = AsyncMock(return_value=[])
        tasks = _build_search_tasks(
            store,
            "find emails",
            "gmail",
            {"gmail", "general"},
            include_subagents=False,
            limit=7,
        )
        assert store.asearch.call_args_list == [
            call(("gmail",), query="find emails", limit=7),
            call(("general",), query="find emails", limit=5),
        ]
        await asyncio.gather(*tasks)

    @pytest.mark.asyncio
    async def test_general_space_single_search_exact_args(self):
        from app.agents.tools.core.retrieval import _build_search_tasks

        store = MagicMock()
        store.asearch = AsyncMock(return_value=[])
        tasks = _build_search_tasks(
            store,
            "send email",
            "general",
            {"general"},
            include_subagents=False,
            limit=3,
        )
        assert store.asearch.call_args_list == [
            call(("general",), query="send email", limit=3),
        ]
        await asyncio.gather(*tasks)

    @pytest.mark.asyncio
    async def test_subagent_searches_exact_args(self):
        from app.agents.tools.core.retrieval import _build_search_tasks

        store = MagicMock()
        store.asearch = AsyncMock(return_value=[])
        with patch(
            "app.agents.tools.core.retrieval.search_public_integrations",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_public:
            tasks = _build_search_tasks(
                store,
                "email",
                "gmail",
                {"gmail", "general"},
                include_subagents=True,
                limit=10,
            )
        assert store.asearch.call_args_list == [
            call(("gmail",), query="email", limit=10),
            call(("general",), query="email", limit=5),
            call(("subagents",), query="email", limit=15),
        ]
        mock_public.assert_called_once_with(query="email", limit=15)
        await asyncio.gather(*tasks)

    @pytest.mark.asyncio
    async def test_desktop_search_exact_args_when_enabled(self):
        from app.agents.tools.core.retrieval import (
            DESKTOP_TOOL_SPACE,
            _build_search_tasks,
        )

        store = MagicMock()
        store.asearch = AsyncMock(return_value=[])
        tasks = _build_search_tasks(
            store,
            "email",
            "general",
            {"general"},
            include_subagents=False,
            limit=10,
            include_desktop=True,
        )
        assert store.asearch.call_args_list == [
            call(("general",), query="email", limit=10),
            call((DESKTOP_TOOL_SPACE,), query="email", limit=10),
        ]
        await asyncio.gather(*tasks)

    @pytest.mark.asyncio
    async def test_no_desktop_search_when_disabled(self):
        from app.agents.tools.core.retrieval import _build_search_tasks

        store = MagicMock()
        store.asearch = AsyncMock(return_value=[])
        tasks = _build_search_tasks(
            store,
            "email",
            "general",
            {"general"},
            include_subagents=False,
            limit=10,
            include_desktop=False,
        )
        assert len(store.asearch.call_args_list) == 1
        assert store.asearch.call_args_list[0].args == (("general",),)
        await asyncio.gather(*tasks)

    @pytest.mark.asyncio
    async def test_refused_search_when_tool_space_not_in_namespaces(self):
        from app.agents.tools.core.retrieval import _build_search_tasks

        store = MagicMock()
        store.asearch = AsyncMock(return_value=[])
        with patch("app.agents.tools.core.retrieval.log") as mock_log:
            tasks = _build_search_tasks(
                store,
                "email",
                "slack",
                {"general"},
                include_subagents=False,
                limit=10,
            )
        # Only the general search is issued; the slack search is refused.
        assert store.asearch.call_args_list == [
            call(("general",), query="email", limit=5),
        ]
        mock_log.warning.assert_called_once()
        assert "refused search" in mock_log.warning.call_args.args[0]
        assert mock_log.warning.call_args.kwargs == {
            "tool_space": "slack",
            "user_namespaces": ["general"],
        }
        await asyncio.gather(*tasks)

    @pytest.mark.asyncio
    async def test_no_public_search_when_subagents_disabled(self):
        from app.agents.tools.core.retrieval import _build_search_tasks

        store = MagicMock()
        store.asearch = AsyncMock(return_value=[])
        with patch(
            "app.agents.tools.core.retrieval.search_public_integrations",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_public:
            tasks = _build_search_tasks(
                store,
                "email",
                "gmail",
                {"gmail", "general"},
                include_subagents=False,
                limit=10,
            )
        mock_public.assert_not_called()
        await asyncio.gather(*tasks)


# ---------------------------------------------------------------------------
# _process_public_integration_result
# ---------------------------------------------------------------------------


class TestProcessPublicIntegrationResult:
    def test_processes_results_exact_keys(self):
        from app.agents.tools.core.retrieval import _process_public_integration_result

        items = [
            {"integration_id": "abc123", "name": "My App", "relevance_score": 0.9},
            {"integration_id": "def456", "name": None, "relevance_score": 0.5},
        ]
        result = _process_public_integration_result(items)
        assert result == [
            {"id": "subagent:abc123 (My App)", "score": 0.9},
            {"id": "subagent:def456", "score": 0.5},
        ]

    def test_skips_missing_integration_id(self):
        from app.agents.tools.core.retrieval import _process_public_integration_result

        items = [{"name": "No ID"}]
        result = _process_public_integration_result(items)
        assert len(result) == 0

    def test_skips_empty_integration_id(self):
        from app.agents.tools.core.retrieval import _process_public_integration_result

        items = [{"integration_id": "", "name": "Empty ID"}]
        result = _process_public_integration_result(items)
        assert result == []

    def test_missing_relevance_score_defaults_to_zero(self):
        from app.agents.tools.core.retrieval import _process_public_integration_result

        items = [{"integration_id": "abc123", "name": "My App"}]
        result = _process_public_integration_result(items)
        assert result == [{"id": "subagent:abc123 (My App)", "score": 0}]

    def test_empty_input_returns_empty(self):
        from app.agents.tools.core.retrieval import _process_public_integration_result

        assert _process_public_integration_result([]) == []


# ---------------------------------------------------------------------------
# _process_chroma_search_result
# ---------------------------------------------------------------------------


class TestProcessChromaSearchResult:
    def _make_item(
        self, key: str, score: float = 0.8, namespace=None, value=None
    ) -> MagicMock:
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
            [item], {"GMAIL_SEND"}, registry, include_subagents=True
        )
        assert result == [{"id": "GMAIL_SEND", "score": 0.8}]

    def test_regular_tool_not_in_available(self):
        from app.agents.tools.core.retrieval import _process_chroma_search_result

        item = self._make_item("UNKNOWN_TOOL", namespace=("gmail",))
        registry = MagicMock()
        registry.get_category_of_tool.return_value = None

        result = _process_chroma_search_result(
            [item], {"GMAIL_SEND"}, registry, include_subagents=True
        )
        assert len(result) == 0

    def test_item_without_namespace_attribute_processed_as_regular_tool(self):
        from app.agents.tools.core.retrieval import _process_chroma_search_result

        item = SimpleNamespace(key="TOOL_A", score=0.7)
        registry = MagicMock()
        registry.get_category_of_tool.return_value = None

        result = _process_chroma_search_result(
            [item], {"TOOL_A"}, registry, include_subagents=True
        )
        assert result == [{"id": "TOOL_A", "score": 0.7}]

    def test_score_none_preserved(self):
        from app.agents.tools.core.retrieval import _process_chroma_search_result

        item = self._make_item("TOOL_A", score=None, namespace=("general",))
        registry = MagicMock()
        registry.get_category_of_tool.return_value = None

        result = _process_chroma_search_result(
            [item], {"TOOL_A"}, registry, include_subagents=False
        )
        assert result == [{"id": "TOOL_A", "score": None}]

    def test_subagent_namespace_items(self):
        from app.agents.tools.core.retrieval import _process_chroma_search_result

        item = self._make_item("gmail", namespace=("subagents",), value={"name": "Gmail"})
        registry = MagicMock()

        result = _process_chroma_search_result([item], set(), registry, include_subagents=True)
        assert result == [{"id": "subagent:gmail (Gmail)", "score": 0.8}]

    def test_subagent_namespace_skipped_when_disabled(self):
        from app.agents.tools.core.retrieval import _process_chroma_search_result

        item = self._make_item("gmail", namespace=("subagents",))
        registry = MagicMock()

        result = _process_chroma_search_result([item], set(), registry, include_subagents=False)
        assert len(result) == 0

    def test_subagent_namespace_without_name_no_parens(self):
        from app.agents.tools.core.retrieval import _process_chroma_search_result

        item = self._make_item("gmail", namespace=("subagents",))
        registry = MagicMock()

        result = _process_chroma_search_result([item], set(), registry, include_subagents=True)
        assert result == [{"id": "subagent:gmail", "score": 0.8}]

    def test_subagent_namespace_value_not_dict_no_parens(self):
        from app.agents.tools.core.retrieval import _process_chroma_search_result

        item = self._make_item(
            "gmail", namespace=("subagents",), value="not a dict"
        )
        registry = MagicMock()

        result = _process_chroma_search_result([item], set(), registry, include_subagents=True)
        assert result == [{"id": "subagent:gmail", "score": 0.8}]

    def test_subagent_namespace_item_skips_available_check(self):
        from app.agents.tools.core.retrieval import _process_chroma_search_result

        item = self._make_item(
            "not_a_tool", namespace=("subagents",), value={"name": "Nope"}
        )
        registry = MagicMock()

        result = _process_chroma_search_result([item], set(), registry, include_subagents=True)
        assert result == [{"id": "subagent:not_a_tool (Nope)", "score": 0.8}]

    def test_subagent_namespace_key_with_prefix_and_name(self):
        from app.agents.tools.core.retrieval import _process_chroma_search_result

        item = self._make_item(
            "subagent:slack", namespace=("subagents",), value={"name": "Slack"}
        )
        registry = MagicMock()

        result = _process_chroma_search_result([item], set(), registry, include_subagents=True)
        assert result == [{"id": "subagent:slack (Slack)", "score": 0.8}]

    def test_subagent_prefix_key(self):
        from app.agents.tools.core.retrieval import _process_chroma_search_result

        item = self._make_item("subagent:gmail", namespace=("general",))
        registry = MagicMock()

        result = _process_chroma_search_result([item], set(), registry, include_subagents=True)
        assert result == [{"id": "subagent:gmail", "score": 0.8}]

    def test_subagent_prefix_skipped_when_disabled(self):
        from app.agents.tools.core.retrieval import _process_chroma_search_result

        item = self._make_item("subagent:gmail", namespace=("general",))
        registry = MagicMock()

        result = _process_chroma_search_result([item], set(), registry, include_subagents=False)
        assert len(result) == 0

    def test_general_namespace_filters_non_webpage_tools_for_subagent(self):
        from app.agents.tools.core.retrieval import _process_chroma_search_result

        item = self._make_item("create_todo", namespace=("general",))
        registry = MagicMock()
        registry.get_category_of_tool.return_value = None

        result = _process_chroma_search_result(
            [item],
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
            {webpage_tool},
            registry,
            include_subagents=False,
            tool_space="gmail",
        )
        assert len(result) == 1

    def test_general_namespace_no_filter_when_tool_space_is_general(self):
        from app.agents.tools.core.retrieval import _process_chroma_search_result

        item = self._make_item("create_todo", namespace=("general",))
        registry = MagicMock()
        registry.get_category_of_tool.return_value = None

        result = _process_chroma_search_result(
            [item],
            {"create_todo"},
            registry,
            include_subagents=False,
            tool_space="general",
        )
        assert result == [{"id": "create_todo", "score": 0.8}]

    def test_delegated_tools_filtered_when_subagents_included(self):
        from app.agents.tools.core.retrieval import _process_chroma_search_result

        item = self._make_item("GMAIL_SEND", namespace=("gmail",))
        registry = MagicMock()
        registry.get_category_of_tool.return_value = "email_category"
        category = MagicMock()
        category.is_delegated = True
        registry.get_category.return_value = category

        result = _process_chroma_search_result(
            [item], {"GMAIL_SEND"}, registry, include_subagents=True
        )
        assert len(result) == 0

    def test_non_delegated_category_kept(self):
        from app.agents.tools.core.retrieval import _process_chroma_search_result

        item = self._make_item("GMAIL_SEND", namespace=("gmail",))
        registry = MagicMock()
        registry.get_category_of_tool.return_value = "email_category"
        category = MagicMock()
        category.is_delegated = False
        registry.get_category.return_value = category

        result = _process_chroma_search_result(
            [item], {"GMAIL_SEND"}, registry, include_subagents=True
        )
        assert result == [{"id": "GMAIL_SEND", "score": 0.8}]

    def test_unknown_category_object_kept(self):
        from app.agents.tools.core.retrieval import _process_chroma_search_result

        item = self._make_item("GMAIL_SEND", namespace=("gmail",))
        registry = MagicMock()
        registry.get_category_of_tool.return_value = "email_category"
        registry.get_category.return_value = None

        result = _process_chroma_search_result(
            [item], {"GMAIL_SEND"}, registry, include_subagents=True
        )
        assert result == [{"id": "GMAIL_SEND", "score": 0.8}]

    def test_delegated_filter_skipped_when_subagents_not_included(self):
        from app.agents.tools.core.retrieval import _process_chroma_search_result

        item = self._make_item("GMAIL_SEND", namespace=("gmail",))
        registry = MagicMock()
        registry.get_category_of_tool.return_value = "email_category"
        category = MagicMock()
        category.is_delegated = True
        registry.get_category.return_value = category

        result = _process_chroma_search_result(
            [item], {"GMAIL_SEND"}, registry, include_subagents=False
        )
        assert result == [{"id": "GMAIL_SEND", "score": 0.8}]


# ---------------------------------------------------------------------------
# _process_search_results
# ---------------------------------------------------------------------------


class TestProcessSearchResults:
    @pytest.mark.asyncio
    async def test_handles_exceptions_in_results(self):
        from app.agents.tools.core.retrieval import _process_search_results

        registry = MagicMock()
        results = [RuntimeError("search fail"), []]
        processed = await _process_search_results(results, set(), registry, include_subagents=False)
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
        public_results = [{"integration_id": "abc", "name": "App", "relevance_score": 0.9}]
        processed = await _process_search_results(
            [public_results], set(), registry, include_subagents=True
        )
        assert processed == [{"id": "subagent:abc (App)", "score": 0.9}]

    @pytest.mark.asyncio
    async def test_chroma_items_processed_with_score(self):
        from app.agents.tools.core.retrieval import _process_search_results

        registry = MagicMock()
        registry.get_category_of_tool.return_value = None
        item = SimpleNamespace(key="TOOL_A", namespace=("gmail",), score=0.9)
        processed = await _process_search_results(
            [[item]], {"TOOL_A"}, registry, include_subagents=False, tool_space="gmail"
        )
        assert processed == [{"id": "TOOL_A", "score": 0.9}]

    @pytest.mark.asyncio
    async def test_general_hits_filtered_when_tool_space_is_subagent_space(self):
        from app.agents.tools.core.retrieval import _process_search_results

        registry = MagicMock()
        registry.get_category_of_tool.return_value = None
        item = SimpleNamespace(key="create_todo", namespace=("general",), score=0.9)
        processed = await _process_search_results(
            [[item]], {"create_todo"}, registry, include_subagents=False, tool_space="gmail"
        )
        assert processed == []

    @pytest.mark.asyncio
    async def test_general_hits_kept_when_tool_space_is_general(self):
        from app.agents.tools.core.retrieval import _process_search_results

        registry = MagicMock()
        registry.get_category_of_tool.return_value = None
        item = SimpleNamespace(key="create_todo", namespace=("general",), score=0.9)
        processed = await _process_search_results(
            [[item]],
            {"create_todo"},
            registry,
            include_subagents=False,
            tool_space="general",
        )
        assert processed == [{"id": "create_todo", "score": 0.9}]

    @pytest.mark.asyncio
    async def test_preview_log_debug_exact(self):
        from app.agents.tools.core.retrieval import _process_search_results

        registry = MagicMock()
        registry.get_category_of_tool.return_value = None
        item = SimpleNamespace(key="TOOL_A", namespace=("gmail",), score=0.9)
        with patch("app.agents.tools.core.retrieval.log") as mock_log:
            processed = await _process_search_results(
                [[item]], {"TOOL_A"}, registry, include_subagents=False, tool_space="gmail"
            )
        assert processed == [{"id": "TOOL_A", "score": 0.9}]
        mock_log.debug.assert_called_once()
        assert mock_log.debug.call_args.kwargs == {
            "task_index": 0,
            "tool_space": "gmail",
            "hit_count": 1,
            "preview": [{"key": "TOOL_A", "namespace": ("gmail",), "score": 0.9}],
        }

    @pytest.mark.asyncio
    async def test_preview_failure_logs_and_continues(self):
        from app.agents.tools.core.retrieval import _process_search_results

        registry = MagicMock()
        registry.get_category_of_tool.return_value = None
        item = SimpleNamespace(key=_FlakyKey("TOOL_A"), namespace=("general",), score=0.9)
        with patch("app.agents.tools.core.retrieval.log") as mock_log:
            processed = await _process_search_results(
                [[item]], {"TOOL_A"}, registry, include_subagents=False, tool_space="general"
            )
        # The first str(item.key) raises inside the preview build; processing
        # re-reads the key and succeeds.
        assert processed == [{"id": "TOOL_A", "score": 0.9}]
        failed = [
            c
            for c in mock_log.debug.call_args_list
            if "log failed" in c.args[0]
        ]
        assert len(failed) == 1
        assert failed[0].kwargs == {"task_index": 0, "error_type": "ValueError"}


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

    def test_keeps_first_occurrence(self):
        from app.agents.tools.core.retrieval import _deduplicate_and_sort

        results = [
            {"id": "a", "score": 0.9},
            {"id": "a", "score": 0.1},
            {"id": "b", "score": 0.5},
        ]
        out = _deduplicate_and_sort(results, 10)
        # The first "a" (score 0.9) is the one kept, so it outranks "b".
        assert out == ["a", "b"]

    def test_respects_limit(self):
        from app.agents.tools.core.retrieval import _deduplicate_and_sort

        results = [
            {"id": "a", "score": 0.9},
            {"id": "b", "score": 0.8},
            {"id": "c", "score": 0.7},
        ]
        out = _deduplicate_and_sort(results, 2)
        assert out == ["a", "b"]

    def test_limit_zero_returns_empty(self):
        from app.agents.tools.core.retrieval import _deduplicate_and_sort

        results = [{"id": "a", "score": 0.9}]
        assert _deduplicate_and_sort(results, 0) == []

    def test_empty_results(self):
        from app.agents.tools.core.retrieval import _deduplicate_and_sort

        assert _deduplicate_and_sort([], 10) == []

    def test_sorts_by_score_descending(self):
        from app.agents.tools.core.retrieval import _deduplicate_and_sort

        results = [
            {"id": "c", "score": 0.3},
            {"id": "a", "score": 0.9},
            {"id": "b", "score": 0.6},
        ]
        out = _deduplicate_and_sort(results, 10)
        assert out == ["a", "b", "c"]

    def test_stable_order_for_equal_scores(self):
        from app.agents.tools.core.retrieval import _deduplicate_and_sort

        results = [
            {"id": "b", "score": 0.5},
            {"id": "a", "score": 0.5},
        ]
        assert _deduplicate_and_sort(results, 10) == ["b", "a"]

    def test_handles_none_score(self):
        from app.agents.tools.core.retrieval import _deduplicate_and_sort

        results = [
            {"id": "a", "score": None},
            {"id": "b", "score": 0.5},
        ]
        out = _deduplicate_and_sort(results, 10)
        assert out == ["b", "a"]

    def test_returns_string_ids(self):
        from app.agents.tools.core.retrieval import _deduplicate_and_sort

        results = [{"id": 7, "score": 0.5}]
        assert _deduplicate_and_sort(results, 10) == ["7"]


# ---------------------------------------------------------------------------
# _inject_available_subagents
# ---------------------------------------------------------------------------


class TestInjectAvailableSubagents:
    def test_noop_when_disabled(self):
        from app.agents.tools.core.retrieval import _inject_available_subagents

        result = _inject_available_subagents(
            ["tool_a"], {"internal"}, {"connected": None}, include_subagents=False
        )
        assert result == ["tool_a"]

    def test_empty_inputs(self):
        from app.agents.tools.core.retrieval import _inject_available_subagents

        with patch(
            "app.agents.tools.core.retrieval.get_subagent_by_id",
            return_value=None,
        ):
            result = _inject_available_subagents([], set(), {}, include_subagents=True)
        assert result == []

    def test_preserves_discovered_order_and_keeps_named_entries(self):
        from app.agents.tools.core.retrieval import _inject_available_subagents

        result = _inject_available_subagents(
            ["tool_a", "subagent:zz (ZZ)", "tool_b"], set(), {}, include_subagents=True
        )
        assert result == ["tool_a", "subagent:zz (ZZ)", "tool_b"]

    def test_upgrades_unnamed_hit_with_connected_name(self):
        from app.agents.tools.core.retrieval import _inject_available_subagents

        with patch(
            "app.agents.tools.core.retrieval.get_subagent_by_id",
            return_value=None,
        ):
            result = _inject_available_subagents(
                ["subagent:abc"], set(), {"abc": "ABC App"}, include_subagents=True
            )
        assert result == ["subagent:abc (ABC App)"]

    def test_upgrades_unnamed_hit_with_registry_name(self):
        from app.agents.tools.core.retrieval import _inject_available_subagents

        sa = MagicMock()
        sa.name = "Registry Name"
        with patch(
            "app.agents.tools.core.retrieval.get_subagent_by_id",
            return_value=sa,
        ):
            result = _inject_available_subagents(
                ["subagent:abc"], set(), {}, include_subagents=True
            )
        assert result == ["subagent:abc (Registry Name)"]

    def test_unnamed_hit_unresolvable_stays_bare(self):
        from app.agents.tools.core.retrieval import _inject_available_subagents

        with patch(
            "app.agents.tools.core.retrieval.get_subagent_by_id",
            return_value=None,
        ):
            result = _inject_available_subagents(
                ["subagent:abc"], set(), {}, include_subagents=True
            )
        assert result == ["subagent:abc"]

    def test_connected_name_preferred_over_registry(self):
        from app.agents.tools.core.retrieval import _inject_available_subagents

        sa = MagicMock()
        sa.name = "Registry Name"
        with patch(
            "app.agents.tools.core.retrieval.get_subagent_by_id",
            return_value=sa,
        ) as mock_subagent:
            result = _inject_available_subagents(
                ["subagent:abc"], set(), {"abc": "Connected"}, include_subagents=True
            )
        assert result == ["subagent:abc (Connected)"]
        mock_subagent.assert_not_called()

    def test_named_hit_kept_as_is_even_when_connected_name_differs(self):
        from app.agents.tools.core.retrieval import _inject_available_subagents

        result = _inject_available_subagents(
            ["subagent:abc (Existing)"], set(), {"abc": "Connected"}, include_subagents=True
        )
        assert result == ["subagent:abc (Existing)"]

    def test_named_and_unnamed_forms_collapse(self):
        from app.agents.tools.core.retrieval import _inject_available_subagents

        with patch(
            "app.agents.tools.core.retrieval.get_subagent_by_id",
            return_value=None,
        ):
            result = _inject_available_subagents(
                ["subagent:abc", "subagent:abc (ABC App)"],
                set(),
                {"abc": "ABC App"},
                include_subagents=True,
            )
        assert result == ["subagent:abc (ABC App)"]

    def test_injects_internal_and_connected(self):
        from app.agents.tools.core.retrieval import _inject_available_subagents

        sa_internal = MagicMock()
        sa_internal.name = "Internal App"

        with patch(
            "app.agents.tools.core.retrieval.get_subagent_by_id",
            return_value=sa_internal,
        ):
            result = _inject_available_subagents(
                ["tool_a"],
                {"int1"},
                {"conn1": "Connected App"},
                include_subagents=True,
            )
        assert result == [
            "tool_a",
            "subagent:int1 (Internal App)",
            "subagent:conn1 (Connected App)",
        ]

    def test_internal_without_registry_name_bare(self):
        from app.agents.tools.core.retrieval import _inject_available_subagents

        with patch(
            "app.agents.tools.core.retrieval.get_subagent_by_id",
            return_value=None,
        ):
            result = _inject_available_subagents(
                [], {"int1"}, {}, include_subagents=True
            )
        assert result == ["subagent:int1"]

    def test_connected_with_none_name_bare(self):
        from app.agents.tools.core.retrieval import _inject_available_subagents

        result = _inject_available_subagents([], set(), {"conn1": None}, include_subagents=True)
        assert result == ["subagent:conn1"]

    def test_dedupe_internal_against_discovered(self):
        from app.agents.tools.core.retrieval import _inject_available_subagents

        sa_internal = MagicMock()
        sa_internal.name = "Internal App"

        with patch(
            "app.agents.tools.core.retrieval.get_subagent_by_id",
            return_value=sa_internal,
        ):
            result = _inject_available_subagents(
                ["subagent:int1 (Internal App)"], {"int1"}, {}, include_subagents=True
            )
        assert result == ["subagent:int1 (Internal App)"]

    def test_dedupe_connected_against_discovered(self):
        from app.agents.tools.core.retrieval import _inject_available_subagents

        result = _inject_available_subagents(
            ["subagent:conn1"], set(), {"conn1": "Conn App"}, include_subagents=True
        )
        assert result == ["subagent:conn1 (Conn App)"]


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
    @contextmanager
    def _seams(
        self,
        registry: MagicMock | None = None,
        mcp_tools: list[str] | None = None,
    ) -> Iterator[dict[str, Any]]:
        with ExitStack() as stack:
            if registry is None:
                registry = _make_registry()
            stack.enter_context(
                patch(
                    "app.agents.tools.core.retrieval.get_tool_registry",
                    new_callable=AsyncMock,
                    return_value=registry,
                )
            )
            mcp_client = SimpleNamespace(
                _tools={
                    "mcp": [SimpleNamespace(name=t) for t in (mcp_tools or [])]
                }
            )
            mcp_accessor = AsyncMock(return_value=mcp_client)
            stack.enter_context(
                patch("app.agents.tools.core.retrieval.get_mcp_client", mcp_accessor)
            )
            log_mock = MagicMock()
            stack.enter_context(patch("app.agents.tools.core.retrieval.log", log_mock))
            yield {
                "registry": registry,
                "mcp_accessor": mcp_accessor,
                "log": log_mock,
            }

    @pytest.mark.asyncio
    async def test_returns_corrective_when_no_args(self):
        from app.agents.tools.core.retrieval import get_retrieve_tools_function

        fn = get_retrieve_tools_function()
        store = MagicMock()
        config: dict = {"configurable": {"user_id": "u1"}}

        with self._seams():
            result = await fn(store=store, config=config, exact_tool_names=[])

        assert result == {
            "tools_to_bind": [],
            "response": [
                (
                    "retrieve_tools received no usable argument (an empty "
                    "exact_tool_names counts as none). Next step: pass "
                    "query='what you want to do' to discover, or "
                    "exact_tool_names=['TOOL_NAME'] to bind a known tool. To use a "
                    "subagent (a 'subagent:' result), do NOT call retrieve_tools "
                    "again; call handoff(subagent_id='gmail', task='...') directly."
                )
            ],
        }

    @pytest.mark.asyncio
    async def test_binding_mode_validates_tools_exact(self):
        from app.agents.tools.core.retrieval import get_retrieve_tools_function

        fn = get_retrieve_tools_function(include_subagents=True)
        store = MagicMock()
        config: dict = {"configurable": {"user_id": "u1"}}

        with self._seams(_make_registry(["TOOL_A", "TOOL_B"])) as mocks:
            result = await fn(
                store=store,
                config=config,
                exact_tool_names=["TOOL_A", "TOOL_C"],
            )

        assert result == {"tools_to_bind": ["TOOL_A"], "response": ["TOOL_A"]}
        mocks["log"].set.assert_called_once_with(
            tool_retrieval={
                "mode": "binding",
                "tools_requested": 2,
                "tools_bound": 1,
                "tools_filtered": 1,
            }
        )

    @pytest.mark.asyncio
    async def test_binding_logs_unknown_names(self):
        from app.agents.tools.core.retrieval import get_retrieve_tools_function

        fn = get_retrieve_tools_function(include_subagents=True)
        store = MagicMock()
        config: dict = {"configurable": {"user_id": "u1"}}

        with self._seams(_make_registry(["TOOL_A"])) as mocks:
            result = await fn(
                store=store,
                config=config,
                exact_tool_names=["UNKNOWN"],
            )

        assert result == {"tools_to_bind": [], "response": []}
        warnings = [
            c
            for c in mocks["log"].warning.call_args_list
            if "dropped unknown tools" in c.args[0]
        ]
        assert len(warnings) == 1
        assert warnings[0].kwargs == {
            "tool_space": "general",
            "unknown": ["UNKNOWN"],
            "available_count": 1,
        }

    @pytest.mark.asyncio
    async def test_binding_binds_mcp_tool_not_in_registry(self):
        from app.agents.tools.core.retrieval import get_retrieve_tools_function

        fn = get_retrieve_tools_function(include_subagents=True)
        store = MagicMock()
        config: dict = {"configurable": {"user_id": "u1"}}

        with self._seams(_make_registry([]), mcp_tools=["MCP_TOOL_X"]) as mocks:
            result = await fn(
                store=store,
                config=config,
                exact_tool_names=["MCP_TOOL_X"],
            )

        assert result == {
            "tools_to_bind": ["MCP_TOOL_X"],
            "response": ["MCP_TOOL_X"],
        }
        mocks["mcp_accessor"].assert_called_once_with(user_id="u1")

    @pytest.mark.asyncio
    async def test_binding_resolves_canonical_hyphenated_names(self):
        from app.agents.tools.core.retrieval import get_retrieve_tools_function

        fn = get_retrieve_tools_function(include_subagents=True)
        store = MagicMock()
        config: dict = {"configurable": {"user_id": "u1"}}

        with self._seams(_make_registry([]), mcp_tools=["my-tool"]):
            result = await fn(
                store=store,
                config=config,
                exact_tool_names=["my_tool"],
            )

        assert result == {"tools_to_bind": ["my-tool"], "response": ["my-tool"]}

    @pytest.mark.asyncio
    async def test_binding_respects_bindable_tool_names_scope(self):
        from app.agents.tools.core.retrieval import get_retrieve_tools_function

        fn = get_retrieve_tools_function(
            include_subagents=True, bindable_tool_names={"SCOPED_A"}
        )
        store = MagicMock()
        config: dict = {"configurable": {"user_id": "u1"}}

        with self._seams(_make_registry(["GLOBAL_A", "SCOPED_A"])) as mocks:
            result = await fn(
                store=store,
                config=config,
                exact_tool_names=["GLOBAL_A", "SCOPED_A"],
            )

        assert result == {
            "tools_to_bind": ["SCOPED_A"],
            "response": [
                "SCOPED_A",
                (
                    "These tools are not available inside this subagent and cannot be "
                    "bound here: GLOBAL_A. They belong to the "
                    "main executor, not this subagent — do not retry binding them; finish "
                    "your task here and let the executor handle them."
                ),
            ],
        }
        mocks["log"].set.assert_called_once_with(
            tool_retrieval={
                "mode": "binding",
                "tools_requested": 2,
                "tools_bound": 1,
                "tools_filtered": 1,
            }
        )
        oos_warnings = [
            c
            for c in mocks["log"].warning.call_args_list
            if "rejected out-of-scope tools" in c.args[0]
        ]
        assert len(oos_warnings) == 1
        assert oos_warnings[0].kwargs == {
            "tool_space": "general",
            "out_of_scope": ["GLOBAL_A"],
        }

    @pytest.mark.asyncio
    async def test_binding_rejects_desktop_tools_outside_desktop_session(self):
        from app.agents.tools.core.retrieval import (
            DESKTOP_TOOL_CATEGORY,
            get_retrieve_tools_function,
        )

        fn = get_retrieve_tools_function(include_subagents=True)
        store = MagicMock()
        config: dict = {"configurable": {"user_id": "u1"}}

        with self._seams(
            _make_registry(["OPEN_DESKTOP_FILE"], category=DESKTOP_TOOL_CATEGORY)
        ):
            result = await fn(
                store=store,
                config=config,
                exact_tool_names=["OPEN_DESKTOP_FILE"],
            )

        assert result == {"tools_to_bind": [], "response": []}

    @pytest.mark.asyncio
    async def test_binding_allows_desktop_tools_in_desktop_session(self):
        from app.agents.tools.core.retrieval import (
            DESKTOP_TOOL_CATEGORY,
            get_retrieve_tools_function,
        )

        fn = get_retrieve_tools_function(include_subagents=True)
        store = MagicMock()
        config: dict = {
            "configurable": {"user_id": "u1", "conversation_source": "desktop"}
        }

        with self._seams(
            _make_registry(["OPEN_DESKTOP_FILE"], category=DESKTOP_TOOL_CATEGORY)
        ):
            result = await fn(
                store=store,
                config=config,
                exact_tool_names=["OPEN_DESKTOP_FILE"],
            )

        assert result == {
            "tools_to_bind": ["OPEN_DESKTOP_FILE"],
            "response": ["OPEN_DESKTOP_FILE"],
        }

    @pytest.mark.asyncio
    async def test_binding_desktop_tool_blocked_in_subagent_tool_space(self):
        from app.agents.tools.core.retrieval import (
            DESKTOP_TOOL_CATEGORY,
            get_retrieve_tools_function,
        )

        fn = get_retrieve_tools_function(
            tool_space="gmail", include_subagents=True
        )
        store = MagicMock()
        config: dict = {
            "configurable": {"user_id": "u1", "conversation_source": "desktop"}
        }

        with self._seams(
            _make_registry(["OPEN_DESKTOP_FILE"], category=DESKTOP_TOOL_CATEGORY)
        ):
            result = await fn(
                store=store,
                config=config,
                exact_tool_names=["OPEN_DESKTOP_FILE"],
            )

        assert result == {"tools_to_bind": [], "response": []}

    @pytest.mark.asyncio
    async def test_binding_returns_corrective_for_subagents(self):
        from app.agents.tools.core.retrieval import get_retrieve_tools_function

        fn = get_retrieve_tools_function(include_subagents=True)
        store = MagicMock()
        config: dict = {"configurable": {"user_id": "u1"}}

        with self._seams(_make_registry(["TOOL_A"])):
            result = await fn(
                store=store,
                config=config,
                exact_tool_names=["subagent:gmail"],
            )

        assert result == {
            "tools_to_bind": [],
            "response": [
                (
                    "Subagents are not bound with retrieve_tools. Call "
                    "handoff(subagent_id='<id>', task='...') directly, using the "
                    "part after 'subagent:'."
                )
            ],
        }

    @pytest.mark.asyncio
    async def test_binding_subagent_name_is_unknown_when_disabled(self):
        from app.agents.tools.core.retrieval import get_retrieve_tools_function

        fn = get_retrieve_tools_function(include_subagents=False)
        store = MagicMock()
        config: dict = {"configurable": {"user_id": "u1"}}

        with self._seams(_make_registry(["TOOL_A"])) as mocks:
            result = await fn(
                store=store,
                config=config,
                exact_tool_names=["subagent:gmail"],
            )

        assert result == {"tools_to_bind": [], "response": []}
        warnings = [
            c
            for c in mocks["log"].warning.call_args_list
            if "dropped unknown tools" in c.args[0]
        ]
        assert len(warnings) == 1
        assert warnings[0].kwargs["unknown"] == ["subagent:gmail"]

    @pytest.mark.asyncio
    async def test_binding_mixed_request_response_order(self):
        from app.agents.tools.core.retrieval import get_retrieve_tools_function

        fn = get_retrieve_tools_function(include_subagents=True)
        store = MagicMock()
        config: dict = {"configurable": {"user_id": "u1"}}

        with self._seams(_make_registry(["TOOL_A", "GLOBAL_OOS"])):
            result = await fn(
                store=store,
                config=config,
                exact_tool_names=["TOOL_A", "subagent:gmail", "GLOBAL_OOS"],
            )

        # Without a scoped bindable set, every registry tool binds; the
        # subagent name surfaces as guidance appended after the bound names.
        assert result == {
            "tools_to_bind": ["TOOL_A", "GLOBAL_OOS"],
            "response": [
                "TOOL_A",
                "GLOBAL_OOS",
                (
                    "Subagents are not bound with retrieve_tools. Call "
                    "handoff(subagent_id='<id>', task='...') directly, using the "
                    "part after 'subagent:'."
                ),
            ],
        }

    @pytest.mark.asyncio
    async def test_binding_without_user_id_skips_mcp_lookup(self):
        from app.agents.tools.core.retrieval import get_retrieve_tools_function

        fn = get_retrieve_tools_function(include_subagents=True)
        store = MagicMock()
        config: dict = {"configurable": {}}

        with self._seams(_make_registry(["TOOL_A"])) as mocks:
            result = await fn(
                store=store,
                config=config,
                exact_tool_names=["TOOL_A"],
            )

        assert result == {"tools_to_bind": ["TOOL_A"], "response": ["TOOL_A"]}
        mocks["mcp_accessor"].assert_not_called()
        assert any(
            "NO user_id" in c.args[0] for c in mocks["log"].warning.call_args_list
        )


class TestRetrieveToolsDiscovery:
    @staticmethod
    def _item(
        key: str,
        namespace: tuple[str, ...] = ("general",),
        score: float = 0.9,
        value: Any = None,
    ) -> SimpleNamespace:
        item = SimpleNamespace(key=key, namespace=namespace, score=score)
        if value is not None:
            item.value = value
        return item

    @contextmanager
    def _seams(
        self,
        *,
        registry_names: list[str] | None = None,
        category_of_tool: str | None = None,
        namespaces: list[str] | None = None,
        namespaces_error: Exception | None = None,
        mcp_tools: list[str] | None = None,
        asearch_results: list[Any] | None = None,
        public_results: list[dict[str, Any]] | None = None,
        subagents: tuple[Any, ...] = (),
        integration_status: dict[str, bool] | None = None,
        subagent_by_id: Any = None,
        user_integrations: Any = None,
    ) -> Iterator[dict[str, Any]]:
        with ExitStack() as stack:
            registry = _make_registry(registry_names, category_of_tool)
            stack.enter_context(
                patch(
                    "app.agents.tools.core.retrieval.get_tool_registry",
                    new_callable=AsyncMock,
                    return_value=registry,
                )
            )

            store = MagicMock()
            store.asearch = AsyncMock(side_effect=asearch_results or [[]])

            if namespaces_error is not None:
                namespaces_mock = AsyncMock(side_effect=namespaces_error)
            else:
                namespaces_mock = AsyncMock(return_value=namespaces or [])
            stack.enter_context(
                patch(
                    "app.agents.tools.core.retrieval.get_user_available_tool_namespaces",
                    namespaces_mock,
                )
            )

            mcp_client = SimpleNamespace(
                _tools={
                    "mcp": [SimpleNamespace(name=t) for t in (mcp_tools or [])]
                }
            )
            stack.enter_context(
                patch(
                    "app.agents.tools.core.retrieval.get_mcp_client",
                    new_callable=AsyncMock,
                    return_value=mcp_client,
                )
            )

            stack.enter_context(
                patch(
                    "app.agents.tools.core.retrieval.all_subagents",
                    return_value=subagents,
                )
            )
            status_mock = AsyncMock(return_value=integration_status or {})
            stack.enter_context(
                patch(
                    "app.agents.tools.core.retrieval.get_all_integrations_status",
                    status_mock,
                )
            )
            subagent_mock = MagicMock(
                side_effect=subagent_by_id if subagent_by_id is not None else (lambda _id: None)
            )
            stack.enter_context(
                patch("app.agents.tools.core.retrieval.get_subagent_by_id", subagent_mock)
            )
            user_ints_mock = AsyncMock(
                return_value=(
                    user_integrations
                    if user_integrations is not None
                    else SimpleNamespace(integrations=[])
                )
            )
            stack.enter_context(
                patch(
                    "app.agents.tools.core.retrieval.get_user_integrations",
                    user_ints_mock,
                )
            )
            public_mock = AsyncMock(return_value=public_results or [])
            stack.enter_context(
                patch(
                    "app.agents.tools.core.retrieval.search_public_integrations",
                    public_mock,
                )
            )
            log_mock = MagicMock()
            stack.enter_context(patch("app.agents.tools.core.retrieval.log", log_mock))

            yield {
                "store": store,
                "registry": registry,
                "namespaces": namespaces_mock,
                "status": status_mock,
                "subagent_by_id": subagent_mock,
                "user_integrations": user_ints_mock,
                "public": public_mock,
                "log": log_mock,
            }

    @pytest.mark.asyncio
    async def test_discovery_exact_searches_and_log_set(self):
        from app.agents.tools.core.retrieval import get_retrieve_tools_function

        fn = get_retrieve_tools_function(
            tool_space="gmail", include_subagents=False, limit=7
        )
        with self._seams(
            registry_names=["TOOL_A"],
            namespaces=["general", "gmail"],
            asearch_results=[
                [self._item("TOOL_A", ("gmail",), 0.9)],
                [],
            ],
        ) as mocks:
            result = await fn(
                store=mocks["store"],
                config={"configurable": {"user_id": "u1"}},
                query="find emails",
                exact_tool_names=[],
            )

        assert result == {"tools_to_bind": [], "response": ["TOOL_A"]}
        assert mocks["store"].asearch.call_args_list == [
            call(("gmail",), query="find emails", limit=7),
            call(("general",), query="find emails", limit=5),
        ]
        mocks["log"].set.assert_called_once_with(
            tool_retrieval={
                "mode": "discovery",
                "query": "find emails",
                "tool_space": "gmail",
                "user_id": "u1",
                "namespaces_searched": ["general", "gmail"],
                "tools_discovered": 1,
                "chroma_hits": 1,
                "public_hits": 0,
                "per_namespace_hits": {"gmail": 1},
                "candidates_after_filter": 1,
                "chroma_preview": ["('gmail',)::TOOL_A"],
            }
        )

    @pytest.mark.asyncio
    async def test_discovery_returns_empty_when_no_hits(self):
        from app.agents.tools.core.retrieval import get_retrieve_tools_function

        fn = get_retrieve_tools_function(include_subagents=False)
        with self._seams(
            registry_names=["TOOL_A"],
            namespaces=["general"],
            asearch_results=[[]],
        ) as mocks:
            result = await fn(
                store=mocks["store"],
                config={"configurable": {"user_id": "u1"}},
                query="find emails",
                exact_tool_names=[],
            )

        assert result == {"tools_to_bind": [], "response": []}

    @pytest.mark.asyncio
    async def test_discovery_public_and_subagent_results(self):
        from app.agents.tools.core.retrieval import get_retrieve_tools_function

        fn = get_retrieve_tools_function(include_subagents=True)
        with self._seams(
            namespaces=["general"],
            asearch_results=[
                [],
                [self._item("gmail", ("subagents",), 0.5, value={"name": "Gmail"})],
            ],
            public_results=[
                {"integration_id": "abc", "name": "ABC", "relevance_score": 0.8}
            ],
        ) as mocks:
            result = await fn(
                store=mocks["store"],
                config={"configurable": {"user_id": "u1"}},
                query="find emails",
                exact_tool_names=[],
            )

        # Sorted by score desc: public hit 0.8 first, chroma subagent 0.5 second.
        assert result == {
            "tools_to_bind": [],
            "response": [
                "subagent:abc (ABC)",
                "subagent:gmail (Gmail)",
            ],
        }
        mocks["public"].assert_called_once_with(query="find emails", limit=15)

    @pytest.mark.asyncio
    async def test_discovery_all_tasks_fail_raises(self):
        from app.agents.tools.core.retrieval import get_retrieve_tools_function

        fn = get_retrieve_tools_function(include_subagents=False)
        with self._seams(
            registry_names=["TOOL_A"],
            namespaces=["general"],
            asearch_results=[RuntimeError("search boom")],
        ) as mocks:
            with pytest.raises(RuntimeError, match="search boom"):
                await fn(
                    store=mocks["store"],
                    config={"configurable": {"user_id": "u1"}},
                    query="find emails",
                    exact_tool_names=[],
                )

        errors = [
            c
            for c in mocks["log"].error.call_args_list
            if "search task failed" in c.args[0]
        ]
        assert len(errors) == 1
        assert errors[0].kwargs == {
            "error": "search boom",
            "error_type": "RuntimeError",
        }

    @pytest.mark.asyncio
    async def test_discovery_partial_failure_degrades(self):
        from app.agents.tools.core.retrieval import get_retrieve_tools_function

        fn = get_retrieve_tools_function(
            tool_space="gmail", include_subagents=False
        )
        with self._seams(
            registry_names=["TOOL_A"],
            namespaces=["general", "gmail"],
            asearch_results=[RuntimeError("boom"), []],
        ) as mocks:
            result = await fn(
                store=mocks["store"],
                config={"configurable": {"user_id": "u1"}},
                query="find emails",
                exact_tool_names=[],
            )

        # One of two searches failed; the surviving search still answers.
        assert result == {"tools_to_bind": [], "response": []}
        assert any(
            "search task failed" in c.args[0] for c in mocks["log"].error.call_args_list
        )

    @pytest.mark.asyncio
    async def test_discovery_includes_mcp_tool_names(self):
        from app.agents.tools.core.retrieval import get_retrieve_tools_function

        fn = get_retrieve_tools_function(include_subagents=False)
        with self._seams(
            registry_names=[],
            mcp_tools=["MCP_X"],
            namespaces=["general"],
            asearch_results=[[self._item("MCP_X", ("general",), 0.7)]],
        ) as mocks:
            result = await fn(
                store=mocks["store"],
                config={"configurable": {"user_id": "u1"}},
                query="find emails",
                exact_tool_names=[],
            )

        assert result == {"tools_to_bind": [], "response": ["MCP_X"]}

    @pytest.mark.asyncio
    async def test_discovery_injects_available_subagents(self):
        from app.agents.tools.core.retrieval import get_retrieve_tools_function

        fn = get_retrieve_tools_function(include_subagents=True)
        sa_int1 = _make_subagent_mock("int1", "internal", name="Internal One")
        with self._seams(
            namespaces=["general"],
            asearch_results=[[], []],
            subagents=(sa_int1,),
            integration_status={"conn1": True},
            subagent_by_id={"conn1": None, "int1": sa_int1}.__getitem__,
            user_integrations=SimpleNamespace(
                integrations=[
                    SimpleNamespace(
                        integration_id="conn1",
                        integration=SimpleNamespace(name="Conn One"),
                    )
                ]
            ),
        ) as mocks:
            result = await fn(
                store=mocks["store"],
                config={"configurable": {"user_id": "u1"}},
                query="find emails",
                exact_tool_names=[],
            )

        assert result == {
            "tools_to_bind": [],
            "response": [
                "subagent:int1 (Internal One)",
                "subagent:conn1 (Conn One)",
            ],
        }

    @pytest.mark.asyncio
    async def test_discovery_desktop_session_searches_desktop_namespace(self):
        from app.agents.tools.core.retrieval import (
            DESKTOP_TOOL_SPACE,
            get_retrieve_tools_function,
        )

        fn = get_retrieve_tools_function(include_subagents=False)
        with self._seams(
            registry_names=["TOOL_A"],
            namespaces=["general"],
            asearch_results=[[], []],
        ) as mocks:
            result = await fn(
                store=mocks["store"],
                config={
                    "configurable": {
                        "user_id": "u1",
                        "conversation_source": "desktop",
                    }
                },
                query="find emails",
                exact_tool_names=[],
            )

        assert result["tools_to_bind"] == []
        assert mocks["store"].asearch.call_args_list == [
            call(("general",), query="find emails", limit=25),
            call((DESKTOP_TOOL_SPACE,), query="find emails", limit=10),
        ]

    @pytest.mark.asyncio
    async def test_discovery_no_desktop_search_for_subagent_tool_space(self):
        from app.agents.tools.core.retrieval import get_retrieve_tools_function

        fn = get_retrieve_tools_function(
            tool_space="gmail", include_subagents=False
        )
        with self._seams(
            registry_names=["TOOL_A"],
            namespaces=["general", "gmail"],
            asearch_results=[[], []],
        ) as mocks:
            await fn(
                store=mocks["store"],
                config={
                    "configurable": {
                        "user_id": "u1",
                        "conversation_source": "desktop",
                    }
                },
                query="find emails",
                exact_tool_names=[],
            )

        assert mocks["store"].asearch.call_args_list == [
            call(("gmail",), query="find emails", limit=25),
            call(("general",), query="find emails", limit=5),
        ]

    @pytest.mark.asyncio
    async def test_discovery_warns_zero_chroma_hits_for_subagent_space(self):
        from app.agents.tools.core.retrieval import get_retrieve_tools_function

        fn = get_retrieve_tools_function(
            tool_space="gmail", include_subagents=False
        )
        with self._seams(
            namespaces=["general", "gmail"],
            asearch_results=[[], []],
        ) as mocks:
            await fn(
                store=mocks["store"],
                config={"configurable": {"user_id": "u1"}},
                query="find emails",
                exact_tool_names=[],
            )

        assert any(
            "0 ChromaDB hits" in c.args[0]
            for c in mocks["log"].warning.call_args_list
        )

    @pytest.mark.asyncio
    async def test_discovery_no_zero_warning_for_general_space(self):
        from app.agents.tools.core.retrieval import get_retrieve_tools_function

        fn = get_retrieve_tools_function(include_subagents=False)
        with self._seams(
            namespaces=["general"],
            asearch_results=[[]],
        ) as mocks:
            await fn(
                store=mocks["store"],
                config={"configurable": {"user_id": "u1"}},
                query="find emails",
                exact_tool_names=[],
            )

        assert not any(
            "0 ChromaDB hits" in c.args[0]
            for c in mocks["log"].warning.call_args_list
        )

    @pytest.mark.asyncio
    async def test_discovery_metadata_fallback_writes_back_to_configurable(self):
        from app.agents.tools.core.retrieval import get_retrieve_tools_function

        fn = get_retrieve_tools_function(include_subagents=False)
        config: dict = {"configurable": {}, "metadata": {"user_id": "from_metadata"}}
        with self._seams(
            registry_names=["TOOL_A"],
            namespaces=["general"],
            asearch_results=[[]],
        ) as mocks:
            await fn(
                store=mocks["store"],
                config=config,
                query="find emails",
                exact_tool_names=[],
            )

        mocks["namespaces"].assert_called_once_with("from_metadata")
        assert config["configurable"]["user_id"] == "from_metadata"

    @pytest.mark.asyncio
    async def test_discovery_tolerates_namespace_lookup_failure(self):
        from app.agents.tools.core.retrieval import get_retrieve_tools_function

        fn = get_retrieve_tools_function(include_subagents=False)
        with self._seams(
            registry_names=["TOOL_A"],
            namespaces_error=RuntimeError("db down"),
            asearch_results=[[]],
        ) as mocks:
            result = await fn(
                store=mocks["store"],
                config={"configurable": {"user_id": "u1"}},
                query="find emails",
                exact_tool_names=[],
            )

        # Falls back to the general namespace only; discovery still answers.
        assert result == {"tools_to_bind": [], "response": []}
        assert mocks["store"].asearch.call_args_list == [
            call(("general",), query="find emails", limit=25),
        ]
