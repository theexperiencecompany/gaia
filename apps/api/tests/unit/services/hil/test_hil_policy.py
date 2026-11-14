"""Attacks on the gating policy (app/services/hil/policy.py).

Three things decide whether a destructive call runs unattended, and each is attacked:

* the user's mode and per-tool overrides (resolve_policy / is_gated);
* the fail-open in _preferences, which is only safe while HIL is off — it must
  re-raise the moment the default becomes a gating mode;
* has_pausing_sibling, which suppresses auto-approval when a sibling call will
  pause the node — the guard that stopped one send becoming two. A sibling pauses
  either at its own gate or, for HIL_PAUSING_TOOLS, without ever being gated.
"""

from dataclasses import replace
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, patch

from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolCall
from langchain_core.tools import BaseTool
import pytest

from app.constants.execute import EXECUTE_TOOL_NAME
from app.models.hil_models import HILMode, HILPreferences
from app.services.hil.policy import (
    gated_tool_key,
    gated_tool_object,
    is_gated,
    resolve_policy,
)
from app.services.mcp.langchain_adapter import MCP_ANNOTATIONS_METADATA_KEY

from .conftest import (
    USER_ID,
    make_request,
    make_tool,
    resolver_returning,
)

MODULE = "app.services.hil.policy"


def prefs(mode: HILMode = "always_ask", **overrides: bool) -> HILPreferences:
    return HILPreferences(mode=mode, tool_overrides=overrides)


def _proxied(real_name: str, proxy: BaseTool | None = None) -> ToolCallRequest:
    return make_request(
        name=EXECUTE_TOOL_NAME,
        args={"tool_name": real_name, "data": {}},
        tool=proxy or make_tool(name=EXECUTE_TOOL_NAME, description="Run any tool."),
    )


_HINTED = {MCP_ANNOTATIONS_METADATA_KEY: {"destructiveHint": True}}


@pytest.fixture(autouse=True)
def _quiet_log():
    with patch(f"{MODULE}.log"):
        yield


@pytest.fixture(autouse=True)
def _registry_without_stamps():
    """Default registry where every tool looks up as unregistered (meta None → never always-gated); tests exercising the stamp patch get_tool_registry themselves."""
    with patch(
        f"{MODULE}.get_tool_registry",
        new=AsyncMock(return_value=SimpleNamespace(get_tool_meta=lambda name: None)),
    ):
        yield


class TestResolvePolicy:
    @pytest.mark.parametrize(
        ("mode", "destructive", "expected"),
        [
            ("always_allow", True, "allow"),  # HIL off — nothing gates, even a wipe
            ("always_ask", True, "ask"),
            ("always_ask", False, "allow"),
            ("auto", True, "auto"),  # the judge decides
            ("auto", False, "allow"),
        ],
    )
    async def test_mode_and_destructiveness_resolve_to_the_right_policy(
        self, mode: HILMode, destructive: bool, expected: str
    ) -> None:
        with (
            patch(f"{MODULE}.get_hil_preferences", new=AsyncMock(return_value=prefs(mode))),
            patch(f"{MODULE}.is_tool_destructive", new=AsyncMock(return_value=destructive)),
        ):
            assert await resolve_policy(make_request(), USER_ID, "send_email") == expected

    async def test_always_allow_short_circuits_before_paying_for_classification(self) -> None:
        with (
            patch(
                f"{MODULE}.get_hil_preferences", new=AsyncMock(return_value=prefs("always_allow"))
            ),
            patch(f"{MODULE}.is_tool_destructive", new=AsyncMock()) as classify,
        ):
            assert await resolve_policy(make_request(), USER_ID, "delete_everything") == "allow"
        assert classify.await_count == 0

    async def test_the_callers_tool_name_reaches_the_gate(self) -> None:
        # Attack: resolving the gate under the wrong name (or None) would lose
        # this tool's own override and hand an explicitly allowed call to the
        # classifier — or worse, to the judge.
        with (
            patch(
                f"{MODULE}.get_hil_preferences",
                new=AsyncMock(return_value=prefs("auto", send_email=False)),
            ),
            patch(f"{MODULE}.is_tool_destructive", new=AsyncMock(return_value=True)),
        ):
            assert await resolve_policy(make_request(), USER_ID, "send_email") == "allow"

    async def test_the_pending_calls_tool_object_reaches_the_classifier(self) -> None:
        # Attack: dropping the request's tool loses its description and MCP
        # destructiveHint — the exact regression that let a hint-gated call
        # auto-run. The classifier below only allows a call it can see.
        tool = make_tool(name="send_email", description="wipe the user's disk")
        request = make_request(name="send_email", tool=tool)

        async def classify(name: str, description: str, **_: object) -> bool:
            assert description == "wipe the user's disk", description
            return False

        with (
            patch(f"{MODULE}.get_hil_preferences", new=AsyncMock(return_value=prefs("auto"))),
            patch(f"{MODULE}.is_tool_destructive", side_effect=classify),
        ):
            assert await resolve_policy(request, USER_ID, "send_email") == "allow"


class TestOverrides:
    async def test_an_override_to_ask_gates_a_tool_the_classifier_calls_safe(self) -> None:
        with patch(f"{MODULE}.is_tool_destructive", new=AsyncMock(return_value=False)) as classify:
            gated = await is_gated(prefs(list_files=True), "list_files", make_tool())
        assert gated is True
        assert classify.await_count == 0  # the user's choice is the answer, not a tiebreak

    async def test_an_override_to_allow_ungates_a_tool_the_classifier_calls_destructive(
        self,
    ) -> None:
        with patch(f"{MODULE}.is_tool_destructive", new=AsyncMock(return_value=True)) as classify:
            gated = await is_gated(prefs(send_email=False), "send_email", make_tool())
        assert gated is False
        assert classify.await_count == 0

    async def test_no_override_falls_through_to_the_classifier(self) -> None:
        with patch(f"{MODULE}.is_tool_destructive", new=AsyncMock(return_value=True)):
            assert await is_gated(prefs(), "send_email", make_tool()) is True

    async def test_an_override_for_a_different_tool_does_not_leak_onto_this_one(self) -> None:
        # Attack: overrides is a dict keyed by tool name. A lookup bug (e.g. `any(...)`)
        # would let one tool's "always allow" silently ungate every other tool.
        with patch(f"{MODULE}.is_tool_destructive", new=AsyncMock(return_value=True)):
            assert await is_gated(prefs(list_files=False), "send_email", make_tool()) is True


def _mcp_tool(name: str, *, integration_id: str, server_name: str | None = None) -> BaseTool:
    return make_tool(
        name=name,
        metadata={"integration_id": integration_id, "mcp_server_name": server_name or name},
    )


class TestScopedOverrides:
    """MCP overrides are keyed per server on the server's own tool name."""

    async def test_an_override_on_one_server_does_not_apply_to_the_same_name_on_another(
        self,
    ) -> None:
        overrides = HILPreferences(
            mode="always_ask", tool_overrides={"mcp:srv_a:delete_item": False}
        )
        with patch(f"{MODULE}.is_tool_destructive", new=AsyncMock(return_value=True)):
            on_a = await is_gated(
                overrides, "delete_item", _mcp_tool("delete_item", integration_id="srv_a")
            )
            on_b = await is_gated(
                overrides, "delete_item", _mcp_tool("delete_item", integration_id="srv_b")
            )
        assert on_a is False
        assert on_b is True

    async def test_the_override_survives_a_collision_rename(self) -> None:
        overrides = HILPreferences(
            mode="always_ask", tool_overrides={"mcp:srv_a:delete_item": False}
        )
        renamed = _mcp_tool(
            "posthog_delete_item", integration_id="srv_a", server_name="delete_item"
        )
        with patch(f"{MODULE}.is_tool_destructive", new=AsyncMock(return_value=True)):
            assert await is_gated(overrides, "posthog_delete_item", renamed) is False

    async def test_a_bare_name_override_does_not_reach_an_mcp_tool_of_that_name(self) -> None:
        with patch(f"{MODULE}.is_tool_destructive", new=AsyncMock(return_value=True)):
            gated = await is_gated(
                prefs(delete_item=False),
                "delete_item",
                _mcp_tool("delete_item", integration_id="srv_a"),
            )
        assert gated is True

    async def test_a_registry_tool_override_is_still_keyed_by_its_bare_name(self) -> None:
        with patch(f"{MODULE}.is_tool_destructive", new=AsyncMock(return_value=True)):
            gated = await is_gated(prefs(GMAIL_SEND_EMAIL=False), "GMAIL_SEND_EMAIL", make_tool())
        assert gated is False


class TestPreferencesFailure:
    @pytest.mark.regression
    async def test_an_unreadable_store_asks_for_a_destructive_call(self) -> None:
        """Regression: an owner whose preferences could not load ran every tool as always_allow."""
        with (
            patch(f"{MODULE}.get_hil_preferences", side_effect=ConnectionError("redis down")),
            patch(f"{MODULE}.is_tool_destructive", new=AsyncMock(return_value=True)),
        ):
            assert await resolve_policy(make_request(), USER_ID, "delete_everything") == "ask"

    async def test_an_unreadable_store_still_lets_a_harmless_call_through(self) -> None:
        with (
            patch(f"{MODULE}.get_hil_preferences", side_effect=ConnectionError("redis down")),
            patch(f"{MODULE}.is_tool_destructive", new=AsyncMock(return_value=False)),
        ):
            assert await resolve_policy(make_request(), USER_ID, "list_todos") == "allow"

    @pytest.mark.regression
    async def test_the_failure_is_logged_as_a_warning_with_its_reason(self) -> None:
        with (
            patch(f"{MODULE}.get_hil_preferences", side_effect=ConnectionError("redis down")),
            patch(f"{MODULE}.is_tool_destructive", new=AsyncMock(return_value=True)),
            patch(f"{MODULE}.log") as log_mock,
        ):
            await resolve_policy(make_request(), USER_ID, "delete_everything")

        log_mock.error.assert_not_called()
        (fields,) = [
            c.kwargs for c in log_mock.warning.call_args_list if "Preferences" in c.args[0]
        ]
        assert fields["error_type"] == "ConnectionError"
        assert fields["error"] == "redis down"
        assert fields["user_id"] == USER_ID


class TestAlwaysGate:
    """The registry's forced-ask stamp: product invariants outrank preferences."""

    def meta(self, always_gate: bool):
        return SimpleNamespace(always_gate=always_gate)

    async def test_forced_ask_wins_over_every_mode_without_reading_preferences(self) -> None:
        # The check runs BEFORE the preference lookup, so a dead preference
        # store cannot wave an account mutation through. The stamp is looked up
        # by the call's own name — a lookup under any other name finds nothing.
        with (
            patch(
                f"{MODULE}.get_tool_registry",
                new=AsyncMock(
                    return_value=SimpleNamespace(
                        get_tool_meta=lambda name: (
                            self.meta(True) if name == "update_preferences" else None
                        )
                    )
                ),
            ),
            patch(
                f"{MODULE}._preferences",
                new=AsyncMock(side_effect=AssertionError("must not read prefs")),
            ) as prefs_read,
            patch(
                f"{MODULE}.get_hil_preferences", new=AsyncMock(return_value=prefs("always_allow"))
            ),
        ):
            assert await resolve_policy(make_request(), USER_ID, "update_preferences") == "ask"
        prefs_read.assert_not_awaited()

    async def test_per_tool_allow_override_does_not_bypass_the_stamp(self) -> None:
        tool = make_tool(name="update_preferences")
        with patch(
            f"{MODULE}.get_tool_registry",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    get_tool_meta=lambda name: (
                        self.meta(True) if name == "update_preferences" else None
                    )
                )
            ),
        ):
            assert (
                await is_gated(
                    prefs("always_ask", update_preferences=False), "update_preferences", tool
                )
                is True
            )

    async def test_ungated_tools_are_unaffected_by_the_stamp_path(self) -> None:
        tool = make_tool(name="web_search")
        with (
            patch(
                f"{MODULE}.get_tool_registry",
                new=AsyncMock(
                    return_value=SimpleNamespace(get_tool_meta=lambda name: self.meta(False))
                ),
            ),
            patch(f"{MODULE}.is_tool_destructive", new=AsyncMock(return_value=False)),
        ):
            assert await is_gated(prefs(), "web_search", tool) is False

    async def test_an_unreachable_registry_still_asks_for_the_users_gated_tool(self) -> None:
        # THE regression: the stamp read sits ahead of everything, so raising out of it
        # took the WHOLE gate down (fails closed by DENYING) — a missing tool_registry
        # provider refused every gated call outright. The stamp is an escalation; the rest of the policy must still run when it can't be read.
        with (
            patch(
                f"{MODULE}.get_tool_registry",
                new=AsyncMock(side_effect=KeyError("Provider 'tool_registry' not found")),
            ),
            patch(
                f"{MODULE}.get_hil_preferences",
                new=AsyncMock(return_value=prefs("always_ask", SEND_GMAIL=True)),
            ),
        ):
            assert await resolve_policy(make_request(), USER_ID, "SEND_GMAIL") == "ask"

    async def test_an_unreachable_registry_reads_no_stamp_so_the_user_still_decides(self) -> None:
        # The other half of the escalation contract: unreadable means "no stamp",
        # never "ask". Failing closed here would gate a call the user has HIL
        # switched off for — a registry blip must not start prompting everyone.
        with (
            patch(
                f"{MODULE}.get_tool_registry",
                new=AsyncMock(side_effect=KeyError("Provider 'tool_registry' not found")),
            ),
            patch(
                f"{MODULE}.get_hil_preferences",
                new=AsyncMock(return_value=prefs("always_allow")),
            ),
        ):
            assert await resolve_policy(make_request(), USER_ID, "SEND_GMAIL") == "allow"

    async def test_the_unreachable_registry_is_reported_with_the_failure_it_hit(self) -> None:
        # The warning has to carry WHICH failure it was — a bare "registry unavailable"
        # line cannot tell a missing provider apart from a dead Chroma.
        with (
            patch(f"{MODULE}.log") as logger,
            patch(
                f"{MODULE}.get_tool_registry",
                new=AsyncMock(side_effect=KeyError("Provider 'tool_registry' not found")),
            ),
            patch(
                f"{MODULE}.get_hil_preferences",
                new=AsyncMock(return_value=prefs("always_allow")),
            ),
        ):
            assert await resolve_policy(make_request(), USER_ID, "SEND_GMAIL") == "allow"

        logger.warning.assert_called_once()
        message, fields = logger.warning.call_args.args, logger.warning.call_args.kwargs
        assert len(message) == 1 and "tool registry unavailable" in message[0]
        assert "Provider 'tool_registry' not found" in fields["error"]
        assert fields["error_type"] == "KeyError"


class TestArgumentGate:
    """manage_linked_account: disconnect confirms; generate_link does not."""

    def registry_with_stamp(self, always_gate: bool = False):
        return AsyncMock(
            return_value=SimpleNamespace(
                get_tool_meta=lambda name: SimpleNamespace(always_gate=always_gate)
            )
        )

    async def test_disconnect_always_asks_regardless_of_mode(self) -> None:
        request = make_request(
            name="manage_linked_account", args={"platform": "slack", "action": "disconnect"}
        )
        with (
            patch(f"{MODULE}.get_tool_registry", new=self.registry_with_stamp()),
            patch(
                f"{MODULE}._preferences",
                new=AsyncMock(side_effect=AssertionError("must not read prefs")),
            ),
        ):
            assert await resolve_policy(request, USER_ID, "manage_linked_account") == "ask"

    async def test_generate_link_falls_through_to_normal_resolution(self) -> None:
        request = make_request(
            name="manage_linked_account", args={"platform": "slack", "action": "generate_link"}
        )
        with (
            patch(f"{MODULE}.get_tool_registry", new=self.registry_with_stamp()),
            patch(
                f"{MODULE}.get_hil_preferences", new=AsyncMock(return_value=prefs("always_allow"))
            ),
        ):
            assert await resolve_policy(request, USER_ID, "manage_linked_account") == "allow"

    async def test_is_gated_honors_the_argument_gate_on_its_own(self) -> None:
        # Direct gate checks (e.g. a sibling scan) must hit on the call's own
        # name and args — not on None standing in for either. The classifier is
        # pinned safe so the ONLY thing that can gate here is the argument gate.
        with (
            patch(f"{MODULE}.get_tool_registry", new=self.registry_with_stamp()),
            patch(f"{MODULE}.is_tool_destructive", new=AsyncMock(return_value=False)),
        ):
            assert (
                await is_gated(
                    prefs(), "manage_linked_account", None, args={"action": "disconnect"}
                )
                is True
            )


class TestTheRealToolBehindACall:
    """Classification reads the tool that will actually run, resolved for the caller."""

    async def test_a_direct_call_reads_the_requests_own_tool(self) -> None:
        own = make_tool(name="send_email", description="Send.")
        request = make_request(name="send_email", tool=own)
        with patch(f"{MODULE}.resolve_tool", new=resolver_returning()) as resolve:
            assert await gated_tool_object(request, USER_ID, "send_email") is own
        resolve.assert_not_awaited()

    async def test_an_object_shaped_direct_call_reads_the_requests_own_tool(self) -> None:
        own = make_tool(name="send_email", description="Send.")
        shaped = cast(ToolCall, SimpleNamespace(name="send_email", id="call-1", args={}))
        request = replace(make_request(tool=own), tool_call=shaped)
        with patch(f"{MODULE}.resolve_tool", new=resolver_returning()):
            assert await gated_tool_object(request, USER_ID, "send_email") is own

    async def test_a_proxied_call_resolves_the_real_tool_for_this_user(self) -> None:
        real = make_tool(name="mcp_wipe", description="Wipe.")
        with patch(f"{MODULE}.resolve_tool", new=resolver_returning(real)):
            assert await gated_tool_object(_proxied("mcp_wipe"), USER_ID, "mcp_wipe") is real

    async def test_a_failed_resolution_is_reported_and_reads_as_no_tool(self) -> None:
        with (
            patch(f"{MODULE}.resolve_tool", new=AsyncMock(side_effect=RuntimeError("mcp down"))),
            patch(f"{MODULE}.log") as log,
        ):
            assert await gated_tool_object(_proxied("mcp_wipe"), USER_ID, "mcp_wipe") is None

        log.warning.assert_called_once()
        assert "tool resolution failed; classifying by name alone" in log.warning.call_args.args[0]
        assert log.warning.call_args.kwargs == {
            "tool_name": "mcp_wipe",
            "error": "mcp down",
            "error_type": "RuntimeError",
        }

    async def test_a_registry_tools_key_is_its_bare_name(self) -> None:
        request = make_request(name="send_email", tool=make_tool(name="send_email"))
        with patch(f"{MODULE}.resolve_tool", new=resolver_returning()):
            assert await gated_tool_key(request, USER_ID, "send_email") == "send_email"

    async def test_a_proxied_mcp_tools_key_is_scoped_to_its_server(self) -> None:
        real = _mcp_tool("posthog_delete_item", integration_id="srv_a", server_name="delete_item")
        with patch(f"{MODULE}.resolve_tool", new=resolver_returning(real)):
            key = await gated_tool_key(
                _proxied("posthog_delete_item"), USER_ID, "posthog_delete_item"
            )
        assert key == "mcp:srv_a:delete_item"

    async def test_a_proxied_calls_real_hint_gates_it(self) -> None:
        real = make_tool(name="mcp_wipe", description="Tidy up.", metadata=_HINTED)
        registry = SimpleNamespace(
            get_tool_meta=lambda _name: None,
            is_tool_destructive=lambda _name: None,
            mark_tool_destructive=lambda *_: None,
        )
        with (
            patch(f"{MODULE}.get_hil_preferences", new=AsyncMock(return_value=prefs())),
            patch(f"{MODULE}.resolve_tool", new=resolver_returning(real)),
            patch(
                "app.services.hil.classification.get_tool_registry",
                new=AsyncMock(return_value=registry),
            ),
            patch(
                "app.services.hil.classification._classify_unknown_tool",
                new=AsyncMock(return_value=False),
            ),
        ):
            assert await resolve_policy(_proxied("mcp_wipe"), USER_ID, "mcp_wipe") == "ask"
