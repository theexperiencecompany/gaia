"""Tests for LangchainProvider (app/services/composio/langchain_composio_service.py)."""

import copy
from typing import Any
from unittest.mock import patch

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.runtime import Runtime
from pydantic import BaseModel, ValidationError
import pytest

from app.override.langgraph_bigtool.dynamic_tool_node import DynamicToolNode
from app.services.composio.langchain_composio_service import LangchainProvider, StructuredTool
from tests.factories import make_composio_tool

MODULE = "app.services.composio.langchain_composio_service"


class TestObservabilityFailureDoesNotBreakTheToolCall:
    """The invocation-observability log call is wrapped in its own try/except so a logging failure can't take down the tool call."""

    def _action_func(self, execute_tool: Any) -> Any:
        return LangchainProvider()._wrap_action(
            tool="GMAIL_SEND_EMAIL",
            description="Send an email.",
            schema_params={},
            execute_tool=execute_tool,
            keywords={},
            toolkit="gmail",
        )

    def test_a_logging_failure_is_swallowed_and_the_tool_result_still_returns(self) -> None:
        tool_result = {"successful": False, "error": "invalid recipient", "data": None}
        action_func = self._action_func(execute_tool=lambda _tool, _kwargs: tool_result)

        with patch(f"{MODULE}.log") as mock_log:
            mock_log.set.side_effect = RuntimeError("log sink unreachable")
            result = action_func(__runnable_config__={"metadata": {"user_id": "user-1"}})

        # The observability failure must not surface as an exception, and must not
        # swap out the real tool result for anything else.
        assert result == tool_result

    def test_the_failure_is_reported_via_log_debug_with_the_original_error(self) -> None:
        action_func = self._action_func(
            execute_tool=lambda _tool, _kwargs: {"successful": True, "data": {"id": "msg-1"}}
        )

        with patch(f"{MODULE}.log") as mock_log:
            mock_log.set.side_effect = RuntimeError("log sink unreachable")
            action_func(__runnable_config__={"metadata": {"user_id": "user-1"}})

        mock_log.debug.assert_called_once()
        _, kwargs = mock_log.debug.call_args
        assert kwargs["tool"] == "GMAIL_SEND_EMAIL"
        assert kwargs["error"] == "log sink unreachable"
        assert kwargs["error_type"] == "RuntimeError"

    def test_a_successful_invocation_never_touches_the_debug_fallback(self) -> None:
        # Positive control: observability succeeding must not also emit the
        # failure-path debug log — only the caught failure does.
        action_func = self._action_func(
            execute_tool=lambda _tool, _kwargs: {"successful": True, "data": {"id": "msg-1"}}
        )

        with patch(f"{MODULE}.log") as mock_log:
            result = action_func(__runnable_config__={"metadata": {"user_id": "user-1"}})

        assert result == {"successful": True, "data": {"id": "msg-1"}}
        mock_log.debug.assert_not_called()


class _SendArgs(BaseModel):
    recipient: str
    count: int


def _send(recipient: str, count: int) -> str:
    return f"sent {count} to {recipient}"


class TestInvalidArgumentsReturnAFailure:
    def _tool(self) -> StructuredTool:
        return StructuredTool(name="send", description="Send.", func=_send, args_schema=_SendArgs)

    def test_invalid_arguments_come_back_as_a_failure_result(self) -> None:
        result = self._tool().run({"recipient": "a@b.c", "count": "not-a-number"})

        assert isinstance(result, dict)
        assert result["successful"] is False
        assert result["data"] is None
        assert "count" in result["error"]

    def test_valid_arguments_still_run_the_tool(self) -> None:
        assert self._tool().run({"recipient": "a@b.c", "count": 2}) == "sent 2 to a@b.c"

    def test_a_plain_string_input_reaches_the_tool_as_langchain_maps_it(self) -> None:
        class _Query(BaseModel):
            query: str

        def search(query: str) -> str:
            return f"searched {query}"

        tool = StructuredTool(name="search", description="Search.", func=search, args_schema=_Query)

        assert tool.run("invoices") == "searched invoices"

    def test_a_validation_error_from_the_body_is_raised_not_blamed_on_the_arguments(self) -> None:
        sent: list[str] = []

        def sends_then_misparses(recipient: str, count: int) -> str:
            sent.append(recipient)
            return _ProviderReply.model_validate({}).message_id

        tool = StructuredTool(
            name="send", description="Send.", func=sends_then_misparses, args_schema=_SendArgs
        )

        with pytest.raises(ValidationError, match="_ProviderReply"):
            tool.run({"recipient": "a@b.c", "count": 2})
        assert sent == ["a@b.c"]


# "from" and "pass" are Python keywords, so the args schema cannot carry them as-is.
RESERVED_KEYWORD_INPUT = {
    "type": "object",
    "title": "SearchRequest",
    "properties": {
        "from": {"type": "string"},
        "query": {"type": "string"},
        "pass": {
            "type": "object",
            "title": "Pass",
            "properties": {"for": {"type": "string"}, "limit": {"type": "integer"}},
        },
    },
}


class TestReservedKeywordArguments:
    """Composio declares arguments named after Python keywords; the agent sees them renamed and Composio must get its own names back."""

    def _wrap(self) -> tuple[StructuredTool, dict[str, Any]]:
        seen: dict[str, Any] = {}

        def execute_tool(slug: str, arguments: dict[Any, Any]) -> dict[Any, Any]:
            seen.update(arguments)
            return {"successful": True, "data": {}, "error": None}

        # wrap_tool renames the schema in place, so every wrap gets its own copy.
        schema = copy.deepcopy(RESERVED_KEYWORD_INPUT)
        tool = make_composio_tool().model_copy(update={"input_parameters": schema})
        return LangchainProvider().wrap_tool(tool, execute_tool), seen

    def test_the_agent_is_offered_the_renamed_arguments(self) -> None:
        wrapped, _ = self._wrap()

        assert set(wrapped.args) == {"from_rs", "query", "pass_rs"}

    @pytest.mark.regression
    def test_composio_receives_its_own_argument_names(self) -> None:
        wrapped, seen = self._wrap()

        wrapped.invoke({"from_rs": "a@b.c", "query": "invoices"})

        # LangChain forwards an omitted optional argument as None.
        assert seen == {
            "from": "a@b.c",
            "query": "invoices",
            "pass": None,
            "__runnable_config__": {"metadata": {}},
        }

    @pytest.mark.regression
    def test_a_keyword_inside_an_object_argument_is_restored_too(self) -> None:
        wrapped, seen = self._wrap()

        wrapped.invoke({"pass_rs": {"for_rs": "inbox", "limit": 2}})

        assert seen["pass"] == {"for": "inbox", "limit": 2}
        assert "pass_rs" not in seen

    @pytest.mark.regression
    def test_an_object_argument_forwards_only_the_fields_the_caller_set(self) -> None:
        wrapped, seen = self._wrap()

        wrapped.invoke({"pass_rs": {"for_rs": "inbox"}})

        assert seen["pass"] == {"for": "inbox"}

    def test_a_direct_call_with_a_plain_mapping_is_restored_too(self) -> None:
        """Called without LangChain (no args-schema parse), an object argument stays a plain dict."""
        wrapped, seen = self._wrap()

        wrapped.func(pass_rs={"for_rs": "inbox"})

        assert seen["pass"] == {"for": "inbox"}


class TestWhatTheWrapperForwardsAndRecords:
    def _action_func(self, execute_tool: Any) -> Any:
        return LangchainProvider()._wrap_action(
            tool="GMAIL_SEND_EMAIL",
            description="Send an email.",
            schema_params={},
            execute_tool=execute_tool,
            keywords={},
            toolkit="gmail",
        )

    @pytest.mark.parametrize(
        "runnable_config",
        [{}, {"tags": ["x"]}, ["not", "a", "config"]],
        ids=["empty", "no-metadata", "not-a-mapping"],
    )
    def test_a_call_with_no_run_metadata_forwards_empty_metadata(
        self, runnable_config: object
    ) -> None:
        seen: dict[str, Any] = {}

        def execute_tool(slug: str, arguments: dict[Any, Any]) -> dict[Any, Any]:
            seen.update(arguments)
            return {"successful": True, "data": {}}

        self._action_func(execute_tool)(__runnable_config__=runnable_config)

        assert seen["__runnable_config__"] == {"metadata": {}}

    def test_metadata_that_is_not_a_mapping_attributes_the_call_to_no_user(self) -> None:
        action_func = self._action_func(lambda _tool, _kwargs: {"successful": True, "data": {}})

        with patch(f"{MODULE}.log") as mock_log:
            action_func(__runnable_config__={"metadata": "not-a-mapping"})

        assert mock_log.set.call_args.kwargs["composio_tool_invocation"]["user_id"] is None

    def test_the_invocation_is_recorded_against_the_run_user(self) -> None:
        action_func = self._action_func(lambda _tool, _kwargs: {"successful": True, "data": {}})

        with patch(f"{MODULE}.log") as mock_log:
            action_func(__runnable_config__={"metadata": {"user_id": "user-1"}})

        mock_log.set.assert_called_once_with(
            composio_tool_invocation={
                "tool": "GMAIL_SEND_EMAIL",
                "toolkit": "gmail",
                "user_id": "user-1",
                "successful": True,
            }
        )

    def test_a_non_dict_result_is_recorded_with_an_unknown_outcome(self) -> None:
        action_func = self._action_func(lambda _tool, _kwargs: "raw provider text")

        with patch(f"{MODULE}.log") as mock_log:
            result = action_func(__runnable_config__={"metadata": {"user_id": "user-1"}})

        assert result == "raw provider text"
        assert mock_log.set.call_args.kwargs["composio_tool_invocation"]["successful"] is None

    def test_a_successful_call_logs_no_failure_line(self) -> None:
        action_func = self._action_func(lambda _tool, _kwargs: {"successful": True, "data": {}})

        with patch(f"{MODULE}.log") as mock_log:
            action_func(__runnable_config__={"metadata": {"user_id": "user-1"}})

        mock_log.info.assert_not_called()
        mock_log.warning.assert_not_called()

    def test_a_failed_call_logs_its_error_bounded_to_200_characters(self) -> None:
        long_error = "invalid recipient " + "x" * 300
        action_func = self._action_func(
            lambda _tool, _kwargs: {"successful": False, "error": long_error, "data": None}
        )

        with patch(f"{MODULE}.log") as mock_log:
            action_func(__runnable_config__={"metadata": {"user_id": "user-1"}})

        assert mock_log.info.call_args.kwargs["err_preview"] == long_error[:200]


SEND_INPUT = {
    "type": "object",
    "title": "SendEmailRequest",
    "properties": {"to": {"type": "string"}},
    "required": ["to"],
}


class _ProviderReply(BaseModel):
    message_id: str


class TestAToolsOwnFailuresAreNotBlamedOnItsArguments:
    """Run in the agent's tool node, as every bound Composio tool is."""

    def _node(self, sent: list[str]) -> DynamicToolNode:
        def execute_tool(slug: str, arguments: dict[Any, Any]) -> dict[Any, Any]:
            sent.append(arguments["to"])
            return {"successful": True, "data": _ProviderReply.model_validate({}).model_dump()}

        tool = make_composio_tool("GMAIL_SEND_EMAIL").model_copy(
            update={"input_parameters": copy.deepcopy(SEND_INPUT)}
        )
        wrapped = LangchainProvider().wrap_tool(tool, execute_tool)
        return DynamicToolNode({wrapped.name: wrapped})

    async def _run(self, node: DynamicToolNode, args: dict[str, Any]) -> ToolMessage:
        call = {"name": "GMAIL_SEND_EMAIL", "args": args, "id": "c1", "type": "tool_call"}
        state = {"messages": [AIMessage(content="", tool_calls=[call])]}
        result = await node._afunc(state, {}, Runtime())
        (message,) = result["messages"]
        return message

    @pytest.mark.regression
    async def test_a_validation_error_after_the_send_is_an_execution_error(self) -> None:
        sent: list[str] = []

        message = await self._run(self._node(sent), {"to": "bob@example.com"})

        assert sent == ["bob@example.com"]
        assert message.status == "error"
        assert message.text.startswith(
            "Error: ValidationError: 1 validation error for _ProviderReply"
        )
        assert "input validation" not in message.text.lower()
        assert "not run" not in message.text

    async def test_invalid_arguments_are_refused_before_the_send(self) -> None:
        sent: list[str] = []

        message = await self._run(self._node(sent), {"to": ["not", "a", "string"]})

        assert sent == []
        assert message.text.startswith(
            "Error: ToolInvocationError: 'GMAIL_SEND_EMAIL' was not run, its arguments are invalid:"
        )
        assert "to: Input should be a valid string" in message.text
