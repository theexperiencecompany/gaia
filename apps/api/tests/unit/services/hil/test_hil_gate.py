"""Attacks on the approval gate (app/services/hil/gate.py).

The gate is the last thing between a model's tool call and the real world. The attacks
that matter are the ones that make the tool *run* when it should not have:

* a malformed resume payload read as an approval;
* a gate that fails open when its own decision I/O breaks;
* a run whose identity is missing, so nothing gates it at all.
"""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from langchain_core.messages import ToolMessage
from langgraph.errors import GraphInterrupt
import pytest

from app.constants.hil import HIL_STATUS_KWARG
from app.services.hil.gate import (
    _integration_name_for,
    read_gate_context,
)

from .conftest import (
    CONVERSATION_ID,
    STREAM_ID,
    USER_ID,
    GateSeams,
    make_request,
    make_tool,
    run_through_gate,
)

MODULE = "app.services.hil.gate"


@pytest.fixture(autouse=True)
def _quiet_log():
    with patch(f"{MODULE}.log"):
        yield


class _Handler:
    """Stands in for the real tool, recording only whether the gate let it run."""

    def __init__(self) -> None:
        self.ran = False

    async def __call__(self, request: Any) -> ToolMessage:
        self.ran = True
        return ToolMessage(content="the tool really ran", tool_call_id="call-1")


class TestGateContext:
    @pytest.mark.parametrize("missing", ["stream_id", "user_id", "conversation_id"])
    def test_a_run_missing_any_identity_field_cannot_be_gated(self, missing: str) -> None:
        configurable = {
            "stream_id": STREAM_ID,
            "user_id": USER_ID,
            "conversation_id": CONVERSATION_ID,
        }
        del configurable[missing]
        assert read_gate_context(make_request(configurable=configurable)) is None

    def test_a_background_run_is_identified_but_not_pausable(self) -> None:
        # No live client to approve, but it is NOT discarded: a gated call here must be
        # failed closed by the gate, not silently allowed. So it is returned, unpausable.
        request = make_request(
            configurable={
                "stream_id": STREAM_ID,
                "user_id": USER_ID,
                "conversation_id": CONVERSATION_ID,
                "execution_mode": "background",
            }
        )
        context = read_gate_context(request)
        assert context is not None
        assert context.pausable is False

    def test_an_interactive_run_is_pausable(self) -> None:
        request = make_request(
            configurable={
                "stream_id": STREAM_ID,
                "user_id": USER_ID,
                "conversation_id": CONVERSATION_ID,
            }
        )
        context = read_gate_context(request)
        assert context is not None
        assert context.pausable is True

    def test_an_empty_string_identity_is_treated_as_missing(self) -> None:
        request = make_request(
            configurable={"stream_id": "", "user_id": USER_ID, "conversation_id": CONVERSATION_ID}
        )
        assert read_gate_context(request) is None

    def test_conversation_id_is_read_rather_than_thread_id(self) -> None:
        # Inside the executor, thread_id is "executor_<conv>". Filing the approval under
        # it would put the card on a conversation the client never polls — the user would
        # never see it, and the run would hang to timeout.
        request = make_request(
            configurable={
                "stream_id": STREAM_ID,
                "user_id": USER_ID,
                "conversation_id": CONVERSATION_ID,
                "thread_id": f"executor_{CONVERSATION_ID}",
            }
        )
        context = read_gate_context(request)
        assert context is not None
        assert context.conversation_id == CONVERSATION_ID

    @pytest.mark.parametrize("raw", ["not a list", None, 42, {"a": 1}])
    def test_malformed_user_messages_degrade_to_no_turns(self, raw: Any) -> None:
        # No turns → the judge cannot ground anything → it asks. Never a crash.
        request = make_request(
            configurable={
                "stream_id": STREAM_ID,
                "user_id": USER_ID,
                "conversation_id": CONVERSATION_ID,
                "user_messages": raw,
            }
        )
        context = read_gate_context(request)
        assert context is not None
        assert context.user_messages == []

    def test_non_string_turns_are_dropped_rather_than_crashing_the_judge(self) -> None:
        request = make_request(
            configurable={
                "stream_id": STREAM_ID,
                "user_id": USER_ID,
                "conversation_id": CONVERSATION_ID,
                "user_messages": ["send it", None, 42, {"role": "user"}, "to bob"],
            }
        )
        context = read_gate_context(request)
        assert context is not None
        assert context.user_messages == ["send it", "to bob"]


class TestGateFailsClosed:
    async def test_a_broken_policy_check_denies_instead_of_running_the_tool(self) -> None:
        # Attack: Redis/Mongo/registry falls over mid-run. The tool MUST NOT run.
        handler = _Handler()
        with patch(f"{MODULE}.resolve_policy", side_effect=ConnectionError("mongo down")):
            result = await run_through_gate(make_request(), handler)

        assert handler.ran is False
        assert isinstance(result, ToolMessage)
        assert result.additional_kwargs[HIL_STATUS_KWARG] == "error"

    async def test_a_broken_publish_denies_instead_of_running_the_tool(
        self, gate_seams: GateSeams
    ) -> None:
        # If the user can't be shown the card, the call must not proceed unseen.
        handler = _Handler()
        gate_seams.publish_ledger.side_effect = RuntimeError("redis down")
        with patch(f"{MODULE}._integration_name_for", new=AsyncMock(return_value=None)):
            result = await run_through_gate(make_request(), handler)

        assert handler.ran is False
        assert isinstance(result, ToolMessage)
        assert result.additional_kwargs[HIL_STATUS_KWARG] == "error"

    async def test_graph_control_flow_is_never_swallowed_by_the_fail_closed_handler(
        self, gate_seams: GateSeams
    ) -> None:
        # GraphBubbleUp is control flow, not an error: the broad `except` must re-raise it.
        handler = _Handler()
        gate_seams.publish_ledger.side_effect = GraphInterrupt(())
        with (
            patch(f"{MODULE}._integration_name_for", new=AsyncMock(return_value=None)),
            pytest.raises(GraphInterrupt),
        ):
            await run_through_gate(make_request(), handler)

        assert handler.ran is False

    async def test_a_tools_own_failure_is_not_converted_into_a_gate_denial(self) -> None:
        # The tool ran and blew up. That is a tool error, and the model must see it as
        # one — not as "the gate denied you", which would send the agent down the wrong
        # recovery path.
        async def exploding_handler(_: Any) -> ToolMessage:
            raise ValueError("the API rejected the request")

        with patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="allow")):
            with pytest.raises(ValueError, match="the API rejected the request"):
                await run_through_gate(make_request(), exploding_handler)


class TestGateBypasses:
    async def test_an_exempt_tool_runs_without_any_gate_check(self) -> None:
        handler = _Handler()
        with patch(f"{MODULE}.resolve_policy", new=AsyncMock()) as policy:
            result = await run_through_gate(make_request(name="call_executor"), handler)

        assert handler.ran is True
        assert result.content == "the tool really ran"
        assert policy.await_count == 0

    async def test_an_ungateable_run_executes_the_tool(self) -> None:
        # A background/queued run has nobody to ask. It runs — by design.
        handler = _Handler()
        with patch(f"{MODULE}.resolve_policy", new=AsyncMock()) as policy:
            await run_through_gate(make_request(configurable={}), handler)

        assert handler.ran is True
        assert policy.await_count == 0

    async def test_an_allowed_policy_runs_the_tool(self) -> None:
        handler = _Handler()
        with patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="allow")):
            await run_through_gate(make_request(), handler)
        assert handler.ran is True


class TestTheApprovalCardNamesTheIntegration:
    """A registry tool names its category; an MCP tool, which has none, names its server."""

    @staticmethod
    def _registry(category_name: str | None) -> SimpleNamespace:
        return SimpleNamespace(
            get_category_of_tool=lambda _name: "cat",
            get_category=lambda _category: (
                SimpleNamespace(integration_name=category_name) if category_name else None
            ),
        )

    async def test_a_registry_tool_names_its_category_without_resolving_the_tool(self) -> None:
        with (
            patch(
                f"{MODULE}.get_tool_registry", new=AsyncMock(return_value=self._registry("Gmail"))
            ),
            patch(f"{MODULE}.gated_tool_object", new=AsyncMock()) as gated,
        ):
            name = await _integration_name_for(make_request(), USER_ID, "GMAIL_SEND_EMAIL")
        assert name == "Gmail"
        gated.assert_not_awaited()

    async def test_an_mcp_tool_names_the_integration_stamped_on_it(self) -> None:
        tool = make_tool(
            name="delete_item",
            metadata={"integration_id": "custom_srv", "mcp_server_name": "delete_item"},
        )
        request = make_request(name="delete_item")
        with (
            patch(f"{MODULE}.get_tool_registry", new=AsyncMock(return_value=self._registry(None))),
            patch(f"{MODULE}.gated_tool_object", new=AsyncMock(return_value=tool)) as gated,
            patch(
                f"{MODULE}.IntegrationResolver.resolve",
                new=AsyncMock(return_value=SimpleNamespace(name="Acme Tracker")),
            ) as resolve,
        ):
            name = await _integration_name_for(request, USER_ID, "delete_item")
        assert name == "Acme Tracker"
        gated.assert_awaited_once_with(request, USER_ID, "delete_item")
        resolve.assert_awaited_once_with("custom_srv")

    async def test_an_unresolvable_integration_still_names_its_id(self) -> None:
        tool = make_tool(
            name="delete_item",
            metadata={"integration_id": "gone_srv", "mcp_server_name": "delete_item"},
        )
        with (
            patch(f"{MODULE}.get_tool_registry", new=AsyncMock(return_value=self._registry(None))),
            patch(f"{MODULE}.gated_tool_object", new=AsyncMock(return_value=tool)),
            patch(f"{MODULE}.IntegrationResolver.resolve", new=AsyncMock(return_value=None)),
        ):
            name = await _integration_name_for(make_request(), USER_ID, "delete_item")
        assert name == "gone_srv"

    async def test_a_tool_with_no_category_and_no_integration_names_nothing(self) -> None:
        with (
            patch(f"{MODULE}.get_tool_registry", new=AsyncMock(return_value=self._registry(None))),
            patch(f"{MODULE}.gated_tool_object", new=AsyncMock(return_value=make_tool())),
            patch(f"{MODULE}.IntegrationResolver.resolve", new=AsyncMock()) as resolve,
        ):
            assert await _integration_name_for(make_request(), USER_ID, "send_email") is None
        resolve.assert_not_awaited()
