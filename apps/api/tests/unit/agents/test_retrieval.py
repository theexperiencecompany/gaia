"""Hermetic unit tests for app.agents.tools.core.retrieval.

Every external seam (tool registry, MCP client, integration status, user
integrations, public-integration store, subagent registry, log) is mocked at
the module boundary; assertions pin exact return values, exact search-task
shapes, exact guidance strings, and exact log-call arguments.
"""

import asyncio
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.tools.core import retrieval
from app.agents.tools.core.retrieval import (
    _RETRIEVE_TOOLS_BASE_DOC,
    _RETRIEVE_TOOLS_SUBAGENT_SECTION,
    _build_search_tasks,
    _deduplicate_and_sort,
    _get_user_context,
    _inject_available_subagents,
    _is_platform_tool_space,
    _process_chroma_search_result,
    _process_public_integration_result,
    _process_search_results,
    _resolve_connected_subagents,
    _user_mcp_tool_names,
    get_retrieve_tools_function,
)
from app.constants.log_tags import LogTag

NO_ARG_GUIDANCE = (
    "retrieve_tools received no usable argument (an empty "
    "exact_tool_names counts as none). Next step: pass "
    "query='what you want to do' to discover, or "
    "exact_tool_names=['TOOL_NAME'] to bind a known tool. To use a "
    "subagent (a 'subagent:' result), do NOT call retrieve_tools "
    "again; call handoff(subagent_id='gmail', task='...') directly."
)

SUBAGENT_GUIDANCE = (
    "Subagents are not bound with retrieve_tools. Call "
    "handoff(subagent_id='<id>', task='...') directly, using the "
    "part after 'subagent:'."
)

OUT_OF_SCOPE_GUIDANCE = (
    "These tools are not available inside this subagent and cannot be "
    "bound here: {tools}. They belong to the "
    "main executor, not this subagent — do not retry binding them; finish "
    "your task here and let the executor handle them."
)


@pytest.fixture(autouse=True)
def _fake_log():
    """Route every module log call into a MagicMock so exact args are assertable."""
    with patch.object(retrieval, "log") as fake_log:
        yield fake_log


def _item(key: str, score: float, namespace: tuple[str, ...] | None, value: dict | None = None):
    """Build a chroma SearchItem-shaped object."""
    kwargs: dict = {"key": key, "score": score}
    if namespace is not None:
        kwargs["namespace"] = namespace
    if value is not None:
        kwargs["value"] = value
    return SimpleNamespace(**kwargs)


class _FakeRegistry:
    """Registry behavior needed by retrieval.py — category map is injectable."""

    def __init__(
        self,
        tool_names: list[str],
        categories: dict[str, str] | None = None,
        delegated_categories: set[str] | None = None,
    ) -> None:
        self._names = list(tool_names)
        self._categories = categories or {}
        self._delegated = delegated_categories or set()

    def get_tool_names(self) -> list[str]:
        return list(self._names)

    def get_category_of_tool(self, tool_name: str) -> str | None:
        return self._categories.get(tool_name)

    def get_category(self, name: str) -> SimpleNamespace | None:
        if name in self._categories.values() or name in self._delegated:
            return SimpleNamespace(is_delegated=name in self._delegated)
        return None


class _FakeStore:
    """Minimal async store: returns preset results per namespace, records calls.

    The default limit is a sentinel (999) so a caller that DROPS the limit
    kwarg is distinguishable from one that passes the real default.
    """

    def __init__(self, data: dict[tuple[str, ...], list[object]]) -> None:
        self._data = data
        self.calls: list[tuple[tuple[str, ...], str, int]] = []

    async def asearch(
        self, namespace: tuple[str, ...], query: str = "", limit: int = 999
    ) -> list[object]:
        self.calls.append((namespace, query, limit))
        return self._data.get(namespace, [])


class _FailingStore:
    """Store that raises for configured namespaces and returns [] otherwise."""

    def __init__(self, fail: set[tuple[str, ...]]) -> None:
        self._fail = fail
        self.calls: list[tuple[tuple[str, ...], str, int]] = []

    async def asearch(
        self, namespace: tuple[str, ...], query: str = "", limit: int = 999
    ) -> list[object]:
        self.calls.append((namespace, query, limit))
        if namespace in self._fail:
            raise RuntimeError(f"search failed for {namespace}")
        return []


class _BrokenItem:
    """Chroma-shaped item whose score access blows up (preview-log failure path)."""

    @property
    def key(self) -> str:
        return "broken_tool"

    @property
    def namespace(self) -> tuple[str, ...]:
        return ("general",)

    @property
    def score(self) -> float:
        raise AttributeError("no score")


async def _run_retrieve(
    *,
    tool_space: str = "general",
    include_subagents: bool = True,
    limit: int = 25,
    bindable_tool_names: set[str] | None = None,
    use_defaults: bool = False,
    store: object = None,
    config: dict | None = None,
    query: str | None = None,
    exact_tool_names: list[str] | None = None,
    registry: _FakeRegistry | None = None,
    mcp_tool_names: set[str] | None = None,
    user_context: tuple[set[str], dict[str, str | None], set[str]] | None = None,
    patch_user_context: bool = True,
    user_mcp_mock: AsyncMock | None = None,
    user_context_mock: AsyncMock | None = None,
    subagent_by_id: dict[str, SimpleNamespace] | None = None,
    public_integrations: list[dict] | None = None,
    process_results_mock: AsyncMock | None = None,
) -> dict:
    """Build a retrieve_tools function with all seams patched and invoke it."""
    if use_defaults:
        retrieve_tools = get_retrieve_tools_function()
    else:
        retrieve_tools = get_retrieve_tools_function(
            tool_space=tool_space,
            include_subagents=include_subagents,
            limit=limit,
            bindable_tool_names=bindable_tool_names,
        )
    store = store if store is not None else _FakeStore({})
    config = config if config is not None else {"configurable": {"user_id": "u1"}}
    mcp_mock = user_mcp_mock if user_mcp_mock is not None else AsyncMock(return_value=mcp_tool_names or set())
    ctx_mock = user_context_mock if user_context_mock is not None else AsyncMock(
        return_value=user_context if user_context is not None else ({"general"}, {}, set())
    )
    patches = [
        patch.object(
            retrieval,
            "get_tool_registry",
            new=AsyncMock(return_value=registry if registry is not None else _FakeRegistry([])),
        ),
        patch.object(retrieval, "_user_mcp_tool_names", new=mcp_mock),
        patch.object(
            retrieval,
            "get_subagent_by_id",
            side_effect=lambda sid: subagent_by_id.get(sid) if subagent_by_id else None,
        ),
    ]
    if patch_user_context:
        patches.append(patch.object(retrieval, "_get_user_context", new=ctx_mock))
    if include_subagents:
        patches.append(
            patch.object(
                retrieval,
                "search_public_integrations",
                new=AsyncMock(return_value=public_integrations or []),
            )
        )
    if process_results_mock is not None:
        patches.append(
            patch.object(retrieval, "_process_search_results", new=process_results_mock)
        )
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        return await retrieve_tools(
            store=store,
            config=config,
            query=query,
            exact_tool_names=exact_tool_names if exact_tool_names is not None else [],
        )


# ---------------------------------------------------------------------------
# _user_mcp_tool_names
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_user_mcp_tool_names_no_user_id_returns_empty_without_mcp_call(_fake_log):
    with patch.object(retrieval, "get_mcp_client", new=AsyncMock()) as get_mcp_client:
        result = await _user_mcp_tool_names(None)
    assert result == set()
    get_mcp_client.assert_not_awaited()
    _fake_log.warning.assert_not_called()


@pytest.mark.asyncio
async def test_user_mcp_tool_names_collects_names_across_connectors():
    client = SimpleNamespace(
        _tools={
            "mcp_a": [SimpleNamespace(name="A_TOOL"), SimpleNamespace(name="B_TOOL")],
            "mcp_b": [SimpleNamespace(name="C_TOOL")],
            "mcp_c": [],
        }
    )
    with patch.object(
        retrieval, "get_mcp_client", new=AsyncMock(return_value=client)
    ) as get_mcp_client:
        result = await _user_mcp_tool_names("u1")
    assert result == {"A_TOOL", "B_TOOL", "C_TOOL"}
    get_mcp_client.assert_awaited_once_with(user_id="u1")


@pytest.mark.asyncio
async def test_user_mcp_tool_names_returns_empty_on_failure_and_logs_exact(_fake_log):
    with patch.object(
        retrieval, "get_mcp_client", new=AsyncMock(side_effect=RuntimeError("boom"))
    ):
        result = await _user_mcp_tool_names("u1")
    assert result == set()
    _fake_log.warning.assert_called_once_with(
        f"{LogTag.TOOL} _user_mcp_tool_names failed",
        user_id="u1",
        error_type="RuntimeError",
    )


# ---------------------------------------------------------------------------
# _is_platform_tool_space
# ---------------------------------------------------------------------------


def _oauth_integration(tool_space: str | None, available: bool = True):
    subagent_config = SimpleNamespace(tool_space=tool_space) if tool_space else None
    return SimpleNamespace(available=available, subagent_config=subagent_config)


def test_is_platform_tool_space_true_when_any_available_integration_matches():
    integrations = [
        _oauth_integration("gmail"),
        _oauth_integration("github"),
        _oauth_integration(None),
    ]
    with patch.object(retrieval, "OAUTH_INTEGRATIONS", integrations):
        assert _is_platform_tool_space("github") is True
        assert _is_platform_tool_space("gmail") is True


def test_is_platform_tool_space_false_for_unavailable_or_unconfigured():
    integrations = [
        _oauth_integration("gmail", available=False),
        _oauth_integration(None, available=True),
    ]
    with patch.object(retrieval, "OAUTH_INTEGRATIONS", integrations):
        assert _is_platform_tool_space("gmail") is False
        assert _is_platform_tool_space("github") is False


def test_is_platform_tool_space_false_for_custom_mcp_namespace():
    integrations = [_oauth_integration("github")]
    with patch.object(retrieval, "OAUTH_INTEGRATIONS", integrations):
        assert _is_platform_tool_space("https://my-mcp.example.com") is False


# ---------------------------------------------------------------------------
# _resolve_connected_subagents
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_connected_subagents_maps_platform_and_custom():
    status = {"gmail": True, "mcp1": True, "todos": False}
    subagent_by_id = {"gmail": SimpleNamespace(id="gmail", name="Gmail")}
    user_ints = SimpleNamespace(
        integrations=[
            SimpleNamespace(
                integration_id="mcp1", integration=SimpleNamespace(name="My MCP")
            )
        ]
    )
    with (
        patch.object(retrieval, "get_all_integrations_status", new=AsyncMock(return_value=status)) as status_mock,
        patch.object(
            retrieval, "get_subagent_by_id", side_effect=lambda sid: subagent_by_id.get(sid)
        ),
        patch.object(retrieval, "get_user_integrations", new=AsyncMock(return_value=user_ints)) as user_ints_mock,
    ):
        result = await _resolve_connected_subagents("u1")
    assert result == {"gmail": "Gmail", "mcp1": "My MCP"}
    status_mock.assert_awaited_once_with("u1")
    user_ints_mock.assert_awaited_once_with("u1")


@pytest.mark.asyncio
async def test_resolve_connected_subagents_custom_without_name_is_none():
    status = {"mcp1": True}
    user_ints = SimpleNamespace(
        integrations=[SimpleNamespace(integration_id="other", integration=SimpleNamespace(name="X"))]
    )
    with (
        patch.object(retrieval, "get_all_integrations_status", new=AsyncMock(return_value=status)),
        patch.object(retrieval, "get_subagent_by_id", return_value=None),
        patch.object(retrieval, "get_user_integrations", new=AsyncMock(return_value=user_ints)),
    ):
        result = await _resolve_connected_subagents("u1")
    assert result == {"mcp1": None}


@pytest.mark.asyncio
async def test_resolve_connected_subagents_skips_user_integrations_when_no_custom():
    status = {"gmail": True, "todos": False}
    subagent_by_id = {"gmail": SimpleNamespace(id="gmail", name="Gmail")}
    with (
        patch.object(retrieval, "get_all_integrations_status", new=AsyncMock(return_value=status)),
        patch.object(
            retrieval, "get_subagent_by_id", side_effect=lambda sid: subagent_by_id.get(sid)
        ),
        patch.object(retrieval, "get_user_integrations", new=AsyncMock()) as get_user_integrations,
    ):
        result = await _resolve_connected_subagents("u1")
    assert result == {"gmail": "Gmail"}
    get_user_integrations.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolve_connected_subagents_skips_disconnected_before_connected():
    # A disconnected entry BEFORE a connected one: `continue` must skip it and
    # keep scanning (a `break` here would drop every later connected id).
    status = {"todos": False, "gmail": True}
    with (
        patch.object(retrieval, "get_all_integrations_status", new=AsyncMock(return_value=status)),
        patch.object(
            retrieval,
            "get_subagent_by_id",
            return_value=SimpleNamespace(id="gmail", name="Gmail"),
        ),
        patch.object(retrieval, "get_user_integrations", new=AsyncMock()),
    ):
        result = await _resolve_connected_subagents("u1")
    assert result == {"gmail": "Gmail"}


@pytest.mark.asyncio
async def test_resolve_connected_subagents_no_connected_returns_empty():
    with (
        patch.object(
            retrieval, "get_all_integrations_status", new=AsyncMock(return_value={"gmail": False})
        ),
        patch.object(retrieval, "get_subagent_by_id", return_value=None),
        patch.object(retrieval, "get_user_integrations", new=AsyncMock()),
    ):
        result = await _resolve_connected_subagents("u1")
    assert result == {}


# ---------------------------------------------------------------------------
# _get_user_context
# ---------------------------------------------------------------------------


def _make_patches(user_context_patches: dict):
    base = {
        "_is_platform_tool_space": patch.object(
            retrieval, "_is_platform_tool_space", return_value=False
        ),
        "all_subagents": patch.object(
            retrieval,
            "all_subagents",
            return_value=[
                SimpleNamespace(id="gmail", managed_by="mcp"),
                SimpleNamespace(id="todos", managed_by="internal"),
                SimpleNamespace(id="skills", managed_by="internal"),
            ],
        ),
        "get_user_available_tool_namespaces": patch.object(
            retrieval,
            "get_user_available_tool_namespaces",
            new=AsyncMock(return_value=set()),
        ),
        "_resolve_connected_subagents": patch.object(
            retrieval,
            "_resolve_connected_subagents",
            new=AsyncMock(return_value={}),
        ),
    }
    base.update(user_context_patches)
    return base


@pytest.mark.asyncio
async def test_get_user_context_no_user_id_seeds_general_and_internal_subagents(_fake_log):
    patches = _make_patches({})
    with (
        patches["_is_platform_tool_space"],
        patches["all_subagents"] as all_subagents,
        patches["get_user_available_tool_namespaces"] as namespaces,
        patches["_resolve_connected_subagents"] as resolve,
    ):
        user_namespaces, connected, internal = await _get_user_context(None, "general")
    assert user_namespaces == {"general"}
    assert connected == {}
    assert internal == {"todos", "skills"}
    all_subagents.assert_called_once()
    namespaces.assert_not_awaited()
    resolve.assert_not_awaited()
    _fake_log.info.assert_not_called()
    _fake_log.warning.assert_not_called()


@pytest.mark.asyncio
async def test_get_user_context_include_subagents_false_skips_all_subagent_work(_fake_log):
    patches = _make_patches({})
    with (
        patches["_is_platform_tool_space"],
        patches["all_subagents"] as all_subagents,
        patches["get_user_available_tool_namespaces"] as namespaces,
        patches["_resolve_connected_subagents"] as resolve,
    ):
        user_namespaces, connected, internal = await _get_user_context(
            "u1", "general", include_subagents=False
        )
    assert user_namespaces == {"general"}
    assert connected == {}
    assert internal == set()
    all_subagents.assert_not_called()
    resolve.assert_not_awaited()
    namespaces.assert_awaited_once_with("u1")
    _fake_log.info.assert_called_once_with(
        f"{LogTag.TOOL} User namespaces resolved", user_id="u1", namespaces={"general"}
    )


@pytest.mark.asyncio
async def test_get_user_context_platform_tool_space_seeded_and_union_with_cache(_fake_log):
    patches = _make_patches(
        {
            "_is_platform_tool_space": patch.object(
                retrieval, "_is_platform_tool_space", return_value=True
            ),
            "get_user_available_tool_namespaces": patch.object(
                retrieval, "get_user_available_tool_namespaces", new=AsyncMock(return_value={"custom"})
            ),
        }
    )
    with (
        patches["_is_platform_tool_space"] as is_platform,
        patches["all_subagents"],
        patches["get_user_available_tool_namespaces"],
        patches["_resolve_connected_subagents"] as resolve,
    ):
        user_namespaces, connected, internal = await _get_user_context("u1", "github")
    # Platform seed survives the cache union.
    assert user_namespaces == {"general", "github", "custom"}
    assert internal == {"todos", "skills"}
    resolve.assert_awaited_once_with("u1")
    is_platform.assert_called_once_with("github")
    _fake_log.info.assert_any_call(
        f"{LogTag.TOOL} User connected subagents", user_id="u1", connected_integrations=[]
    )
    _fake_log.info.assert_any_call(
        f"{LogTag.TOOL} User namespaces resolved",
        user_id="u1",
        namespaces={"general", "github", "custom"},
    )


@pytest.mark.asyncio
async def test_get_user_context_include_subagents_resolves_connected(_fake_log):
    patches = _make_patches(
        {
            "_resolve_connected_subagents": patch.object(
                retrieval,
                "_resolve_connected_subagents",
                new=AsyncMock(return_value={"gmail": "Gmail"}),
            )
        }
    )
    with (
        patches["_is_platform_tool_space"],
        patches["all_subagents"],
        patches["get_user_available_tool_namespaces"],
        patches["_resolve_connected_subagents"] as resolve,
    ):
        user_namespaces, connected, internal = await _get_user_context("u1", "general")
    assert connected == {"gmail": "Gmail"}
    assert user_namespaces == {"general"}
    assert internal == {"todos", "skills"}
    resolve.assert_awaited_once_with("u1")
    _fake_log.info.assert_any_call(
        f"{LogTag.TOOL} User connected subagents", user_id="u1", connected_integrations=["gmail"]
    )


@pytest.mark.asyncio
async def test_get_user_context_namespace_failure_keeps_seed_and_returns(_fake_log):
    patches = _make_patches(
        {
            "get_user_available_tool_namespaces": patch.object(
                retrieval,
                "get_user_available_tool_namespaces",
                new=AsyncMock(side_effect=RuntimeError("cache down")),
            )
        }
    )
    with (
        patches["_is_platform_tool_space"],
        patches["all_subagents"],
        patches["get_user_available_tool_namespaces"],
        patches["_resolve_connected_subagents"] as resolve,
    ):
        user_namespaces, connected, internal = await _get_user_context("u1", "general")
    assert user_namespaces == {"general"}
    assert connected == {}
    assert internal == {"todos", "skills"}
    resolve.assert_not_awaited()
    _fake_log.warning.assert_called_once_with(
        f"{LogTag.TOOL} Failed to get user namespaces", error_type="RuntimeError"
    )
    _fake_log.info.assert_not_called()


# ---------------------------------------------------------------------------
# _build_search_tasks
# ---------------------------------------------------------------------------


async def _drain_tasks(tasks: list) -> None:
    """Await the asearch coroutines so no un-awaited-coroutine warnings leak."""
    await asyncio.gather(*tasks)


@pytest.mark.asyncio
async def test_build_search_tasks_general_only(_fake_log):
    store = _FakeStore({})
    tasks = _build_search_tasks(
        store, "q", "general", {"general"}, include_subagents=False, limit=25
    )
    await _drain_tasks(tasks)
    assert store.calls == [(("general",), "q", 25)]
    _fake_log.info.assert_any_call(
        f"{LogTag.TOOL} Adding search for tool space", tool_space="general"
    )


@pytest.mark.asyncio
async def test_build_search_tasks_general_tool_space_searched_even_outside_namespaces(_fake_log):
    # The `or tool_space == "general"` escape hatch: general must be searched
    # even when the caller's namespaces (which always seed "general") are absent
    # in a synthetic context — a string mutation here would refuse the search.
    store = _FakeStore({})
    tasks = _build_search_tasks(
        store, "q", "general", {"other"}, include_subagents=False, limit=25
    )
    await _drain_tasks(tasks)
    assert store.calls == [(("general",), "q", 25)]


@pytest.mark.asyncio
async def test_build_search_tasks_refuses_foreign_tool_space(_fake_log):
    store = _FakeStore({})
    tasks = _build_search_tasks(
        store, "q", "other_space", {"general"}, include_subagents=False, limit=25
    )
    await _drain_tasks(tasks)
    # The foreign namespace must never be searched; general still is (limit 5).
    assert store.calls == [(("general",), "q", 5)]
    _fake_log.warning.assert_called_once_with(
        f"{LogTag.TOOL} retrieve_tools refused search: tool_space not in user_namespaces",
        tool_space="other_space",
        user_namespaces=["general"],
    )


@pytest.mark.asyncio
async def test_build_search_tasks_searches_owned_tool_space_plus_general(_fake_log):
    store = _FakeStore({})
    tasks = _build_search_tasks(
        store, "q", "github", {"general", "github"}, include_subagents=False, limit=25
    )
    await _drain_tasks(tasks)
    assert store.calls == [(("github",), "q", 25), (("general",), "q", 5)]
    _fake_log.info.assert_any_call(
        f"{LogTag.TOOL} Adding search for tool space", tool_space="github"
    )
    _fake_log.info.assert_any_call(
        f"{LogTag.TOOL} Adding search for general namespace (limited to 5 for core tools)"
    )


@pytest.mark.asyncio
async def test_build_search_tasks_subagents_and_desktop_namespaces(_fake_log):
    store = _FakeStore({})
    with patch.object(
        retrieval, "search_public_integrations", new=AsyncMock(return_value=[])
    ) as search_public:
        tasks = _build_search_tasks(
            store,
            "q",
            "general",
            {"general"},
            include_subagents=True,
            limit=25,
            include_desktop=True,
        )
        await _drain_tasks(tasks)
    assert store.calls == [
        (("general",), "q", 25),
        (("desktop",), "q", 10),
        (("subagents",), "q", 15),
    ]
    search_public.assert_awaited_once_with(query="q", limit=15)
    _fake_log.info.assert_any_call(f"{LogTag.TOOL} Adding search for desktop namespace")
    _fake_log.info.assert_any_call(f"{LogTag.TOOL} Adding search for subagents namespace")


# ---------------------------------------------------------------------------
# _process_public_integration_result
# ---------------------------------------------------------------------------


def test_process_public_integration_result_renders_named_and_unnamed():
    result = [
        {"integration_id": "pub1", "name": "Pub MCP", "relevance_score": 0.7},
        {"integration_id": "pub2"},
    ]
    assert _process_public_integration_result(result) == [
        {"id": "subagent:pub1 (Pub MCP)", "score": 0.7},
        {"id": "subagent:pub2", "score": 0},
    ]


def test_process_public_integration_result_drops_missing_id_and_empty():
    assert _process_public_integration_result([{"name": "No id", "relevance_score": 0.9}]) == []
    assert _process_public_integration_result([]) == []


def test_process_public_integration_result_preserves_order():
    result = [
        {"integration_id": "a", "relevance_score": 0.1},
        {"integration_id": "b", "name": "B", "relevance_score": 0.9},
    ]
    assert _process_public_integration_result(result) == [
        {"id": "subagent:a", "score": 0.1},
        {"id": "subagent:b (B)", "score": 0.9},
    ]


# ---------------------------------------------------------------------------
# _process_chroma_search_result
# ---------------------------------------------------------------------------


def test_process_chroma_subagents_namespace_with_names():
    result = [
        _item("gmail", 1.0, ("subagents",), {"name": "Gmail"}),
        _item("fb9dfd7e05f8", 0.9, ("subagents",), {}),
        _item("subagent:abc", 0.8, ("subagents",), {"name": "ABC"}),
    ]
    processed = _process_chroma_search_result(
        result, {"gmail", "fb9dfd7e05f8"}, _FakeRegistry([]), include_subagents=True
    )
    assert processed == [
        {"id": "subagent:gmail (Gmail)", "score": 1.0},
        {"id": "subagent:fb9dfd7e05f8", "score": 0.9},
        {"id": "subagent:abc (ABC)", "score": 0.8},
    ]


def test_process_chroma_subagents_namespace_skipped_when_disabled():
    result = [
        _item("gmail", 1.0, ("subagents",), {"name": "Gmail"}),
        _item("t1", 0.5, ("general",)),
    ]
    processed = _process_chroma_search_result(
        result, {"t1"}, _FakeRegistry([]), include_subagents=False
    )
    # Skipping must not abort the loop: the regular item still passes through.
    assert processed == [{"id": "t1", "score": 0.5}]


def test_process_chroma_subagents_item_without_value_dict():
    # No `value` attr at all: name stays unset, no AttributeError on the guard.
    result = [_item("gmail", 1.0, ("subagents",))]
    processed = _process_chroma_search_result(
        result, set(), _FakeRegistry([]), include_subagents=True
    )
    assert processed == [{"id": "subagent:gmail", "score": 1.0}]


def test_process_chroma_subagent_prefix_key_outside_subagents_namespace():
    result = [
        _item("subagent:xyz", 0.7, ("general",)),
        _item("t1", 0.5, ("general",)),
    ]
    included = _process_chroma_search_result(
        result, {"t1"}, _FakeRegistry([]), include_subagents=True
    )
    assert included == [
        {"id": "subagent:xyz", "score": 0.7},
        {"id": "t1", "score": 0.5},
    ]
    excluded = _process_chroma_search_result(
        result, {"t1"}, _FakeRegistry([]), include_subagents=False
    )
    assert excluded == [{"id": "t1", "score": 0.5}]


def test_process_chroma_general_namespace_filtered_for_subagent_context():
    webpage_tools = retrieval.WEBPAGE_TOOLS
    result = [
        _item("random_general_tool", 0.8, ("general",)),
        _item(webpage_tools[0], 0.9, ("general",)),
    ]
    processed = _process_chroma_search_result(
        result,
        set(webpage_tools) | {"random_general_tool"},
        _FakeRegistry([]),
        include_subagents=False,
        tool_space="provider_space",
    )
    assert [hit["id"] for hit in processed] == [webpage_tools[0]]


def test_process_chroma_general_namespace_not_filtered_for_main_agent():
    result = [_item("random_general_tool", 0.8, ("general",))]
    processed = _process_chroma_search_result(
        result, {"random_general_tool"}, _FakeRegistry([]), include_subagents=False
    )
    assert processed == [{"id": "random_general_tool", "score": 0.8}]


def test_process_chroma_filters_delegated_tools_in_main_context():
    registry = _FakeRegistry(
        ["normal_tool", "delegated_tool"],
        categories={"delegated_tool": "delegated_cat"},
        delegated_categories={"delegated_cat"},
    )
    result = [
        _item("delegated_tool", 0.95, ("general",)),
        _item("normal_tool", 0.9, ("general",)),
    ]
    processed = _process_chroma_search_result(
        result, {"normal_tool", "delegated_tool"}, registry, include_subagents=True
    )
    # Filtering must not abort the loop: the regular tool still passes through.
    assert [hit["id"] for hit in processed] == ["normal_tool"]


def test_process_chroma_keeps_non_delegated_tools_in_main_context():
    registry = _FakeRegistry(["normal_tool"], categories={"normal_tool": "general_cat"})
    result = [_item("normal_tool", 0.9, ("general",))]
    processed = _process_chroma_search_result(
        result, {"normal_tool"}, registry, include_subagents=True
    )
    assert processed == [{"id": "normal_tool", "score": 0.9}]


def test_process_chroma_drops_tools_not_in_available_names():
    result = [_item("stray_tool", 0.99, ("general",))]
    processed = _process_chroma_search_result(
        result, {"normal_tool"}, _FakeRegistry([]), include_subagents=False
    )
    assert processed == []


def test_process_chroma_item_without_namespace_still_processed():
    result = [_item("bare_tool", 0.6, None)]
    processed = _process_chroma_search_result(
        result, {"bare_tool"}, _FakeRegistry([]), include_subagents=False
    )
    assert processed == [{"id": "bare_tool", "score": 0.6}]


# ---------------------------------------------------------------------------
# _process_search_results
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_search_results_skips_errors_and_empty_and_mixes_sources(_fake_log):
    results: list = [
        RuntimeError("boom"),
        [],
        [{"integration_id": "p1", "name": "P", "relevance_score": 0.3}],
        [
            _item("subagent:gmail", 1.0, ("subagents",), {"name": "Gmail"}),
            _item("t1", 0.9, ("general",)),
        ],
    ]
    processed = await _process_search_results(
        results, {"t1"}, _FakeRegistry([]), include_subagents=False, tool_space="provider_space"
    )
    # Subagent hit is skipped (include_subagents=False) and the general-namespace
    # hit is filtered to webpage tools only inside a subagent tool space.
    assert processed == [{"id": "subagent:p1 (P)", "score": 0.3}]
    _fake_log.debug.assert_any_call(
        f"{LogTag.TOOL} Chroma search raw hits",
        task_index=3,
        tool_space="provider_space",
        hit_count=2,
        preview=[
            {"key": "subagent:gmail", "namespace": ("subagents",), "score": 1.0},
            {"key": "t1", "namespace": ("general",), "score": 0.9},
        ],
    )


@pytest.mark.asyncio
async def test_process_search_results_preview_capped_at_twenty_items(_fake_log):
    results: list = [[_item(f"t{i}", float(i), ("general",)) for i in range(21)]]
    processed = await _process_search_results(
        results, {f"t{i}" for i in range(21)}, _FakeRegistry([]), include_subagents=False
    )
    assert len(processed) == 21
    call_args = _fake_log.debug.call_args
    assert call_args.kwargs["hit_count"] == 21
    assert len(call_args.kwargs["preview"]) == 20


@pytest.mark.asyncio
async def test_process_search_results_preview_failure_logs_and_crashes_loudly(_fake_log):
    # A malformed item (score access raises) hits the preview log's except path,
    # then the same item fails the real processing — the error must propagate.
    with pytest.raises(AttributeError, match="no score"):
        await _process_search_results(
            [[_BrokenItem()]], {"broken_tool"}, _FakeRegistry([]), include_subagents=False
        )
    _fake_log.debug.assert_called_once_with(
        f"{LogTag.TOOL} Chroma search raw hits log failed",
        task_index=0,
        error_type="AttributeError",
    )


@pytest.mark.asyncio
async def test_process_search_results_public_result_without_required_keys():
    results: list = [[{"integration_id": "p1"}]]
    processed = await _process_search_results(
        results, set(), _FakeRegistry([]), include_subagents=False
    )
    assert processed == [{"id": "subagent:p1", "score": 0}]


# ---------------------------------------------------------------------------
# _deduplicate_and_sort
# ---------------------------------------------------------------------------


def test_deduplicate_and_sort_keeps_first_occurrence_and_sorts_desc():
    results = [
        {"id": "a", "score": 0.1},
        {"id": "b", "score": 0.9},
        {"id": "a", "score": 0.95},
    ]
    assert _deduplicate_and_sort(results, limit=10) == ["b", "a"]


def test_deduplicate_and_sort_treats_none_score_as_zero():
    results = [
        {"id": "x", "score": None},
        {"id": "y", "score": 0.1},
    ]
    assert _deduplicate_and_sort(results, limit=10) == ["y", "x"]


def test_deduplicate_and_sort_applies_limit():
    results = [{"id": f"t{i}", "score": float(i)} for i in range(5)]
    assert _deduplicate_and_sort(results, limit=2) == ["t4", "t3"]
    assert _deduplicate_and_sort(results, limit=0) == []


def test_deduplicate_and_sort_empty():
    assert _deduplicate_and_sort([], limit=10) == []


# ---------------------------------------------------------------------------
# _inject_available_subagents
# ---------------------------------------------------------------------------


def test_inject_available_subagents_passthrough_when_disabled():
    discovered = ["normal_tool", "subagent:gmail (Gmail)"]
    result = _inject_available_subagents(discovered, set(), {}, include_subagents=False)
    assert result == discovered
    assert result is discovered


def test_inject_available_subagents_upgrades_unnamed_hit_with_connected_name():
    discovered = ["subagent:mcp1", "normal_tool"]
    result = _inject_available_subagents(
        discovered, set(), {"mcp1": "My MCP"}, include_subagents=True
    )
    assert result == ["subagent:mcp1 (My MCP)", "normal_tool"]


def test_inject_available_subagents_falls_back_to_registry_name():
    discovered = ["subagent:gmail"]
    with patch.object(
        retrieval, "get_subagent_by_id", return_value=SimpleNamespace(id="gmail", name="Gmail")
    ) as get_subagent_by_id:
        result = _inject_available_subagents(
            discovered, set(), {}, include_subagents=True
        )
    assert result == ["subagent:gmail (Gmail)"]
    get_subagent_by_id.assert_called_once_with("gmail")


def test_inject_available_subagents_keeps_unnamed_when_no_name_resolvable():
    discovered = ["subagent:gmail"]
    with patch.object(retrieval, "get_subagent_by_id", return_value=None):
        result = _inject_available_subagents(discovered, set(), {}, include_subagents=True)
    assert result == ["subagent:gmail"]


def test_inject_available_subagents_keeps_already_named_entries():
    discovered = ["subagent:gmail (Gmail)"]
    # Even when a connected integration knows a (different) name, the named hit wins.
    result = _inject_available_subagents(
        discovered, set(), {"gmail": "Other Name"}, include_subagents=True
    )
    assert result == ["subagent:gmail (Gmail)"]


def test_inject_available_subagents_dedupes_by_canonical_id():
    discovered = ["subagent:mcp1", "subagent:mcp1 (My MCP)"]
    result = _inject_available_subagents(
        discovered, set(), {"mcp1": "My MCP"}, include_subagents=True
    )
    assert result == ["subagent:mcp1 (My MCP)"]


def test_inject_available_subagents_dedup_skip_must_continue_scanning():
    # Skipping a duplicate canonical id must CONTINUE to later entries (a
    # `break` here would drop every entry after the duplicate). "other" must
    # NOT be recoverable from the connected-integrations pass — a `break`
    # would otherwise be masked by pass 2 re-adding the dropped entry.
    discovered = ["subagent:mcp1", "subagent:mcp1 (My MCP)", "subagent:other"]
    with patch.object(retrieval, "get_subagent_by_id", return_value=None):
        result = _inject_available_subagents(
            discovered, set(), {"mcp1": "My MCP"}, include_subagents=True
        )
    assert result == ["subagent:mcp1 (My MCP)", "subagent:other"]


def test_inject_available_subagents_non_subagent_entry_first_keeps_later_ones():
    # A non-subagent entry must be kept and iteration must CONTINUE to later
    # subagent entries (a `break` here would drop everything after it).
    discovered = ["normal_tool", "subagent:mcp1"]
    result = _inject_available_subagents(
        discovered, set(), {"mcp1": "My MCP"}, include_subagents=True
    )
    assert result == ["normal_tool", "subagent:mcp1 (My MCP)"]


def test_inject_available_subagents_canonical_id_split_on_whitespace_tab():
    # `split(" ", 1)` on a tab-separated tail must keep the whole tail as the
    # canonical id; splitting on any-whitespace would truncate at the tab and
    # wrongly dedupe distinct entries.
    discovered = ["subagent:mcp1\t(My MCP)", "subagent:mcp1 (My MCP)"]
    result = _inject_available_subagents(
        discovered, set(), {"mcp1": "My MCP"}, include_subagents=True
    )
    assert result == ["subagent:mcp1\t(My MCP)", "subagent:mcp1 (My MCP)"]


def test_inject_available_subagents_empty_connected_name_falls_back_to_registry():
    with patch.object(
        retrieval, "get_subagent_by_id", return_value=SimpleNamespace(id="gmail", name="Gmail")
    ):
        result = _inject_available_subagents(
            ["subagent:gmail"], set(), {"gmail": ""}, include_subagents=True
        )
    assert result == ["subagent:gmail (Gmail)"]


def test_inject_available_subagents_adds_internal_subagents_with_registry_names():
    discovered: list[str] = []
    with patch.object(
        retrieval,
        "get_subagent_by_id",
        side_effect=lambda sid: (
            SimpleNamespace(id=sid, name="Todos") if sid == "todos" else None
        ),
    ) as get_subagent_by_id:
        result = _inject_available_subagents(
            discovered, {"todos", "skills"}, {}, include_subagents=True
        )
    assert sorted(result) == ["subagent:skills", "subagent:todos (Todos)"]
    get_subagent_by_id.assert_any_call("todos")
    get_subagent_by_id.assert_any_call("skills")


def test_inject_available_subagents_adds_connected_integrations_at_end():
    discovered = ["normal_tool"]
    result = _inject_available_subagents(
        discovered, set(), {"gmail": "Gmail", "mcp1": None}, include_subagents=True
    )
    assert result == ["normal_tool", "subagent:gmail (Gmail)", "subagent:mcp1"]


def test_inject_available_subagents_does_not_repeat_internal_already_discovered():
    discovered = ["subagent:todos (Todos)"]
    result = _inject_available_subagents(discovered, {"todos"}, {}, include_subagents=True)
    assert result == ["subagent:todos (Todos)"]


def test_inject_available_subagents_overlapping_internal_and_connected_added_once():
    # The same id supplied by both internal_subagents and connected_integrations
    # must be appended exactly once (the seen-set guard, not just pass-1 dedup).
    with patch.object(
        retrieval, "get_subagent_by_id", return_value=SimpleNamespace(id="gmail", name="Gmail")
    ):
        result = _inject_available_subagents(
            [], {"gmail"}, {"gmail": "Gmail"}, include_subagents=True
        )
    assert result == ["subagent:gmail (Gmail)"]


# ---------------------------------------------------------------------------
# get_retrieve_tools_function — docstring & no-arg contract
# ---------------------------------------------------------------------------


def test_retrieve_tools_docstring_depends_on_include_subagents():
    with_subagents = get_retrieve_tools_function(include_subagents=True)
    without_subagents = get_retrieve_tools_function(include_subagents=False)
    assert with_subagents.__doc__ == _RETRIEVE_TOOLS_BASE_DOC + _RETRIEVE_TOOLS_SUBAGENT_SECTION
    assert without_subagents.__doc__ == _RETRIEVE_TOOLS_BASE_DOC
    assert _RETRIEVE_TOOLS_SUBAGENT_SECTION not in without_subagents.__doc__


@pytest.mark.asyncio
async def test_retrieve_tools_no_usable_argument_returns_corrective_guidance():
    result = await _run_retrieve(query=None, exact_tool_names=[])
    assert result == {"tools_to_bind": [], "response": [NO_ARG_GUIDANCE]}


# ---------------------------------------------------------------------------
# get_retrieve_tools_function — factory defaults & entry logging
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retrieve_tools_factory_defaults_flow_through():
    # get_retrieve_tools_function() with no args must default to
    # tool_space="general", include_subagents=True, limit=25.
    store = _FakeStore({})
    result = await _run_retrieve(
        use_defaults=True,
        store=store,
        query="q",
        user_context=({"general"}, {}, set()),
        public_integrations=[],
    )
    assert store.calls == [(("general",), "q", 25), (("subagents",), "q", 15)]
    assert result["tools_to_bind"] == []


@pytest.mark.asyncio
async def test_retrieve_tools_entry_log_pins_all_args(_fake_log):
    # user_id falls back to metadata; every entry-log kwarg is pinned exactly.
    result = await _run_retrieve(
        registry=_FakeRegistry(["TOOL_A"]),
        exact_tool_names=["TOOL_A"],
        config={"configurable": {}, "metadata": {"user_id": "u9"}},
    )
    assert result["tools_to_bind"] == ["TOOL_A"]
    _fake_log.info.assert_any_call(
        f"{LogTag.TOOL} retrieve_tools called",
        query=None,
        exact_tool_names=["TOOL_A"],
        tool_space="general",
        include_subagents=True,
        user_id="u9",
    )
    _fake_log.info.assert_any_call(
        f"{LogTag.TOOL} Registry available tools", available_tool_count=1
    )


@pytest.mark.asyncio
async def test_retrieve_tools_user_id_prefers_configurable(_fake_log):
    user_context_mock = AsyncMock(return_value=({"general"}, {}, set()))
    await _run_retrieve(
        registry=_FakeRegistry(["TOOL_A"]),
        store=_FakeStore({("general",): [_item("TOOL_A", 0.9, ("general",))]}),
        query="q",
        include_subagents=False,
        user_context_mock=user_context_mock,
        config={"configurable": {"user_id": "u1"}},
    )
    user_context_mock.assert_awaited_once_with("u1", "general", False)
    _fake_log.warning.assert_not_called()
    # Entry log must carry the configurable user_id (no metadata fallback to
    # mask read-path mutations) and the actual query.
    _fake_log.info.assert_any_call(
        f"{LogTag.TOOL} retrieve_tools called",
        query="q",
        exact_tool_names=[],
        tool_space="general",
        include_subagents=False,
        user_id="u1",
    )


@pytest.mark.asyncio
async def test_retrieve_tools_no_user_id_logs_warning(_fake_log):
    await _run_retrieve(
        registry=_FakeRegistry(["TOOL_A"]),
        exact_tool_names=["TOOL_A"],
        config={"configurable": {}},
    )
    _fake_log.warning.assert_any_call(
        f"{LogTag.TOOL} retrieve_tools called with NO user_id (not in configurable or metadata)"
    )


@pytest.mark.asyncio
async def test_retrieve_tools_metadata_user_id_without_configurable_key(_fake_log):
    # config has NO "configurable" key: the user_id back-fill must be skipped,
    # not attempted (that would KeyError).
    result = await _run_retrieve(
        registry=_FakeRegistry(["TOOL_A"]),
        store=_FakeStore({("general",): [_item("TOOL_A", 0.9, ("general",))]}),
        query="q",
        include_subagents=False,
        user_context=({"general"}, {}, set()),
        config={"metadata": {"user_id": "u9"}},
    )
    assert result["response"] == ["TOOL_A"]


# ---------------------------------------------------------------------------
# get_retrieve_tools_function — binding mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retrieve_tools_binding_validates_and_drops_unknown(_fake_log):
    registry = _FakeRegistry(["TOOL_A", "TOOL_B"])
    result = await _run_retrieve(
        registry=registry,
        exact_tool_names=["TOOL_A", "TOOL_B", "NOPE"],
    )
    assert result["tools_to_bind"] == ["TOOL_A", "TOOL_B"]
    assert result["response"] == ["TOOL_A", "TOOL_B"]
    _fake_log.warning.assert_any_call(
        f"{LogTag.TOOL} retrieve_tools binding dropped unknown tools",
        tool_space="general",
        unknown=["NOPE"],
        available_count=2,
    )


@pytest.mark.asyncio
async def test_retrieve_tools_binding_respects_bindable_scope_and_reports_out_of_scope(_fake_log):
    registry = _FakeRegistry(["TOOL_A", "GLOBAL_ONLY"])
    result = await _run_retrieve(
        registry=registry,
        bindable_tool_names={"TOOL_A"},
        exact_tool_names=["TOOL_A", "GLOBAL_ONLY", "NOPE"],
    )
    assert result["tools_to_bind"] == ["TOOL_A"]
    assert result["response"] == [
        "TOOL_A",
        OUT_OF_SCOPE_GUIDANCE.format(tools="GLOBAL_ONLY"),
    ]
    _fake_log.warning.assert_any_call(
        "retrieve_tools binding rejected out-of-scope tools",
        tool_space="general",
        out_of_scope=["GLOBAL_ONLY"],
    )


@pytest.mark.asyncio
async def test_retrieve_tools_binding_out_of_scope_join_and_logset_exact(_fake_log):
    # TWO out-of-scope tools: the response guidance joins them with ", " and
    # log.set records exact binding counters.
    registry = _FakeRegistry(["TOOL_A", "G1", "G2"])
    result = await _run_retrieve(
        registry=registry,
        bindable_tool_names={"TOOL_A"},
        exact_tool_names=["TOOL_A", "G1", "G2", "NOPE"],
    )
    assert result["tools_to_bind"] == ["TOOL_A"]
    assert result["response"] == [
        "TOOL_A",
        OUT_OF_SCOPE_GUIDANCE.format(tools="G1, G2"),
    ]
    _fake_log.warning.assert_any_call(
        "retrieve_tools binding rejected out-of-scope tools",
        tool_space="general",
        out_of_scope=["G1", "G2"],
    )
    _fake_log.set.assert_called_once_with(
        tool_retrieval={
            "mode": "binding",
            "tools_requested": 4,
            "tools_bound": 1,
            "tools_filtered": 3,
        }
    )


@pytest.mark.asyncio
async def test_retrieve_tools_binding_without_bindable_set_validates_globally():
    registry = _FakeRegistry(["TOOL_A", "GLOBAL_ONLY"])
    result = await _run_retrieve(
        registry=registry, bindable_tool_names=None, exact_tool_names=["GLOBAL_ONLY"]
    )
    assert result["tools_to_bind"] == ["GLOBAL_ONLY"]
    assert result["response"] == ["GLOBAL_ONLY"]


@pytest.mark.asyncio
async def test_retrieve_tools_binding_subagent_request_adds_handoff_guidance():
    registry = _FakeRegistry(["TOOL_A"])
    result = await _run_retrieve(
        registry=registry,
        include_subagents=True,
        exact_tool_names=["subagent:gmail", "TOOL_A"],
    )
    assert result["tools_to_bind"] == ["TOOL_A"]
    assert result["response"] == ["TOOL_A", SUBAGENT_GUIDANCE]


@pytest.mark.asyncio
async def test_retrieve_tools_binding_subagent_is_unknown_when_disabled(_fake_log):
    registry = _FakeRegistry(["TOOL_A"])
    result = await _run_retrieve(
        registry=registry,
        include_subagents=False,
        exact_tool_names=["subagent:gmail"],
    )
    assert result["tools_to_bind"] == []
    assert result["response"] == []
    _fake_log.warning.assert_any_call(
        f"{LogTag.TOOL} retrieve_tools binding dropped unknown tools",
        tool_space="general",
        unknown=["subagent:gmail"],
        available_count=1,
    )


@pytest.mark.asyncio
async def test_retrieve_tools_binding_binds_mcp_tool_names():
    user_mcp_mock = AsyncMock(return_value={"NOTION_QUERY"})
    registry = _FakeRegistry(["TOOL_A"])
    result = await _run_retrieve(
        registry=registry,
        user_mcp_mock=user_mcp_mock,
        exact_tool_names=["NOTION_QUERY"],
    )
    assert result["tools_to_bind"] == ["NOTION_QUERY"]
    user_mcp_mock.assert_awaited_once_with("u1")


@pytest.mark.asyncio
async def test_retrieve_tools_binding_recovers_canonical_hyphenated_names():
    registry = _FakeRegistry(["MY-TOOL"])
    result = await _run_retrieve(
        registry=registry,
        bindable_tool_names={"MY-TOOL"},
        exact_tool_names=["MY_TOOL", "MY-TOOL"],
    )
    assert result["tools_to_bind"] == ["MY-TOOL", "MY-TOOL"]


@pytest.mark.asyncio
async def test_retrieve_tools_binding_canonical_lookup_from_underscore_request():
    # "A-B" is not in the bindable set, but its underscore-canonical form
    # resolves via canonical_tool_name_map -> "A_B".
    registry = _FakeRegistry(["A_B"])
    result = await _run_retrieve(
        registry=registry,
        bindable_tool_names={"A_B"},
        exact_tool_names=["A-B"],
    )
    assert result["tools_to_bind"] == ["A_B"]
    assert result["response"] == ["A_B"]


@pytest.mark.asyncio
async def test_retrieve_tools_binding_colliding_underscore_hyphen_names():
    # bindable contains BOTH "A_B" and "A-B": a strict `and` membership check
    # would route both requests through the canonical map and collapse them
    # onto one name; the `or` check keeps each requested form verbatim.
    registry = _FakeRegistry(["A_B", "A-B"])
    result = await _run_retrieve(
        registry=registry,
        bindable_tool_names={"A_B", "A-B"},
        exact_tool_names=["A_B", "A-B"],
    )
    assert result["tools_to_bind"] == ["A_B", "A-B"]
    assert result["response"] == ["A_B", "A-B"]


@pytest.mark.asyncio
async def test_retrieve_tools_binding_desktop_tool_rejected_outside_desktop_session(_fake_log):
    registry = _FakeRegistry(
        ["DESKTOP_READ"], categories={"DESKTOP_READ": retrieval.DESKTOP_TOOL_CATEGORY}
    )
    result = await _run_retrieve(
        registry=registry,
        bindable_tool_names={"DESKTOP_READ"},
        exact_tool_names=["DESKTOP_READ"],
        config={"configurable": {"user_id": "u1", "conversation_source": "web"}},
    )
    assert result["tools_to_bind"] == []
    assert result["response"] == []
    _fake_log.warning.assert_any_call(
        f"{LogTag.TOOL} retrieve_tools binding dropped unknown tools",
        tool_space="general",
        unknown=["DESKTOP_READ"],
        available_count=1,
    )


@pytest.mark.asyncio
async def test_retrieve_tools_binding_desktop_tool_bound_in_desktop_session():
    registry = _FakeRegistry(
        ["DESKTOP_READ"], categories={"DESKTOP_READ": retrieval.DESKTOP_TOOL_CATEGORY}
    )
    result = await _run_retrieve(
        registry=registry,
        bindable_tool_names={"DESKTOP_READ"},
        exact_tool_names=["DESKTOP_READ"],
        config={
            "configurable": {
                "user_id": "u1",
                "conversation_source": "desktop",
            }
        },
    )
    assert result["tools_to_bind"] == ["DESKTOP_READ"]
    assert result["response"] == ["DESKTOP_READ"]


@pytest.mark.asyncio
async def test_retrieve_tools_binding_without_user_id_still_binds_registry_tools():
    result = await _run_retrieve(
        registry=_FakeRegistry(["TOOL_A"]),
        exact_tool_names=["TOOL_A"],
        config={"configurable": {}},
    )
    assert result["tools_to_bind"] == ["TOOL_A"]
    assert result["response"] == ["TOOL_A"]


# ---------------------------------------------------------------------------
# get_retrieve_tools_function — discovery mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retrieve_tools_discovery_end_to_end_ordering_and_injection(_fake_log):
    registry = _FakeRegistry(
        ["normal_tool", "delegated_tool", "web_search_tool"],
        categories={"delegated_tool": "delegated_cat"},
        delegated_categories={"delegated_cat"},
    )
    store = _FakeStore(
        {
            ("general",): [
                _item("normal_tool", 0.8, ("general",)),
                _item("delegated_tool", 0.9, ("general",)),
                _item("web_search_tool", 0.6, ("general",)),
            ],
            ("subagents",): [_item("gmail", 1.0, ("subagents",), {"name": "Gmail"})],
        }
    )
    result = await _run_retrieve(
        registry=registry,
        store=store,
        query="find tools",
        user_context=({"general", "subagents"}, {"gmail": "Gmail"}, {"todos"}),
        subagent_by_id={"todos": SimpleNamespace(id="todos", name="Todos")},
        public_integrations=[{"integration_id": "pub1", "name": "Pub", "relevance_score": 0.5}],
    )
    assert result == {
        "tools_to_bind": [],
        "response": [
            "subagent:gmail (Gmail)",
            "normal_tool",
            "web_search_tool",
            "subagent:pub1 (Pub)",
            "subagent:todos (Todos)",
        ],
    }
    _fake_log.set.assert_called_once_with(
        tool_retrieval={
            "mode": "discovery",
            "query": "find tools",
            "tool_space": "general",
            "user_id": "u1",
            "namespaces_searched": ["general", "subagents"],
            "tools_discovered": 5,
            "chroma_hits": 4,
            "public_hits": 1,
            "per_namespace_hits": {"general": 3, "subagents": 1},
            "candidates_after_filter": 4,
            "chroma_preview": [
                "('general',)::normal_tool",
                "('general',)::delegated_tool",
                "('general',)::web_search_tool",
                "('subagents',)::gmail",
            ],
        }
    )


@pytest.mark.asyncio
async def test_retrieve_tools_discovery_counters_and_preview_kitchen_sink(_fake_log):
    # Result shapes: [empty tool-space result, 13-item subagents result, 2
    # public dicts]. Pins every counter/preview computation exactly:
    # - empty first result must be skipped, not abort the loop
    # - per-namespace hit tallies (default ns for empty tuple, None ns skipped)
    # - preview capped at 10 entries, None keys skipped
    # - public dicts never leak into chroma_preview
    store = _FakeStore(
        {
            ("github",): [
                _item("key0", 0.0, None),
                _item(None, 1.0, ("github",)),
                _item("key2", 2.0, ()),
                # A multi-element namespace: the per-namespace tally joins it
                # with "::" (single-element tuples hide the separator).
                _item("key3", 3.0, ("general", "sub")),
                *[_item(f"key{i}", float(i), ("github",)) for i in range(4, 13)],
                _item("sa1", 1.5, ("subagents",), {"name": "SA"}),
            ],
            # A dict-shaped store result is treated as a public-integration
            # hit, so TWO public results reach the counters (+= vs = and
            # continue vs break on the public branch become observable).
            ("subagents",): [{"integration_id": "gen1", "name": "Gen", "relevance_score": 0.3}],
        }
    )
    result = await _run_retrieve(
        registry=_FakeRegistry(["key0", *[f"key{i}" for i in range(2, 13)]]),
        store=store,
        query="q",
        tool_space="github",
        user_context=({"general", "github"}, {}, set()),
        public_integrations=[
            {"integration_id": "p1", "name": "Pub", "relevance_score": 0.9, "key": "PKEY1"},
            {"integration_id": "p2", "name": "Pub2", "relevance_score": 0.8, "key": "PKEY2"},
        ],
    )
    assert result["response"] == [
        "key12",
        "key11",
        "key10",
        "key9",
        "key8",
        "key7",
        "key6",
        "key5",
        "key4",
        "key3",
        "key2",
        "subagent:sa1 (SA)",
        "subagent:p1 (Pub)",
        "subagent:p2 (Pub2)",
        "subagent:gen1 (Gen)",
        "key0",
    ]
    _fake_log.set.assert_called_once_with(
        tool_retrieval={
            "mode": "discovery",
            "query": "q",
            "tool_space": "github",
            "user_id": "u1",
            "namespaces_searched": ["general", "github"],
            "tools_discovered": 16,
            "chroma_hits": 14,
            "public_hits": 3,
            "per_namespace_hits": {
                "github": 10,
                "default": 1,
                "general::sub": 1,
                "subagents": 1,
            },
            "candidates_after_filter": 16,
            "chroma_preview": [
                "None::key0",
                "()::key2",
                "('general', 'sub')::key3",
                "('github',)::key4",
                "('github',)::key5",
                "('github',)::key6",
                "('github',)::key7",
                "('github',)::key8",
                "('github',)::key9",
                "('github',)::key10",
            ],
        }
    )


@pytest.mark.asyncio
async def test_retrieve_tools_discovery_preview_handles_dict_items_in_chroma_result(_fake_log):
    # A dict item inside a chroma-shaped result takes the item.get() preview
    # branch: namespace/tool_key must be read from the dict keys, and an item
    # without a "key" must be skipped. _process_search_results is stubbed
    # because a dict inside a chroma list would crash the real processor —
    # the preview is computed before that, and this test pins exactly that
    # preview (mutating the dict-key reads changes the logged preview).
    store = _FakeStore(
        {
            ("general",): [
                _item("t1", 0.9, ("general",)),
                {"namespace": "ns1", "key": "k1"},
                {"namespace": "ns2"},
            ],
        }
    )
    await _run_retrieve(
        registry=_FakeRegistry([]),
        store=store,
        query="q",
        include_subagents=False,
        user_context=({"general"}, {}, set()),
        process_results_mock=AsyncMock(return_value=[]),
    )
    tool_retrieval = _fake_log.set.call_args.kwargs["tool_retrieval"]
    assert tool_retrieval["chroma_preview"] == ["('general',)::t1", "ns1::k1"]


@pytest.mark.asyncio
async def test_retrieve_tools_discovery_preview_outer_break_stops_at_ten_across_results(_fake_log):
    # The OUTER `if len(chroma_preview) >= 10: break` must fire when the inner
    # per-result cap already stopped at 10: a second chroma result is waiting,
    # so a `>` / `11` mutation of the outer check would let an 11th entry
    # through and must be caught by the exact preview assertion.
    registry = _FakeRegistry([f"g{i}" for i in range(10)] + ["extra_general"])
    store = _FakeStore(
        {
            ("github",): [_item(f"g{i}", float(10 - i), ("github",)) for i in range(10)],
            ("general",): [_item("extra_general", 0.5, ("general",))],
        }
    )
    result = await _run_retrieve(
        registry=registry,
        store=store,
        query="q",
        tool_space="github",
        include_subagents=False,
        user_context=(
            {"general", "github"},
            {},
            set(),
        ),
    )
    assert result["response"] == [f"g{i}" for i in range(10)]
    tool_retrieval = _fake_log.set.call_args.kwargs["tool_retrieval"]
    assert tool_retrieval["chroma_preview"] == [f"('github',)::g{i}" for i in range(10)]


@pytest.mark.asyncio
async def test_retrieve_tools_discovery_mcp_names_kept_and_stray_dropped(_fake_log):
    user_mcp_mock = AsyncMock(return_value={"mcp_only"})
    registry = _FakeRegistry(["normal_tool"])
    store = _FakeStore(
        {
            ("general",): [
                _item("mcp_only", 0.9, ("general",)),
                _item("stray_tool", 0.8, ("general",)),
                _item("normal_tool", 0.5, ("general",)),
            ]
        }
    )
    result = await _run_retrieve(
        registry=registry,
        store=store,
        query="q",
        user_mcp_mock=user_mcp_mock,
        user_context=({"general"}, {}, set()),
    )
    assert result["response"] == ["mcp_only", "normal_tool"]
    user_mcp_mock.assert_awaited_once_with("u1")


@pytest.mark.asyncio
async def test_retrieve_tools_discovery_respects_limit():
    registry = _FakeRegistry([f"tool_{i}" for i in range(5)])
    store = _FakeStore(
        {("general",): [_item(f"tool_{i}", float(i), ("general",)) for i in range(5)]}
    )
    result = await _run_retrieve(
        registry=registry,
        store=store,
        query="q",
        limit=2,
        user_context=({"general"}, {}, set()),
    )
    assert result["response"] == ["tool_4", "tool_3"]


@pytest.mark.asyncio
async def test_retrieve_tools_discovery_queries_subagents_namespace_when_enabled():
    registry = _FakeRegistry([])
    store = _FakeStore({})
    await _run_retrieve(
        registry=registry,
        store=store,
        query="q",
        user_context=({"general"}, {}, set()),
        public_integrations=[],
    )
    assert (("subagents",), "q", 15) in store.calls
    assert (("general",), "q", 25) in store.calls


@pytest.mark.asyncio
async def test_retrieve_tools_discovery_skips_subagents_namespace_when_disabled():
    registry = _FakeRegistry([])
    store = _FakeStore({})
    await _run_retrieve(
        registry=registry,
        store=store,
        query="q",
        include_subagents=False,
        user_context=({"general"}, {}, set()),
    )
    assert (("general",), "q", 25) in store.calls
    assert all(ns != ("subagents",) for ns, _q, _l in store.calls)


@pytest.mark.asyncio
async def test_retrieve_tools_discovery_refuses_foreign_tool_space_search():
    registry = _FakeRegistry([])
    store = _FakeStore({})
    await _run_retrieve(
        registry=registry,
        store=store,
        query="q",
        tool_space="custom_mcp",
        include_subagents=False,
        user_context=({"general"}, {}, set()),
    )
    assert all(ns != ("custom_mcp",) for ns, _q, _l in store.calls)
    assert (("general",), "q", 5) in store.calls


@pytest.mark.asyncio
async def test_retrieve_tools_discovery_subagent_items_excluded_when_disabled_in_subagent_space():
    # Inside a subagent tool space with include_subagents=False, subagents
    # namespace hits must be excluded (the flag must reach the processor).
    # "random_general_tool" IS in the registry (so it is available to bind),
    # but the general-namespace filter must drop it here: the tool_space
    # argument must reach _process_search_results — a dropped argument would
    # default it to "general" and let the non-webpage tool through.
    registry = _FakeRegistry(["ptool", "web_search_tool", "random_general_tool"])
    store = _FakeStore(
        {
            ("provider_space",): [
                _item("subagent:x", 0.9, ("subagents",), {"name": "X"}),
                _item("ptool", 0.8, ("provider_space",)),
            ],
            ("general",): [
                _item("web_search_tool", 0.7, ("general",)),
                # Not a webpage tool: only keepable because the general
                # namespace filter knows this is a subagent tool space.
                _item("random_general_tool", 0.6, ("general",)),
            ],
        }
    )
    result = await _run_retrieve(
        registry=registry,
        store=store,
        query="q",
        tool_space="provider_space",
        include_subagents=False,
        user_context=({"general", "provider_space"}, {}, set()),
    )
    assert result["response"] == ["ptool", "web_search_tool"]


@pytest.mark.asyncio
async def test_retrieve_tools_discovery_searches_desktop_namespace_for_desktop_source():
    registry = _FakeRegistry(["DESKTOP_READ"])
    store = _FakeStore(
        {("desktop",): [_item("DESKTOP_READ", 0.9, ("desktop",))]}
    )
    result = await _run_retrieve(
        registry=registry,
        store=store,
        query="q",
        include_subagents=False,
        user_context=({"general"}, {}, set()),
        config={
            "configurable": {
                "user_id": "u1",
                "conversation_source": "desktop",
            }
        },
    )
    assert (("desktop",), "q", 10) in store.calls
    assert "DESKTOP_READ" in result["response"]


@pytest.mark.asyncio
async def test_retrieve_tools_discovery_item_without_key_attr_crashes_loudly(_fake_log):
    # An item lacking the `key` attribute is skipped by the chroma_preview
    # loop (getattr default None) but fails the debug preview's attribute
    # access and real processing — the crash must propagate loudly.
    no_key_item = SimpleNamespace(score=0.7, namespace=("general",))
    store = _FakeStore(
        {
            ("general",): [
                no_key_item,
                _item("tool_a", 0.9, ("general",)),
            ],
        }
    )
    with pytest.raises(AttributeError):
        await _run_retrieve(
            registry=_FakeRegistry(["tool_a"]),
            store=store,
            query="q",
            include_subagents=False,
            user_context=({"general"}, {}, set()),
        )
    _fake_log.debug.assert_any_call(
        f"{LogTag.TOOL} Chroma search raw hits log failed",
        task_index=0,
        error_type="AttributeError",
    )


@pytest.mark.asyncio
async def test_retrieve_tools_discovery_raises_when_every_search_fails():
    store = _FailingStore({("general",)})
    with pytest.raises(RuntimeError, match="search failed for"):
        await _run_retrieve(
            registry=_FakeRegistry([]),
            store=store,
            query="q",
            include_subagents=False,
            user_context=({"general"}, {}, set()),
        )


@pytest.mark.asyncio
async def test_retrieve_tools_discovery_degrades_on_partial_failure(_fake_log):
    store = _FailingStore({("general",), ("subagents",)})
    result = await _run_retrieve(
        registry=_FakeRegistry([]),
        store=store,
        query="q",
        user_context=({"general"}, {}, set()),
        public_integrations=[{"integration_id": "pub1", "name": "Pub", "relevance_score": 0.4}],
    )
    # Only the surviving public-integration search contributes.
    assert result["response"] == ["subagent:pub1 (Pub)"]
    assert _fake_log.error.call_count == 2
    _fake_log.error.assert_any_call(
        f"{LogTag.TOOL} retrieve_tools search task failed",
        error="search failed for ('general',)",
        error_type="RuntimeError",
    )
    _fake_log.error.assert_any_call(
        f"{LogTag.TOOL} retrieve_tools search task failed",
        error="search failed for ('subagents',)",
        error_type="RuntimeError",
    )


@pytest.mark.asyncio
async def test_retrieve_tools_discovery_falls_back_to_metadata_user_id():
    registry = _FakeRegistry(["TOOL_A"])
    store = _FakeStore({("general",): [_item("TOOL_A", 0.9, ("general",))]})
    config: dict = {"configurable": {}, "metadata": {"user_id": "u9"}}
    with patch.object(
        retrieval, "_get_user_context", new=AsyncMock(return_value=({"general"}, {}, set()))
    ) as get_user_context:
        await _run_retrieve(
            registry=registry,
            store=store,
            query="q",
            include_subagents=False,
            patch_user_context=False,
            config=config,
        )
    get_user_context.assert_awaited_once_with("u9", "general", False)
    assert config["configurable"]["user_id"] == "u9"


@pytest.mark.asyncio
async def test_retrieve_tools_discovery_no_subagent_injection_when_disabled():
    registry = _FakeRegistry(["normal_tool"])
    store = _FakeStore({("general",): [_item("normal_tool", 0.9, ("general",))]})
    result = await _run_retrieve(
        registry=registry,
        store=store,
        query="q",
        include_subagents=False,
        user_context=({"general"}, {"gmail": "Gmail"}, {"todos"}),
    )
    # connected/internal subagents must not appear when include_subagents=False.
    assert result["response"] == ["normal_tool"]


@pytest.mark.asyncio
async def test_retrieve_tools_discovery_zero_chroma_hits_warns_for_subagent_space(_fake_log):
    await _run_retrieve(
        registry=_FakeRegistry([]),
        store=_FakeStore({}),
        query="q",
        tool_space="github",
        include_subagents=False,
        user_context=({"github"}, {}, set()),
    )
    _fake_log.warning.assert_any_call(
        f"{LogTag.TOOL} retrieve_tools: 0 ChromaDB hits — check that index_tools_to_store actually wrote docs for this namespace",
        tool_space="github",
        user_id="u1",
    )


@pytest.mark.asyncio
async def test_retrieve_tools_discovery_zero_chroma_hits_no_warning_for_general(_fake_log):
    await _run_retrieve(
        registry=_FakeRegistry([]),
        store=_FakeStore({}),
        query="q",
        include_subagents=False,
        user_context=({"general"}, {}, set()),
    )
    _fake_log.warning.assert_not_called()


@pytest.mark.asyncio
async def test_retrieve_tools_discovery_with_hits_no_zero_warning(_fake_log):
    await _run_retrieve(
        registry=_FakeRegistry(["TOOL_A"]),
        store=_FakeStore({("github",): [_item("TOOL_A", 0.9, ("github",))]}),
        query="q",
        tool_space="github",
        include_subagents=False,
        user_context=({"github"}, {}, set()),
    )
    _fake_log.warning.assert_not_called()
