"""Attacks on the gating policy (app/services/hil/policy.py).

Three things decide whether a destructive call runs unattended, and each is attacked:

* the user's mode and per-tool overrides (``resolve_policy`` / ``is_gated``);
* the fail-open in ``_preferences``, which is only safe while HIL is off — it must
  re-raise the moment the default becomes a gating mode;
* ``has_pausing_sibling``, which suppresses auto-approval when a sibling call will
  pause the node — the guard that stopped one send becoming two. A sibling pauses
  either at its own gate or, for ``HIL_PAUSING_TOOLS``, without ever being gated.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.models.hil_models import HILPreferences
from app.services.hil.policy import has_pausing_sibling, is_gated, resolve_policy
from app.services.mcp.langchain_adapter import MCP_ANNOTATIONS_METADATA_KEY

from .conftest import USER_ID, ai_message_with_calls, make_request, make_tool

MODULE = "app.services.hil.policy"


def prefs(mode: str = "always_ask", **overrides: bool) -> HILPreferences:
    return HILPreferences(mode=mode, tool_overrides=overrides)


@pytest.fixture(autouse=True)
def _quiet_log():
    with patch(f"{MODULE}.log"):
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
        self, mode: str, destructive: bool, expected: str
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


class TestPreferencesFailure:
    async def test_an_unreachable_store_fails_open_only_because_hil_is_off(self) -> None:
        # Today HIL_DEFAULT_MODE is always_allow, so a Redis/Mongo blip must not start
        # gating every tool call for the ~100% of users who have HIL off.
        with (
            patch(f"{MODULE}.HIL_DEFAULT_MODE", "always_allow"),
            patch(f"{MODULE}.get_hil_preferences", side_effect=ConnectionError("redis down")),
            patch(f"{MODULE}.is_tool_destructive", new=AsyncMock(return_value=True)),
        ):
            assert await resolve_policy(make_request(), USER_ID, "delete_everything") == "allow"

    async def test_once_the_default_is_a_gating_mode_an_unreachable_store_must_raise(self) -> None:
        # THE launch-safety test. The day HIL_DEFAULT_MODE flips to always_ask, this
        # fail-open becomes "a Redis blip disables the approval gate for everyone".
        # The guard must re-raise so the gate's own fail-closed handler denies the call.
        for gating_mode in ("always_ask", "auto"):
            with (
                patch(f"{MODULE}.HIL_DEFAULT_MODE", gating_mode),
                patch(f"{MODULE}.get_hil_preferences", side_effect=ConnectionError("redis down")),
                pytest.raises(ConnectionError),
            ):
                await resolve_policy(make_request(), USER_ID, "delete_everything")


class TestHasPausingSibling:
    """Auto-approval is only safe when the call is the turn's *only* pausing action.
    A sibling that pauses re-runs the whole node, so anything that already ran runs
    twice — verified in production: one send became two."""

    @pytest.fixture(autouse=True)
    def _unregistered_siblings(self):
        # These tests attack sibling *selection*, not tool resolution, so every
        # sibling resolves to no tool object.
        registry = SimpleNamespace(get_tool_meta=lambda _name: None)
        with patch(f"{MODULE}.get_tool_registry", new=AsyncMock(return_value=registry)):
            yield

    async def test_a_gated_sibling_in_the_same_message_suppresses_auto_approval(self) -> None:
        state_messages = [
            ai_message_with_calls(
                {"id": "call-1", "name": "send_email", "args": {}},
                {"id": "call-2", "name": "delete_file", "args": {}},
            )
        ]
        request = make_request(call_id="call-1", messages=state_messages)
        with (
            patch(f"{MODULE}.get_hil_preferences", new=AsyncMock(return_value=prefs())),
            patch(f"{MODULE}.is_tool_destructive", new=AsyncMock(return_value=True)),
        ):
            assert await has_pausing_sibling(request, USER_ID, "call-1") is True

    async def test_the_pending_call_does_not_count_as_its_own_sibling(self) -> None:
        # Mutation bait: excluding by *name* instead of id would make every gated call
        # look like it had a sibling, and auto mode would never approve anything.
        state_messages = [ai_message_with_calls({"id": "call-1", "name": "send_email", "args": {}})]
        request = make_request(call_id="call-1", messages=state_messages)
        with (
            patch(f"{MODULE}.get_hil_preferences", new=AsyncMock(return_value=prefs())),
            patch(f"{MODULE}.is_tool_destructive", new=AsyncMock(return_value=True)),
        ):
            assert await has_pausing_sibling(request, USER_ID, "call-1") is False

    async def test_an_earlier_call_of_the_same_tool_is_a_real_sibling(self) -> None:
        # Same tool name, different id — two sends in one turn. Both must be confirmed
        # together; excluding by name would let the second auto-run.
        state_messages = [
            ai_message_with_calls(
                {"id": "call-1", "name": "send_email", "args": {"to": "a@x.com"}},
                {"id": "call-2", "name": "send_email", "args": {"to": "b@x.com"}},
            )
        ]
        request = make_request(call_id="call-2", messages=state_messages)
        with (
            patch(f"{MODULE}.get_hil_preferences", new=AsyncMock(return_value=prefs())),
            patch(f"{MODULE}.is_tool_destructive", new=AsyncMock(return_value=True)),
        ):
            assert await has_pausing_sibling(request, USER_ID, "call-2") is True

    async def test_an_exempt_sibling_does_not_suppress_auto_approval(self) -> None:
        state_messages = [
            ai_message_with_calls(
                {"id": "call-1", "name": "send_email", "args": {}},
                {"id": "call-2", "name": "search_memory", "args": {}},
            )
        ]
        request = make_request(call_id="call-1", messages=state_messages)
        with (
            patch(f"{MODULE}.get_hil_preferences", new=AsyncMock(return_value=prefs())),
            patch(f"{MODULE}.is_tool_destructive", new=AsyncMock(return_value=True)),
        ):
            assert await has_pausing_sibling(request, USER_ID, "call-1") is False

    async def test_an_unclassifiable_sibling_suppresses_auto_approval(self) -> None:
        # Fail closed: an unknown sibling might pause, so the pending call must not
        # auto-run and risk the double-execution. The registry is broken here — the REAL
        # classifier runs, so this exercises the whole fail-closed chain rather than a
        # mocked-in verdict.
        state_messages = [
            ai_message_with_calls(
                {"id": "call-1", "name": "send_email", "args": {}},
                {"id": "call-2", "name": "mystery_tool", "args": {}},
            )
        ]
        request = make_request(call_id="call-1", messages=state_messages)
        with (
            patch(f"{MODULE}.get_hil_preferences", new=AsyncMock(return_value=prefs())),
            patch(
                "app.services.hil.classification.get_tool_registry",
                side_effect=ConnectionError("chroma down"),
            ),
            patch("app.services.hil.classification.log"),
        ):
            assert await has_pausing_sibling(request, USER_ID, "call-1") is True

    async def test_a_sibling_is_classified_with_its_own_tool_object(self) -> None:
        # The regression: resolving a sibling by bare name loses its MCP
        # destructiveHint, so a tool its OWN gate will pause on looks safe here —
        # the pending call auto-runs and then executes twice when the node re-runs
        # on resume. The classifier below calls the sibling safe, so the only thing
        # that can gate it is the hint on the tool object itself.
        sibling = make_tool(
            name="mcp_wipe",
            description="Tidy up the workspace.",
            metadata={MCP_ANNOTATIONS_METADATA_KEY: {"destructiveHint": True}},
        )
        state_messages = [
            ai_message_with_calls(
                {"id": "call-1", "name": "send_email", "args": {}},
                {"id": "call-2", "name": "mcp_wipe", "args": {}},
            )
        ]
        request = make_request(call_id="call-1", messages=state_messages)
        registry = SimpleNamespace(
            get_tool_meta=lambda name: (
                SimpleNamespace(tool=sibling) if name == "mcp_wipe" else None
            ),
            is_tool_destructive=lambda _name: None,
            mark_tool_destructive=lambda *_: None,
        )
        with (
            patch(f"{MODULE}.get_hil_preferences", new=AsyncMock(return_value=prefs())),
            patch(f"{MODULE}.get_tool_registry", new=AsyncMock(return_value=registry)),
            patch(
                "app.services.hil.classification.get_tool_registry",
                new=AsyncMock(return_value=registry),
            ),
            patch(
                "app.services.hil.classification._classify_unknown_tool",
                new=AsyncMock(return_value=False),
            ),
        ):
            assert await has_pausing_sibling(request, USER_ID, "call-1") is True

    async def test_a_safe_sibling_does_not_suppress_auto_approval(self) -> None:
        state_messages = [
            ai_message_with_calls(
                {"id": "call-1", "name": "send_email", "args": {}},
                {"id": "call-2", "name": "list_files", "args": {}},
            )
        ]
        request = make_request(call_id="call-1", messages=state_messages)

        async def classify(name: str, *_: object, **__: object) -> bool:
            return name != "list_files"

        with (
            patch(f"{MODULE}.get_hil_preferences", new=AsyncMock(return_value=prefs())),
            patch(f"{MODULE}.is_tool_destructive", side_effect=classify),
        ):
            assert await has_pausing_sibling(request, USER_ID, "call-1") is False
