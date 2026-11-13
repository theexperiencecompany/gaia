"""Regressions for bugs found reviewing the HIL branch. Each test names the bug it pins.

These are the ones a passing suite did not catch, so each is written against the *shape*
of the mistake rather than the fix: an orchestration tool that fell through to the
destructive classifier, and a pausing sibling that cost a gated call its auto-approval.
"""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import ToolMessage
import pytest

from app.constants.hil import HIL_EXEMPT_TOOLS, HIL_PAUSING_TOOLS
from app.services.hil.policy import has_pausing_sibling

from .conftest import USER_ID, ai_message_with_calls, make_request, run_through_gate

GATE = "app.services.hil.gate"
POLICY = "app.services.hil.policy"


class TestExemptToolsAreNeverGated:
    """The join tool is gone, but the regression coverage stays: HIL_EXEMPT_TOOLS must keep covering every bound orchestration tool, or the gate sends one to the LLM destructive classifier, which fails CLOSED."""

    def test_the_join_tool_is_exempt(self) -> None:
        assert "spawn_subagent" in HIL_EXEMPT_TOOLS

    async def test_the_gate_runs_it_without_resolving_any_policy(self) -> None:
        ran = False

        async def handler(_request: Any) -> ToolMessage:
            nonlocal ran
            ran = True
            return ToolMessage(content="collected", tool_call_id="call-1")

        with patch(f"{GATE}.resolve_policy", new=AsyncMock()) as policy:
            result = await run_through_gate(make_request(name="spawn_subagent"), handler)

        assert ran is True
        assert result.content == "collected"
        policy.assert_not_awaited()

    def test_every_orchestration_tool_that_can_pause_is_also_exempt(self) -> None:
        # A pausing tool that is NOT exempt would be classified, and a fail-closed verdict
        # would gate it — which is the bug above, in whichever tool joins the set next.
        assert HIL_PAUSING_TOOLS <= HIL_EXEMPT_TOOLS


class TestExemptSiblingsThatPauseSuppressAutoApproval:
    """Bug: the sibling guard skipped every exempt tool, but spawn_subagent is exempt AND can pause.

    A gated tool sharing a message with one of them auto-ran, then ran a SECOND time when the pause
    re-ran the whole node.
    """

    @pytest.fixture(autouse=True)
    def _registry(self):
        registry = SimpleNamespace(get_tool_meta=lambda _name: None)
        with (
            patch(f"{POLICY}.log"),
            patch(f"{POLICY}.get_tool_registry", new=AsyncMock(return_value=registry)),
            patch(
                f"{POLICY}.get_hil_preferences",
                new=AsyncMock(return_value=MagicMock(tool_overrides={})),
            ),
            patch(f"{POLICY}.is_tool_destructive", new=AsyncMock(return_value=False)),
        ):
            yield

    @pytest.mark.parametrize("pausing_tool", sorted(HIL_PAUSING_TOOLS))
    async def test_a_pausing_sibling_blocks_auto_approval(self, pausing_tool: str) -> None:
        request = make_request(
            call_id="call-1",
            messages=[
                ai_message_with_calls(
                    {"id": "call-1", "name": "send_email", "args": {}},
                    {"id": "call-2", "name": pausing_tool, "args": {"background": False}},
                )
            ],
        )

        assert await has_pausing_sibling(request, USER_ID, "call-1") is True

    @pytest.mark.parametrize("delegation_tool", sorted(HIL_PAUSING_TOOLS))
    async def test_a_background_delegation_sibling_does_not_block(
        self, delegation_tool: str
    ) -> None:
        # A background run parks on its own thread and never re-runs this node, so it
        # must not cost the gated sibling its auto-approval.
        request = make_request(
            call_id="call-1",
            messages=[
                ai_message_with_calls(
                    {"id": "call-1", "name": "send_email", "args": {}},
                    {"id": "call-2", "name": delegation_tool, "args": {}},
                )
            ],
        )

        assert await has_pausing_sibling(request, USER_ID, "call-1") is False

    async def test_a_harmless_exempt_sibling_still_does_not_block(self) -> None:
        # The fix must not degrade into "any exempt sibling blocks", which would disable
        # auto mode for every turn that also searched memory.
        request = make_request(
            call_id="call-1",
            messages=[
                ai_message_with_calls(
                    {"id": "call-1", "name": "send_email", "args": {}},
                    {"id": "call-2", "name": "search_memory", "args": {}},
                )
            ],
        )

        assert await has_pausing_sibling(request, USER_ID, "call-1") is False
