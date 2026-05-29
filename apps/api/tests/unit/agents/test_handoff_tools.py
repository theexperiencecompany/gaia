"""Tests for app.agents.core.subagents.handoff_tools.

BEHAVIOR SPEC
=============

UNIT: _extract_service_username(metadata)
EXPECTED: Return the first truthy value among metadata["username"|"login"|"handle"],
          coerced to str; None when metadata is falsy or holds none of those keys.
MECHANISM: guard `if not metadata`; iterate ("username","login","handle") in order;
           `if value: return str(value)`; else None.
MUST-CATCH:
  - None / empty dict -> None (guard)
  - precedence: "username" wins over "login"/"handle"
  - falls through to "login" then "handle" when earlier keys absent/empty
  - empty-string value is skipped (falsy), not returned
  - non-str value is coerced to str

UNIT: _sanitize_task_user_reference(task, gaia_name, provider_hint, service_username)
EXPECTED: Replace the GAIA display name in user/username/account references with the
          service username (or "authenticated user"), but ONLY when the provider_hint
          appears in the task. No-op when gaia_name is falsy or provider not mentioned.
MECHANISM: early-return if not gaia_name; lower-case provider_hint membership test;
           replacement = service_username or "authenticated user"; 3 regex subs over
           user:/username:/account: prefixes (case-insensitive, regex-escaped name).
MUST-CATCH:
  - no gaia_name -> task returned unchanged
  - provider_hint absent from task -> unchanged (the gating branch)
  - provider present + name present -> name replaced with service_username
  - service_username None -> replaced with literal "authenticated user"
  - replacement is case-insensitive on the prefix but preserves the prefix text
  - only user/username/account-prefixed occurrences are rewritten

UNIT: check_integration_connection(integration_id, user_id)
EXPECTED: None when subagent unknown OR already connected; on not-connected, stream a
          progress frame + an integration_connection_required frame and return a
          "<name> is not connected" instruction string; None on any exception.
MECHANISM: get_subagent_by_id; check_integration_status; two writer() frames; return f-string.
MUST-CATCH:
  - unknown subagent -> None (no status check, no writer)
  - connected -> None
  - not connected -> exact return string + exact two streamed frame shapes
  - exception -> swallowed, returns None

UNIT: _get_subagent_by_id(subagent_id)
EXPECTED: Lowercase+strip the id; return platform Subagent if registry knows it; else
          consult Redis cache (negative cache -> None), then MongoDB by integration_id/
          name regex, then IntegrationResolver; cache positive+negative results.
MECHANISM: get_subagent_by_id; get_cache; re.escape; integrations_collection.find_one
           with anchored case-insensitive regex; set_cache; IntegrationResolver.resolve.
MUST-CATCH:
  - platform hit short-circuits (no cache/db calls)
  - id is lowercased+stripped before lookup
  - cached positive returned as-is; cached empty dict -> None
  - mongo custom doc -> mapped dict with id/name/source/managed_by defaults + cached
  - resolver fallback -> mapped dict carrying resolver.source + cached
  - nothing found -> negative cache written, None returned
  - regex is anchored (^) and case-insensitive ($options i)

UNIT: index_custom_mcp_as_subagent(store, ...)
EXPECTED: Build a rich description, derive a tool namespace, and abatch a single PutOp
          into the ("subagents",) namespace keyed by integration_id, indexed on description.
MUST-CATCH:
  - PutOp namespace, key, value fields (id/name/source=custom/tool_namespace) exact
  - description embeds name + provided description
  - index list is exactly ["description"]

UNIT: _resolve_subagent(subagent_id, user_id)
EXPECTED: Resolve to (graph, agent_name, integration_id, is_custom) or
          (None, None, error, False). Custom MCP, auth-gated MCP, and plain platform
          subagent each follow a distinct branch with distinct error strings.
MUST-CATCH:
  - unknown -> "not found" error, available list capped at 5 with trailing "..."
  - custom dict happy path -> graph, is_custom True, agent_name custom_mcp_<id>
  - custom no user_id -> auth error; custom empty id -> "no ID" error; graph None -> "Failed to create"
  - mcp+requires_auth: no user / not connected / connected / graph-None branches
  - non-mcp non-internal + user_id -> check_integration_connection gate
  - internal -> providers.aget; KeyError or None -> "not available"

UNIT: handoff(subagent_id, task, config) [the @tool coroutine]
EXPECTED: Resolve subagent, sanitize the task's user reference, build a child config +
          system message + initial messages, then return execute_subagent_stream's result.
          Resolution failure returns the resolver error; any exception returns
          "Error executing task: <e>".
MUST-CATCH:
  - resolution failure short-circuits and returns the resolver error string
  - user_id falls back from metadata when absent in configurable
  - the sanitized task (not the raw task) is forwarded into the run state intent
  - platform integration_metadata carries the subagent name + integration_id
  - the streamed result is returned verbatim
  - an exception in the chain returns the "Error executing task:" wrapper

EQUIVALENT MUTANTS (allowed survivors, justified): see test for line-by-line notes.
None expected after this rewrite; any survivor is a real gap.
"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.core.subagents.handoff_tools import (
    _extract_service_username,
    _get_subagent_by_id,
    _resolve_subagent,
    _sanitize_task_user_reference,
    check_integration_connection,
    handoff,
    index_custom_mcp_as_subagent,
)
from app.constants.cache import SUBAGENT_CACHE_PREFIX
from app.models.mcp_config import MCPConfig, SubAgentConfig
from app.models.subagent_models import Subagent

MODULE = "app.agents.core.subagents.handoff_tools"


def _make_subagent_config(agent_name: str = "gmail_agent") -> SubAgentConfig:
    return SubAgentConfig(
        has_subagent=True,
        agent_name=agent_name,
        tool_space="gmail_space",
        handoff_tool_name="call_gmail",
        domain="gmail",
        capabilities="email",
        use_cases="emails",
        system_prompt="You are gmail.",
    )


def _make_subagent(
    subagent_id: str = "gmail",
    short_name: str | None = "gmail",
    name: str = "Gmail",
    managed_by: str = "internal",
    mcp_config: MCPConfig | None = None,
    agent_name: str = "gmail_agent",
    provider: str | None = None,
) -> Subagent:
    """Real Subagent for tests of handoff_tools (post-refactor)."""
    return Subagent(
        id=subagent_id,
        name=name,
        provider=provider if provider is not None else subagent_id,
        managed_by=managed_by,  # type: ignore[arg-type]
        config=_make_subagent_config(agent_name=agent_name),
        short_name=short_name,
        mcp_config=mcp_config,
    )


# ---------------------------------------------------------------------------
# _extract_service_username  (pure)
# ---------------------------------------------------------------------------


class TestExtractServiceUsername:
    def test_none_metadata_returns_none(self):
        assert _extract_service_username(None) is None

    def test_empty_dict_returns_none(self):
        assert _extract_service_username({}) is None

    def test_no_matching_keys_returns_none(self):
        assert _extract_service_username({"email": "a@b.com", "id": "x"}) is None

    def test_username_key_wins(self):
        result = _extract_service_username(
            {"username": "primary", "login": "secondary", "handle": "tertiary"}
        )
        assert result == "primary"

    def test_falls_through_to_login(self):
        # username absent -> login is used (not handle).
        assert _extract_service_username({"login": "octocat", "handle": "ignored"}) == "octocat"

    def test_falls_through_to_handle(self):
        assert _extract_service_username({"handle": "tweety"}) == "tweety"

    def test_empty_username_is_skipped(self):
        # Empty string is falsy: skip "username", keep scanning to "login".
        assert _extract_service_username({"username": "", "login": "fallback"}) == "fallback"

    def test_non_str_value_coerced_to_str(self):
        assert _extract_service_username({"username": 12345}) == "12345"


# ---------------------------------------------------------------------------
# _sanitize_task_user_reference  (pure)
# ---------------------------------------------------------------------------


class TestSanitizeTaskUserReference:
    def test_no_gaia_name_is_noop(self):
        task = "Send an email as user: Aryan on gmail"
        assert (
            _sanitize_task_user_reference(
                task=task, gaia_name=None, provider_hint="gmail", service_username="real"
            )
            == task
        )

    def test_provider_absent_is_noop(self):
        # provider_hint not in task -> nothing is rewritten even though name appears.
        task = "Tell user: Aryan about the meeting"
        assert (
            _sanitize_task_user_reference(
                task=task, gaia_name="Aryan", provider_hint="gmail", service_username="real"
            )
            == task
        )

    def test_replaces_name_with_service_username(self):
        task = "On gmail, set username: Aryan as the sender"
        result = _sanitize_task_user_reference(
            task=task, gaia_name="Aryan", provider_hint="gmail", service_username="aryan@work"
        )
        assert "aryan@work" in result
        assert "username: Aryan" not in result
        # prefix preserved, value swapped
        assert "username: aryan@work" in result

    def test_none_service_username_uses_authenticated_user(self):
        task = "On gmail, account: Aryan should send"
        result = _sanitize_task_user_reference(
            task=task, gaia_name="Aryan", provider_hint="gmail", service_username=None
        )
        assert "account: authenticated user" in result
        assert "Aryan" not in result

    def test_quoting_around_name_is_preserved(self):
        # The replacement template is \1<value>\3 — group 3 is the trailing quote.
        # A quoted reference keeps both quotes around the substituted value.
        task = 'On gmail, user: "Aryan" sends mail'
        result = _sanitize_task_user_reference(
            task=task, gaia_name="Aryan", provider_hint="gmail", service_username="svc"
        )
        assert result == 'On gmail, user: "svc" sends mail'

    def test_provider_match_is_case_insensitive(self):
        # provider_hint membership check lower-cases the task.
        task = "On GMAIL, user: Aryan composes"
        result = _sanitize_task_user_reference(
            task=task, gaia_name="Aryan", provider_hint="gmail", service_username="real-user"
        )
        assert "user: real-user" in result

    def test_only_prefixed_references_are_rewritten(self):
        # "Aryan" appears bare AND behind a "user:" prefix; only the prefixed one changes.
        task = "On gmail, user: Aryan asked Aryan to reply"
        result = _sanitize_task_user_reference(
            task=task, gaia_name="Aryan", provider_hint="gmail", service_username="svc"
        )
        assert result == "On gmail, user: svc asked Aryan to reply"


# ---------------------------------------------------------------------------
# check_integration_connection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCheckIntegrationConnection:
    async def test_returns_none_when_integration_not_found(self):
        with patch(f"{MODULE}.get_subagent_by_id", return_value=None):
            result = await check_integration_connection("bogus", "user1")
        assert result is None

    async def test_returns_none_when_connected(self):
        subagent = _make_subagent("gmail")
        with (
            patch(f"{MODULE}.get_subagent_by_id", return_value=subagent),
            patch(
                f"{MODULE}.check_integration_status",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            result = await check_integration_connection("gmail", "user1")
        assert result is None

    async def test_not_connected_streams_frames_and_returns_exact_message(self):
        subagent = _make_subagent("gmail", name="Gmail")
        mock_writer = MagicMock()
        with (
            patch(f"{MODULE}.get_subagent_by_id", return_value=subagent),
            patch(
                f"{MODULE}.check_integration_status",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(f"{MODULE}.get_stream_writer", return_value=mock_writer),
        ):
            result = await check_integration_connection("gmail", "user1")

        # Exact return string (pins both literal segments + the interpolated name).
        assert result == "Integration Gmail is not connected. Please connect it first."

        # Exactly two frames, in order, with exact shapes (frontend contract).
        assert mock_writer.call_count == 2
        progress_frame = mock_writer.call_args_list[0].args[0]
        assert progress_frame == {"progress": "Checking Gmail connection..."}

        connection_frame = mock_writer.call_args_list[1].args[0]
        assert connection_frame == {
            "integration_connection_required": {
                "integration_id": "gmail",
                "message": "To use Gmail features, please connect your account first.",
            }
        }

    async def test_returns_none_on_exception(self):
        with patch(f"{MODULE}.get_subagent_by_id", side_effect=RuntimeError("boom")):
            result = await check_integration_connection("bad", "user1")
        assert result is None


# ---------------------------------------------------------------------------
# _get_subagent_by_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetSubagentById:
    async def test_platform_hit_short_circuits(self):
        subagent = _make_subagent("gmail")
        with (
            patch(f"{MODULE}.get_subagent_by_id", return_value=subagent),
            patch(f"{MODULE}.get_cache", new_callable=AsyncMock) as mock_get_cache,
        ):
            result = await _get_subagent_by_id("gmail")
        assert result is subagent
        # Platform hit must not touch the cache/DB at all.
        mock_get_cache.assert_not_awaited()

    async def test_lookup_id_is_lowercased_and_stripped(self):
        subagent = _make_subagent("gmail")
        with patch(f"{MODULE}.get_subagent_by_id", return_value=subagent) as mock_lookup:
            await _get_subagent_by_id("  GMAIL  ")
        mock_lookup.assert_called_once_with("gmail")

    async def test_returns_cached_custom_integration(self):
        cached = {"id": "abc123", "name": "Custom MCP"}
        with (
            patch(f"{MODULE}.get_subagent_by_id", return_value=None),
            patch(f"{MODULE}.get_cache", new_callable=AsyncMock, return_value=cached),
        ):
            result = await _get_subagent_by_id("abc123")
        assert result == cached

    async def test_negative_cache_returns_none(self):
        with (
            patch(f"{MODULE}.get_subagent_by_id", return_value=None),
            patch(f"{MODULE}.get_cache", new_callable=AsyncMock, return_value={}),
        ):
            result = await _get_subagent_by_id("missing")
        assert result is None

    async def test_finds_custom_from_mongodb_and_caches(self):
        # source/managed_by intentionally differ from the .get() defaults
        # ("custom"/"mcp") so the lookup keys are pinned, not just the defaults.
        custom_doc = {
            "integration_id": "abc",
            "name": "My MCP",
            "source": "marketplace",
            "managed_by": "self",
            "mcp_config": {"url": "https://example.com"},
            "icon_url": "https://example.com/icon.png",
        }
        with (
            patch(f"{MODULE}.get_subagent_by_id", return_value=None),
            patch(f"{MODULE}.get_cache", new_callable=AsyncMock, return_value=None),
            patch(f"{MODULE}.integrations_collection") as mock_col,
            patch(f"{MODULE}.set_cache", new_callable=AsyncMock) as mock_set_cache,
        ):
            mock_col.find_one = AsyncMock(return_value=custom_doc)
            result = await _get_subagent_by_id("abc")

        assert result == {
            "id": "abc",
            "name": "My MCP",
            "source": "marketplace",
            "managed_by": "self",
            "mcp_config": {"url": "https://example.com"},
            "icon_url": "https://example.com/icon.png",
            "subagent_config": None,
        }
        # Positive result is cached under the prefixed key.
        mock_set_cache.assert_awaited_once()
        cache_key = mock_set_cache.await_args.args[0]
        assert cache_key == f"{SUBAGENT_CACHE_PREFIX}:abc"

    async def test_mongo_query_uses_anchored_case_insensitive_regex(self):
        with (
            patch(f"{MODULE}.get_subagent_by_id", return_value=None),
            patch(f"{MODULE}.get_cache", new_callable=AsyncMock, return_value=None),
            patch(f"{MODULE}.integrations_collection") as mock_col,
            patch(f"{MODULE}.IntegrationResolver") as mock_resolver,
            patch(f"{MODULE}.set_cache", new_callable=AsyncMock),
        ):
            mock_col.find_one = AsyncMock(return_value=None)
            mock_resolver.resolve = AsyncMock(return_value=None)
            await _get_subagent_by_id("my-mcp")

        query = mock_col.find_one.await_args.args[0]
        clauses = query["$or"]
        id_clause = clauses[0]["integration_id"]
        name_clause = clauses[1]["name"]
        # Prefix-anchored for integration_id, fully-anchored for name; both ci.
        assert id_clause == {"$regex": "^my\\-mcp", "$options": "i"}
        assert name_clause == {"$regex": "^my\\-mcp$", "$options": "i"}

    async def test_defaults_applied_when_mongo_doc_omits_source_and_managed_by(self):
        # Doc without source/managed_by exercises the .get(..., default) branches.
        custom_doc = {"integration_id": "raw", "name": "Raw MCP"}
        with (
            patch(f"{MODULE}.get_subagent_by_id", return_value=None),
            patch(f"{MODULE}.get_cache", new_callable=AsyncMock, return_value=None),
            patch(f"{MODULE}.integrations_collection") as mock_col,
            patch(f"{MODULE}.set_cache", new_callable=AsyncMock),
        ):
            mock_col.find_one = AsyncMock(return_value=custom_doc)
            result = await _get_subagent_by_id("raw")

        assert result["source"] == "custom"
        assert result["managed_by"] == "mcp"

    async def test_fallback_to_integration_resolver(self):
        resolved_doc = {
            "integration_id": "res_id",
            "name": "Resolved",
            "mcp_config": {"url": "u"},
            "icon_url": "https://icon",
        }
        resolved = SimpleNamespace(custom_doc=resolved_doc, source="user_integrations")
        with (
            patch(f"{MODULE}.get_subagent_by_id", return_value=None),
            patch(f"{MODULE}.get_cache", new_callable=AsyncMock, return_value=None),
            patch(f"{MODULE}.integrations_collection") as mock_col,
            patch(f"{MODULE}.IntegrationResolver") as mock_resolver,
            patch(f"{MODULE}.set_cache", new_callable=AsyncMock),
        ):
            mock_col.find_one = AsyncMock(return_value=None)
            mock_resolver.resolve = AsyncMock(return_value=resolved)
            result = await _get_subagent_by_id("res_id")

        # Every mapped field pins the dict KEY (not just the value).
        assert result == {
            "id": "res_id",
            "name": "Resolved",
            "source": "user_integrations",
            "managed_by": "mcp",
            "mcp_config": {"url": "u"},
            "icon_url": "https://icon",
            "subagent_config": None,
        }

    async def test_nothing_found_writes_negative_cache_and_returns_none(self):
        with (
            patch(f"{MODULE}.get_subagent_by_id", return_value=None),
            patch(f"{MODULE}.get_cache", new_callable=AsyncMock, return_value=None),
            patch(f"{MODULE}.integrations_collection") as mock_col,
            patch(f"{MODULE}.IntegrationResolver") as mock_resolver,
            patch(f"{MODULE}.set_cache", new_callable=AsyncMock) as mock_set_cache,
        ):
            mock_col.find_one = AsyncMock(return_value=None)
            mock_resolver.resolve = AsyncMock(return_value=None)
            result = await _get_subagent_by_id("slack")

        assert result is None
        # Negative cache: empty dict written under the prefixed key.
        mock_set_cache.assert_awaited_once()
        assert mock_set_cache.await_args.args[0] == f"{SUBAGENT_CACHE_PREFIX}:slack"
        assert mock_set_cache.await_args.args[1] == {}


# ---------------------------------------------------------------------------
# index_custom_mcp_as_subagent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestIndexCustomMcpAsSubagent:
    async def test_indexes_mcp_with_exact_put_op(self):
        mock_store = AsyncMock()
        with patch(
            f"{MODULE}.derive_integration_namespace",
            return_value="example.com",
        ) as mock_ns:
            await index_custom_mcp_as_subagent(
                store=mock_store,
                integration_id="abc123",
                name="My Tool",
                description="Does stuff",
                server_url="https://example.com/mcp",
            )

        # Exactly one batched op.
        mock_store.abatch.assert_awaited_once()
        ops = mock_store.abatch.await_args.args[0]
        assert len(ops) == 1
        put_op = ops[0]

        assert put_op.namespace == ("subagents",)
        assert put_op.key == "abc123"
        assert put_op.index == ["description"]

        value = put_op.value
        assert value["id"] == "abc123"
        assert value["name"] == "My Tool"
        assert value["source"] == "custom"
        assert value["tool_namespace"] == "example.com"
        # Rich description embeds the name and the caller's description verbatim,
        # including the literal separators between them.
        assert value["description"] == (
            "My Tool. Custom MCP integration. "
            "Does stuff. "
            "Use cases: data fetching, automation, API access, external services. "
            "Examples: fetch data, scrape, query, automate"
        )

        # Namespace derivation gets the custom flag.
        mock_ns.assert_called_once_with("abc123", "https://example.com/mcp", is_custom=True)


# ---------------------------------------------------------------------------
# _resolve_subagent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestResolveSubagent:
    async def test_not_found_lists_examples_capped_at_five(self):
        # Six available -> list capped at 5 with trailing "...".
        available = tuple(_make_subagent(f"agent{i}") for i in range(6))
        with (
            patch(f"{MODULE}._get_subagent_by_id", new_callable=AsyncMock, return_value=None),
            patch(f"{MODULE}.all_subagents", return_value=available),
        ):
            graph, name, error, is_custom = await _resolve_subagent("unknown", "user1")

        assert graph is None
        assert name is None
        assert is_custom is False
        # Pin every literal segment of the guidance message, not just a substring.
        assert error.startswith("Subagent 'unknown' not found. ")
        assert "Use retrieve_tools to find available subagents. " in error
        assert "Examples: " in error
        assert error.endswith("...")
        # Exactly five examples are rendered (the cap), each prefixed.
        assert error.count("subagent:agent") == 5
        # Examples are comma+space joined (pins the ", " separator literal).
        assert "subagent:agent0, subagent:agent1" in error

    async def test_not_found_no_ellipsis_when_under_five(self):
        available = (_make_subagent("a"), _make_subagent("b"))
        with (
            patch(f"{MODULE}._get_subagent_by_id", new_callable=AsyncMock, return_value=None),
            patch(f"{MODULE}.all_subagents", return_value=available),
        ):
            _, _, error, _ = await _resolve_subagent("unknown", "user1")
        assert not error.endswith("...")

    async def test_resolves_custom_mcp(self):
        custom_dict = {"id": "abc", "name": "Custom"}
        mock_graph = MagicMock()
        with (
            patch(
                f"{MODULE}._get_subagent_by_id",
                new_callable=AsyncMock,
                return_value=custom_dict,
            ),
            patch(
                f"{MODULE}.create_subagent_for_user",
                new_callable=AsyncMock,
                return_value=mock_graph,
            ) as mock_create,
        ):
            graph, name, int_id, is_custom = await _resolve_subagent("abc", "user1")
        assert graph is mock_graph
        assert is_custom is True
        assert int_id == "abc"
        assert name == "custom_mcp_abc"
        mock_create.assert_awaited_once_with("abc", "user1")

    async def test_custom_mcp_no_user_id(self):
        custom_dict = {"id": "abc", "name": "Custom"}
        with patch(
            f"{MODULE}._get_subagent_by_id",
            new_callable=AsyncMock,
            return_value=custom_dict,
        ):
            graph, name, error, is_custom = await _resolve_subagent("abc", None)
        assert graph is None
        assert is_custom is False
        assert error == "Error: Custom requires authentication. Please sign in first."

    async def test_custom_mcp_no_id_field(self):
        custom_dict = {"id": "", "name": "Broken"}
        with patch(
            f"{MODULE}._get_subagent_by_id",
            new_callable=AsyncMock,
            return_value=custom_dict,
        ):
            graph, name, error, is_custom = await _resolve_subagent("broken", "user1")
        assert graph is None
        assert is_custom is False
        assert error == "Error: Custom integration has no ID"

    async def test_custom_mcp_graph_creation_fails(self):
        custom_dict = {"id": "abc", "name": "Custom"}
        with (
            patch(
                f"{MODULE}._get_subagent_by_id",
                new_callable=AsyncMock,
                return_value=custom_dict,
            ),
            patch(
                f"{MODULE}.create_subagent_for_user",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            graph, name, error, is_custom = await _resolve_subagent("abc", "user1")
        assert graph is None
        assert is_custom is False
        assert error == "Error: Failed to create subagent for Custom"

    async def test_platform_mcp_requires_auth_connected(self):
        mcp_cfg = MCPConfig(server_url="https://example.com", requires_auth=True)
        subagent = _make_subagent("gmail", "gmail", "Gmail", managed_by="mcp", mcp_config=mcp_cfg)
        mock_graph = MagicMock()
        with (
            patch(
                f"{MODULE}._get_subagent_by_id",
                new_callable=AsyncMock,
                return_value=subagent,
            ),
            patch(f"{MODULE}.MCPTokenStore") as mock_ts_cls,
            patch(
                f"{MODULE}.create_subagent_for_user",
                new_callable=AsyncMock,
                return_value=mock_graph,
            ) as mock_create,
        ):
            mock_ts = AsyncMock()
            mock_ts.is_connected = AsyncMock(return_value=True)
            mock_ts_cls.return_value = mock_ts
            graph, name, int_id, is_custom = await _resolve_subagent("subagent:gmail", "user1")
        assert graph is mock_graph
        assert is_custom is False
        assert int_id == "gmail"
        # Token store built for the right user; graph created with the integration id.
        mock_ts_cls.assert_called_once_with(user_id="user1")
        mock_create.assert_awaited_once_with("gmail", "user1")

    async def test_platform_mcp_requires_auth_not_connected(self):
        mcp_cfg = MCPConfig(server_url="https://example.com", requires_auth=True)
        subagent = _make_subagent("gmail", "gmail", "Gmail", managed_by="mcp", mcp_config=mcp_cfg)
        with (
            patch(
                f"{MODULE}._get_subagent_by_id",
                new_callable=AsyncMock,
                return_value=subagent,
            ),
            patch(f"{MODULE}.MCPTokenStore") as mock_ts_cls,
            patch(
                f"{MODULE}.create_subagent_for_user",
                new_callable=AsyncMock,
            ) as mock_create,
        ):
            mock_ts = AsyncMock()
            mock_ts.is_connected = AsyncMock(return_value=False)
            mock_ts_cls.return_value = mock_ts
            graph, name, error, is_custom = await _resolve_subagent("gmail", "user1")
        assert graph is None
        assert is_custom is False
        # Both f-string segments (agent_name + display name) are pinned exactly.
        assert error == (
            "Error: gmail_agent requires OAuth connection. Please connect Gmail first via settings."
        )
        # Not-connected path must not attempt to create a graph.
        mock_create.assert_not_awaited()

    async def test_platform_mcp_requires_auth_no_user(self):
        mcp_cfg = MCPConfig(server_url="https://example.com", requires_auth=True)
        subagent = _make_subagent("gmail", "gmail", "Gmail", managed_by="mcp", mcp_config=mcp_cfg)
        with patch(
            f"{MODULE}._get_subagent_by_id",
            new_callable=AsyncMock,
            return_value=subagent,
        ):
            graph, name, error, is_custom = await _resolve_subagent("gmail", None)
        assert graph is None
        assert is_custom is False
        assert error == "Error: gmail_agent requires authentication. Please sign in first."

    async def test_platform_non_mcp_uses_provider(self):
        subagent = _make_subagent(
            "gcal",
            "gcal",
            "Google Calendar",
            managed_by="internal",
            agent_name="calendar_agent",
        )
        mock_graph = MagicMock()
        with (
            patch(
                f"{MODULE}._get_subagent_by_id",
                new_callable=AsyncMock,
                return_value=subagent,
            ),
            patch(
                f"{MODULE}.check_integration_connection",
                new_callable=AsyncMock,
                return_value="should-not-be-used",
            ) as mock_check,
            patch(f"{MODULE}.providers") as mock_providers,
        ):
            mock_providers.aget = AsyncMock(return_value=mock_graph)
            graph, name, int_id, is_custom = await _resolve_subagent("gcal", "user1")
        assert graph is mock_graph
        assert name == "calendar_agent"
        assert int_id == "gcal"
        assert is_custom is False
        mock_providers.aget.assert_awaited_once_with("calendar_agent")
        # "internal" is in the skip-list, so the connection gate is bypassed entirely
        # (the `not in ("mcp", "internal") and user_id` guard is False).
        mock_check.assert_not_awaited()

    async def test_platform_non_auth_mcp_skips_connection_gate(self):
        # managed_by == "mcp" but requires_auth False -> falls to the else branch.
        # "mcp" is in the skip-list, so the connection gate must NOT run.
        mcp_cfg = MCPConfig(server_url="https://example.com", requires_auth=False)
        subagent = _make_subagent(
            "notion",
            "notion",
            "Notion",
            managed_by="mcp",
            mcp_config=mcp_cfg,
            agent_name="notion_agent",
        )
        mock_graph = MagicMock()
        with (
            patch(
                f"{MODULE}._get_subagent_by_id",
                new_callable=AsyncMock,
                return_value=subagent,
            ),
            patch(
                f"{MODULE}.check_integration_connection",
                new_callable=AsyncMock,
                return_value="should-not-be-used",
            ) as mock_check,
            patch(f"{MODULE}.providers") as mock_providers,
        ):
            mock_providers.aget = AsyncMock(return_value=mock_graph)
            graph, name, int_id, is_custom = await _resolve_subagent("notion", "user1")
        assert graph is mock_graph
        assert name == "notion_agent"
        assert is_custom is False
        mock_check.assert_not_awaited()
        mock_providers.aget.assert_awaited_once_with("notion_agent")

    async def test_platform_composio_checks_connection(self):
        # managed_by not in (mcp, internal) AND user_id present -> connection gate.
        subagent = _make_subagent(
            "composio",
            "composio",
            "Composio",
            managed_by="composio",
            agent_name="composio_agent",
        )
        with (
            patch(
                f"{MODULE}._get_subagent_by_id",
                new_callable=AsyncMock,
                return_value=subagent,
            ),
            patch(
                f"{MODULE}.check_integration_connection",
                new_callable=AsyncMock,
                return_value="Not connected",
            ),
            patch(f"{MODULE}.providers") as mock_providers,
        ):
            mock_providers.aget = AsyncMock()
            graph, name, error, is_custom = await _resolve_subagent("composio", "user1")
        assert graph is None
        assert is_custom is False
        assert error == "Not connected"
        # Gate failed -> provider lookup never happens.
        mock_providers.aget.assert_not_awaited()

    async def test_platform_provider_not_available_when_none(self):
        subagent = _make_subagent("x", "x", "X", managed_by="internal", agent_name="missing_agent")
        with (
            patch(
                f"{MODULE}._get_subagent_by_id",
                new_callable=AsyncMock,
                return_value=subagent,
            ),
            patch(f"{MODULE}.providers") as mock_providers,
        ):
            mock_providers.aget = AsyncMock(return_value=None)
            graph, name, error, is_custom = await _resolve_subagent("x", "user1")
        assert graph is None
        assert is_custom is False
        assert error == "Error: missing_agent not available"

    async def test_platform_provider_not_available_on_keyerror(self):
        subagent = _make_subagent("x", "x", "X", managed_by="internal", agent_name="missing_agent")
        with (
            patch(
                f"{MODULE}._get_subagent_by_id",
                new_callable=AsyncMock,
                return_value=subagent,
            ),
            patch(f"{MODULE}.providers") as mock_providers,
        ):
            mock_providers.aget = AsyncMock(side_effect=KeyError("missing_agent"))
            graph, name, error, is_custom = await _resolve_subagent("x", "user1")
        assert graph is None
        assert is_custom is False
        assert error == "Error: missing_agent not available"

    async def test_platform_mcp_graph_creation_fails(self):
        mcp_cfg = MCPConfig(server_url="https://example.com", requires_auth=True)
        subagent = _make_subagent(
            "mcp_int",
            "mcp_int",
            "MCP Int",
            managed_by="mcp",
            mcp_config=mcp_cfg,
            agent_name="mcp_agent",
        )
        with (
            patch(
                f"{MODULE}._get_subagent_by_id",
                new_callable=AsyncMock,
                return_value=subagent,
            ),
            patch(f"{MODULE}.MCPTokenStore") as mock_ts_cls,
            patch(
                f"{MODULE}.create_subagent_for_user",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            mock_ts = AsyncMock()
            mock_ts.is_connected = AsyncMock(return_value=True)
            mock_ts_cls.return_value = mock_ts
            graph, name, error, is_custom = await _resolve_subagent("mcp_int", "user1")
        assert graph is None
        assert is_custom is False
        assert error == "Error: Failed to create mcp_agent subagent"


# ---------------------------------------------------------------------------
# handoff (the @tool coroutine)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestHandoff:
    async def test_resolution_failure_returns_error_string(self):
        config = {"configurable": {"user_id": "user1", "thread_id": "t1"}}
        with patch(
            f"{MODULE}._resolve_subagent",
            new_callable=AsyncMock,
            return_value=(None, None, "Subagent 'x' not found.", False),
        ):
            result = await handoff.coroutine("x", "do a thing", config)
        assert result == "Subagent 'x' not found."

    async def test_resolution_failure_with_none_error_uses_fallback(self):
        # graph None but error message also None -> the `or` fallback string.
        config = {"configurable": {"user_id": "user1", "thread_id": "t1"}}
        with patch(
            f"{MODULE}._resolve_subagent",
            new_callable=AsyncMock,
            return_value=(None, None, None, False),
        ):
            result = await handoff.coroutine("x", "do a thing", config)
        assert result == "Unknown error resolving subagent"

    async def test_user_id_falls_back_to_metadata(self):
        # No user_id in configurable; it must be pulled from metadata.
        config = {
            "configurable": {"thread_id": "t1"},
            "metadata": {"user_id": "from-meta"},
        }
        resolve = AsyncMock(return_value=(MagicMock(), "gmail_agent", "gmail", False))
        with (
            patch(f"{MODULE}._resolve_subagent", new=resolve),
            patch(
                f"{MODULE}.create_subagent_system_message",
                new_callable=AsyncMock,
                return_value=SimpleNamespace(content="sys"),
            ),
            patch(f"{MODULE}.get_subagent_by_id", return_value=None),
            patch(
                f"{MODULE}.get_provider_metadata",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(f"{MODULE}.build_initial_messages", new_callable=AsyncMock, return_value=["m"]),
            patch(f"{MODULE}.build_agent_config", return_value={"configurable": {}}),
            patch(f"{MODULE}.execute_subagent_stream", new_callable=AsyncMock, return_value="ok"),
            patch(f"{MODULE}.get_stream_writer", return_value=MagicMock()),
        ):
            await handoff.coroutine("gmail", "task", config)
        # _resolve_subagent received the user_id recovered from metadata.
        assert resolve.await_args.args[1] == "from-meta"
        # And it was written back into configurable for downstream consistency.
        assert config["configurable"]["user_id"] == "from-meta"

    async def test_no_metadata_user_id_means_no_writeback(self):
        # user_id missing everywhere -> the `user_id and "configurable" in config`
        # guard must NOT write a falsy user_id back into the configurable.
        config = {"configurable": {"thread_id": "t1"}, "metadata": {}}
        with (
            patch(
                f"{MODULE}._resolve_subagent",
                new_callable=AsyncMock,
                return_value=(MagicMock(), "gmail_agent", "gmail", False),
            ),
            patch(
                f"{MODULE}.create_subagent_system_message",
                new_callable=AsyncMock,
                return_value=SimpleNamespace(content="sys"),
            ),
            patch(f"{MODULE}.get_subagent_by_id", return_value=None),
            patch(f"{MODULE}.get_provider_metadata", new_callable=AsyncMock, return_value=None),
            patch(f"{MODULE}.build_initial_messages", new_callable=AsyncMock, return_value=["m"]),
            patch(f"{MODULE}.build_agent_config", return_value={"configurable": {}}),
            patch(f"{MODULE}.execute_subagent_stream", new_callable=AsyncMock, return_value="ok"),
            patch(f"{MODULE}.get_stream_writer", return_value=MagicMock()),
        ):
            await handoff.coroutine("gmail", "task", config)
        # No user_id key was injected into the configurable.
        assert "user_id" not in config["configurable"]

    async def test_sanitized_task_and_full_context_wiring(self):
        config = {
            "configurable": {
                "user_id": "user1",
                "thread_id": "t1",
                "user_name": "Aryan",
                "email": "aryan@gaia.dev",
                "stream_id": "stream-99",
                "user_time": "2026-01-01T09:30:00",
            }
        }
        platform = _make_subagent("github", name="GitHub", managed_by="internal", provider="github")
        build_msgs = AsyncMock(return_value=["msg-a", "msg-b"])
        exec_stream = AsyncMock(return_value="done")
        build_cfg = MagicMock(return_value={"configurable": {"child": "cfg"}})
        with (
            patch(
                f"{MODULE}._resolve_subagent",
                new_callable=AsyncMock,
                return_value=(MagicMock(), "github_agent", "github", False),
            ),
            patch(
                f"{MODULE}.create_subagent_system_message",
                new_callable=AsyncMock,
                return_value=SimpleNamespace(content="sys"),
            ),
            patch(f"{MODULE}.get_subagent_by_id", return_value=platform),
            patch(
                f"{MODULE}.get_provider_metadata",
                new_callable=AsyncMock,
                return_value={"username": "octo-real"},
            ),
            patch(f"{MODULE}.build_initial_messages", new=build_msgs),
            patch(f"{MODULE}.build_agent_config", new=build_cfg),
            patch(f"{MODULE}.execute_subagent_stream", new=exec_stream),
            patch(f"{MODULE}.get_stream_writer", return_value=MagicMock()),
        ):
            result = await handoff.coroutine(
                "github", "On github, user: Aryan should open a PR", config
            )

        assert result == "done"
        # The task forwarded to build_initial_messages is sanitized: Aryan -> octo-real.
        forwarded_task = build_msgs.await_args.kwargs["task"]
        assert "user: octo-real" in forwarded_task
        assert "Aryan" not in forwarded_task

        # build_agent_config receives the derived thread id and the assembled user dict.
        cfg_kwargs = build_cfg.call_args.kwargs
        assert cfg_kwargs["conversation_id"] == "t1"
        assert cfg_kwargs["thread_id"] == "github_t1"
        assert cfg_kwargs["user"] == {
            "user_id": "user1",
            "email": "aryan@gaia.dev",
            "name": "Aryan",
        }
        # user_time is parsed from the configurable ISO string (not datetime.now()).
        assert cfg_kwargs["user_time"] == datetime(2026, 1, 1, 9, 30, 0)

        # The child configurable (from build_agent_config) is what gets forwarded.
        assert build_msgs.await_args.kwargs["configurable"] == {"child": "cfg"}

        ctx = exec_stream.await_args.kwargs["ctx"]
        assert ctx.configurable == {"child": "cfg"}
        assert ctx.stream_id == "stream-99"
        # The sanitized task lands in intent; messages/todos are wired through.
        assert ctx.initial_state["intent"] == forwarded_task
        assert ctx.initial_state["messages"] == ["msg-a", "msg-b"]
        assert ctx.initial_state["todos"] == []
        assert ctx.initial_state["integration_usernames"] == {"github": "octo-real"}

    async def test_provider_hint_falls_back_to_int_id_when_no_provider(self):
        # platform_subagent has no provider -> provider_name stays None and the
        # sanitization provider_hint must fall back to int_id ("gmail").
        config = {"configurable": {"user_id": "user1", "thread_id": "t1", "user_name": "Aryan"}}
        # Subagent with empty provider so the `platform_subagent.provider` guard is falsy.
        platform = _make_subagent("gmail", name="Gmail", managed_by="internal", provider="")
        build_msgs = AsyncMock(return_value=["m"])
        with (
            patch(
                f"{MODULE}._resolve_subagent",
                new_callable=AsyncMock,
                return_value=(MagicMock(), "gmail_agent", "gmail", False),
            ),
            patch(
                f"{MODULE}.create_subagent_system_message",
                new_callable=AsyncMock,
                return_value=SimpleNamespace(content="sys"),
            ),
            patch(f"{MODULE}.get_subagent_by_id", return_value=platform),
            patch(f"{MODULE}.get_provider_metadata", new_callable=AsyncMock, return_value=None),
            patch(f"{MODULE}.build_initial_messages", new=build_msgs),
            patch(f"{MODULE}.build_agent_config", return_value={"configurable": {}}),
            patch(f"{MODULE}.execute_subagent_stream", new_callable=AsyncMock, return_value="ok"),
            patch(f"{MODULE}.get_stream_writer", return_value=MagicMock()),
        ):
            await handoff.coroutine("gmail", "On gmail, user: Aryan replies", config)

        # provider_hint == int_id "gmail" is present in the task, so sanitization runs;
        # with no service_username it substitutes the literal "authenticated user".
        forwarded_task = build_msgs.await_args.kwargs["task"]
        assert "user: authenticated user" in forwarded_task

    async def test_integration_usernames_empty_without_service_username(self):
        # provider_name truthy but service_username falsy -> the `and` keeps the
        # integration_usernames map empty (Or would wrongly populate it).
        config = {"configurable": {"user_id": "user1", "thread_id": "t1"}}
        platform = _make_subagent("github", name="GitHub", managed_by="internal", provider="github")
        exec_stream = AsyncMock(return_value="ok")
        with (
            patch(
                f"{MODULE}._resolve_subagent",
                new_callable=AsyncMock,
                return_value=(MagicMock(), "github_agent", "github", False),
            ),
            patch(
                f"{MODULE}.create_subagent_system_message",
                new_callable=AsyncMock,
                return_value=SimpleNamespace(content="sys"),
            ),
            patch(f"{MODULE}.get_subagent_by_id", return_value=platform),
            # provider metadata present but carries no username/login/handle.
            patch(
                f"{MODULE}.get_provider_metadata",
                new_callable=AsyncMock,
                return_value={"email": "x@y.com"},
            ),
            patch(f"{MODULE}.build_initial_messages", new_callable=AsyncMock, return_value=["m"]),
            patch(f"{MODULE}.build_agent_config", return_value={"configurable": {}}),
            patch(f"{MODULE}.execute_subagent_stream", new=exec_stream),
            patch(f"{MODULE}.get_stream_writer", return_value=MagicMock()),
        ):
            await handoff.coroutine("github", "task", config)

        ctx = exec_stream.await_args.kwargs["ctx"]
        assert ctx.initial_state["integration_usernames"] == {}

    async def test_custom_mcp_metadata_built_from_lookup(self):
        # is_custom True -> integration_metadata is sourced from a second
        # _get_subagent_by_id lookup (icon_url + name), not the platform branch.
        config = {"configurable": {"user_id": "user1", "thread_id": "t1"}}
        custom_meta = {"icon_url": "https://i/c.png", "name": "My Custom"}
        exec_stream = AsyncMock(return_value="ok")
        with (
            patch(
                f"{MODULE}._resolve_subagent",
                new_callable=AsyncMock,
                return_value=(MagicMock(), "custom_mcp_xyz", "xyz", True),
            ),
            patch(
                f"{MODULE}.create_subagent_system_message",
                new_callable=AsyncMock,
                return_value=SimpleNamespace(content="sys"),
            ),
            # Platform lookup (for provider meta) returns None; custom lookup returns the dict.
            patch(f"{MODULE}.get_subagent_by_id", return_value=None),
            patch(
                f"{MODULE}._get_subagent_by_id",
                new_callable=AsyncMock,
                return_value=custom_meta,
            ),
            patch(f"{MODULE}.get_provider_metadata", new_callable=AsyncMock, return_value=None),
            patch(f"{MODULE}.build_initial_messages", new_callable=AsyncMock, return_value=["m"]),
            patch(f"{MODULE}.build_agent_config", return_value={"configurable": {}}),
            patch(f"{MODULE}.execute_subagent_stream", new=exec_stream),
            patch(f"{MODULE}.get_stream_writer", return_value=MagicMock()),
        ):
            await handoff.coroutine("xyz", "task", config)

        meta = exec_stream.await_args.kwargs["integration_metadata"]
        assert meta == {
            "icon_url": "https://i/c.png",
            "integration_id": "xyz",
            "name": "My Custom",
        }

    async def test_platform_metadata_and_stream_result_returned(self):
        config = {"configurable": {"user_id": "user1", "thread_id": "t1"}}
        platform = _make_subagent("gmail", name="Gmail", managed_by="internal", provider="gmail")
        exec_stream = AsyncMock(return_value="final answer")
        with (
            patch(
                f"{MODULE}._resolve_subagent",
                new_callable=AsyncMock,
                return_value=(MagicMock(), "gmail_agent", "gmail", False),
            ),
            patch(
                f"{MODULE}.create_subagent_system_message",
                new_callable=AsyncMock,
                return_value=SimpleNamespace(content="sys"),
            ),
            patch(f"{MODULE}.get_subagent_by_id", return_value=platform),
            patch(
                f"{MODULE}.get_provider_metadata",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(f"{MODULE}.build_initial_messages", new_callable=AsyncMock, return_value=["m"]),
            patch(f"{MODULE}.build_agent_config", return_value={"configurable": {}}),
            patch(f"{MODULE}.execute_subagent_stream", new=exec_stream),
            patch(f"{MODULE}.get_stream_writer", return_value=MagicMock()),
        ):
            result = await handoff.coroutine("gmail", "task", config)

        assert result == "final answer"
        # Platform branch builds integration_metadata from the subagent name + id.
        meta = exec_stream.await_args.kwargs["integration_metadata"]
        assert meta == {"icon_url": None, "integration_id": "gmail", "name": "Gmail"}

    async def test_exception_in_chain_returns_error_wrapper(self):
        config = {"configurable": {"user_id": "user1", "thread_id": "t1"}}
        with patch(
            f"{MODULE}._resolve_subagent",
            new_callable=AsyncMock,
            side_effect=RuntimeError("kaboom"),
        ):
            result = await handoff.coroutine("gmail", "task", config)
        assert result == "Error executing task: kaboom"
