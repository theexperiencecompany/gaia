"""
UNIT: app/override/langgraph_bigtool/create_agent.py :: create_agent
      (focus on the should_continue routing closure and the acall_model
       response-shaping branches)

EXPECTED:
    create_agent builds a StateGraph whose `agent` node routes via the
    should_continue closure. Driving the compiled graph with a deterministic
    fake LLM (the I/O boundary) exercises every routing decision and the
    response-shaping logic in acall_model — asserting the resulting message
    state, not graph internals.

MECHANISM:
    - should_continue inspects the last AIMessage's tool_calls and decides the
      next hop: END / end_graph_hooks (no calls), Send(finish_task) (a
      finish_task call short-circuits all others), Send("select_tools")
      (retrieve_tools call), Send("tools", ToolCallWithContext) (bound tool,
      optionally after rewriting a hyphen/underscore canonical name), or
      Send("reject_unbound_tools") (unknown tool). Bound + unbound calls in the
      same message produce multiple Sends.
    - select_tools/aselect_tools invoke retrieve_tools with the call args plus
      the config's user_id, drop "subagent:"-prefixed ids from binding while
      keeping them in the shown response, and write the bound ids to
      selected_tool_ids.
    - acall_model: empty response (no tool_calls, no content) is rewritten to
      "Empty response from model."; for agent_name == "comms_agent" the string
      content gets NEW_MESSAGE_BREAKER appended.

MUST-CATCH (each maps to >=1 test + >=1 killed mutant):
    - a finish_task tool call short-circuits routing: only finish_task runs,
      sibling tool calls are dropped                          [routing contract]
    - finish_task carries args["result"] as the ToolMessage content; missing
      result falls back to "Task completed."                  [finish payload]
    - an unbound tool call routes to reject_unbound_tools and yields an error
      ToolMessage naming the unbound tool                     [guardrail]
    - a hyphen/underscore canonical mismatch is rewritten so the real tool
      executes (not rejected)                                 [MCP name contract]
    - bound + unbound calls in one AIMessage route independently: bound tool
      executes AND unbound tool is rejected                   [multi-Send fan-out]
    - the retrieve_tools call routes to select_tools, which calls retrieve_tools
      with the query and the config user_id, filters "subagent:" ids out of
      binding (kept in the shown list), and binds the real id  [retrieval path]
    - disable_retrieve_tools=True removes the retrieve_tools mechanism: a
      retrieve_tools call is unbound and rejected             [disable flag]
    - comms_agent appends NEW_MESSAGE_BREAKER to string content; other agents
      do not                                                  [comms contract]
    - empty model output is replaced with the literal "Empty response from
      model." sentinel                                        [empty guard]

EQUIVALENT MUTANTS (allowed survivors, justified):
    - The defensive message-preview logging block in acall_model (truncation at
      200 chars, try/except around log.info) has no observable effect on routing
      or returned state; mutating its constants/branches is behaviour-preserving
      for this contract. It is exercised on every model call but not asserted.
"""

from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
import pytest

from app.constants.general import FINISH_TASK_NAME, NEW_MESSAGE_BREAKER
from app.override.langgraph_bigtool.create_agent import create_agent
from tests.helpers import BindableToolsFakeModel


def _thread_config() -> dict:
    """Unique thread + user id so checkpoint state never leaks between tests."""
    return {"configurable": {"thread_id": str(uuid4()), "user_id": str(uuid4())}}


@tool
def echo_tool(query: str) -> str:
    """Echo the query back (deterministic registry tool for routing tests)."""
    return f"echo: {query}"


@tool("notion-search")
def notion_search(query: str) -> str:
    """A hyphen-named tool, mimicking an MCP tool the LLM may echo with underscores."""
    return f"notion: {query}"


def _llm(*responses: AIMessage) -> BindableToolsFakeModel:
    """Fake LLM that replays the given AIMessages in order across turns."""
    return BindableToolsFakeModel(responses=list(responses))


def _tool_call(name: str, *, call_id: str, **args: object) -> dict:
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


def _compile_no_retrieval(
    llm: BindableToolsFakeModel,
    *,
    registry: dict | None = None,
    initial_tool_ids: list[str] | None = None,
    agent_name: str = "test_agent",
):
    """Compile a create_agent graph with retrieval disabled and a MemorySaver."""
    builder = create_agent(
        llm=llm,
        tool_registry=registry if registry is not None else {"echo_tool": echo_tool},
        disable_retrieve_tools=True,
        initial_tool_ids=initial_tool_ids if initial_tool_ids is not None else ["echo_tool"],
        agent_name=agent_name,
    )
    return builder.compile(checkpointer=MemorySaver())


def _tool_messages(result: dict) -> list[ToolMessage]:
    return [m for m in result["messages"] if isinstance(m, ToolMessage)]


def _final_ai(result: dict) -> AIMessage:
    return [m for m in result["messages"] if isinstance(m, AIMessage)][-1]


@pytest.mark.unit
@pytest.mark.asyncio
class TestFinishTaskRouting:
    """A finish_task tool call short-circuits should_continue to the finish node."""

    async def test_finish_task_call_short_circuits_sibling_tool_calls(self):
        """finish_task + a real tool call in one AIMessage → only finish_task runs.

        should_continue returns early on the first finish_task call, dropping all
        other calls. Kills a mutant that removes the early `if finish_calls: return`.
        """
        graph = _compile_no_retrieval(
            _llm(
                AIMessage(
                    content="",
                    tool_calls=[
                        _tool_call(FINISH_TASK_NAME, call_id="f1", result="all set"),
                        _tool_call("notion-search", call_id="o1", query="ignored"),
                    ],
                ),
                AIMessage(content="post finish"),
            ),
            registry={"notion-search": notion_search},
            initial_tool_ids=["notion-search"],
        )

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="finish now")]},
            config=_thread_config(),
        )

        tool_msgs = _tool_messages(result)
        assert [m.name for m in tool_msgs] == [FINISH_TASK_NAME], (
            "Only the finish_task call must execute; the sibling notion-search call "
            f"must be dropped. Got tool messages from: {[m.name for m in tool_msgs]}"
        )
        assert all("notion:" not in m.content for m in tool_msgs), (
            "The sibling notion-search tool must NOT have executed when finish_task "
            "short-circuits routing."
        )

    async def test_finish_task_content_is_the_result_argument(self):
        """finish_task ToolMessage content is exactly args['result'].

        Kills mutants that read the wrong arg key or stringify a constant.
        """
        graph = _compile_no_retrieval(
            _llm(
                AIMessage(
                    content="",
                    tool_calls=[
                        _tool_call(FINISH_TASK_NAME, call_id="f2", result="the final summary"),
                    ],
                )
            ),
            registry={"notion-search": notion_search},
            initial_tool_ids=["notion-search"],
        )

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="wrap up")]},
            config=_thread_config(),
        )

        finish_msgs = [m for m in _tool_messages(result) if m.name == FINISH_TASK_NAME]
        assert len(finish_msgs) == 1, "Exactly one finish_task ToolMessage expected."
        assert finish_msgs[0].content == "the final summary", (
            f"finish_task content must be args['result']. Got: {finish_msgs[0].content!r}"
        )

    async def test_finish_task_without_result_falls_back_to_task_completed(self):
        """finish_task with no 'result' arg → content defaults to 'Task completed.'.

        Kills a mutant that drops the None fallback or changes the literal.
        """
        graph = _compile_no_retrieval(
            _llm(
                AIMessage(
                    content="",
                    tool_calls=[
                        _tool_call(FINISH_TASK_NAME, call_id="f3"),
                    ],
                )
            ),
            registry={"notion-search": notion_search},
            initial_tool_ids=["notion-search"],
        )

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="done")]},
            config=_thread_config(),
        )

        finish_msgs = [m for m in _tool_messages(result) if m.name == FINISH_TASK_NAME]
        assert len(finish_msgs) == 1
        assert finish_msgs[0].content == "Task completed.", (
            f"Missing result must fall back to 'Task completed.'. Got: {finish_msgs[0].content!r}"
        )


@pytest.mark.unit
@pytest.mark.asyncio
class TestUnboundToolRouting:
    """Unknown tool calls route to reject_unbound_tools instead of executing."""

    async def test_unbound_tool_is_rejected_with_naming_error_message(self):
        """A tool not in the bound set → reject_unbound_tools error ToolMessage.

        Kills mutants that route unbound calls to the tools node or skip the
        unbound_calls accumulation.
        """
        graph = _compile_no_retrieval(
            _llm(
                AIMessage(
                    content="",
                    tool_calls=[
                        _tool_call("totally_unknown_tool", call_id="u1"),
                    ],
                ),
                AIMessage(content="recovered"),
            ),
        )

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="call unknown")]},
            config=_thread_config(),
        )

        tool_msgs = _tool_messages(result)
        assert len(tool_msgs) == 1, "Exactly one rejection ToolMessage expected."
        rejection = tool_msgs[0]
        assert rejection.name == "totally_unknown_tool", (
            f"Rejection ToolMessage must name the unbound tool. Got name: {rejection.name!r}"
        )
        assert "is not bound" in rejection.content, (
            f"Rejection content must explain the tool is not bound. Got: {rejection.content!r}"
        )
        assert "totally_unknown_tool" in rejection.content, (
            "Rejection content must reference the offending tool name."
        )
        assert rejection.tool_call_id == "u1", (
            f"Rejection must carry the original call id 'u1'. Got: {rejection.tool_call_id!r}"
        )

    async def test_bound_and_unbound_calls_route_independently(self):
        """One AIMessage with a bound + an unbound call produces both outcomes.

        should_continue emits multiple Sends: the bound call to 'tools', the
        unbound call to 'reject_unbound_tools'. Kills mutants that collapse the
        per-call loop or only handle the first call.
        """
        graph = _compile_no_retrieval(
            _llm(
                AIMessage(
                    content="",
                    tool_calls=[
                        _tool_call("echo_tool", call_id="b1", query="ok"),
                        _tool_call("mystery_tool", call_id="u1"),
                    ],
                ),
                AIMessage(content="recovered"),
            ),
        )

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="mixed")]},
            config=_thread_config(),
        )

        by_id = {m.tool_call_id: m for m in _tool_messages(result)}
        assert set(by_id) == {"b1", "u1"}, (
            f"Both the bound and unbound calls must yield ToolMessages. Got ids: {set(by_id)}"
        )
        assert by_id["b1"].content == "echo: ok", (
            f"Bound echo_tool must execute and return its real output. Got: {by_id['b1'].content!r}"
        )
        assert "is not bound" in by_id["u1"].content, (
            f"Unbound mystery_tool must be rejected. Got: {by_id['u1'].content!r}"
        )


@pytest.mark.unit
@pytest.mark.asyncio
class TestCanonicalNameRewriteRouting:
    """Hyphen/underscore canonical mismatches are rewritten so the real tool runs."""

    async def test_underscore_name_rewritten_to_hyphenated_bound_tool(self):
        """LLM emits 'notion_search' but the tool is registered as 'notion-search'.

        should_continue maps the underscore form back to the canonical hyphen
        name and routes to 'tools' (instead of rejecting). Kills a mutant that
        drops the canonical_to_bound rewrite or the .replace('-', '_') step.
        """
        graph = _compile_no_retrieval(
            _llm(
                AIMessage(
                    content="",
                    tool_calls=[
                        _tool_call("notion_search", call_id="c1", query="rewrite me"),
                    ],
                ),
                AIMessage(content="done"),
            ),
            registry={"notion-search": notion_search},
            initial_tool_ids=["notion-search"],
        )

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="search notion")]},
            config=_thread_config(),
        )

        tool_msgs = _tool_messages(result)
        assert len(tool_msgs) == 1, "Expected the rewritten call to execute exactly once."
        assert tool_msgs[0].content == "notion: rewrite me", (
            "The underscore-named call must be rewritten to the bound 'notion-search' "
            f"tool and execute it. Got: {tool_msgs[0].content!r}"
        )
        assert "is not bound" not in tool_msgs[0].content, (
            "A canonically-rewritable call must NOT be rejected as unbound."
        )


@pytest.mark.unit
@pytest.mark.asyncio
class TestRetrieveToolsRouting:
    """The retrieve_tools call routes to select_tools and binds the retrieved ids."""

    async def test_retrieve_tools_call_invokes_retriever_and_binds_filtered_tools(self):
        """retrieve_tools call → select_tools runs the retriever, filters subagents.

        Verifies: (1) the retriever is invoked with the call's query and the
        config user_id; (2) "subagent:"-prefixed ids are shown in the response
        message but excluded from binding; (3) the real tool id is bound and
        becomes callable on the next turn.

        Kills mutants in select_tools: dropping the user_id injection, removing
        the subagent: filter, or swapping tools_to_bind/response keys.
        """
        captured: dict[str, object] = {}

        async def retrieve_tools(query: str, store=None, user_id=None) -> dict:
            """Custom retriever returning a RetrieveToolsResult dict."""
            captured["query"] = query
            captured["user_id"] = user_id
            return {
                "tools_to_bind": ["real_tool", "subagent:planner"],
                "response": ["real_tool", "subagent:planner"],
            }

        @tool
        def real_tool(query: str) -> str:
            """A real registry tool retrieved on demand."""
            return f"real: {query}"

        builder = create_agent(
            llm=_llm(
                AIMessage(
                    content="",
                    tool_calls=[
                        _tool_call("retrieve_tools", call_id="rt1", query="find a tool"),
                    ],
                ),
                AIMessage(
                    content="",
                    tool_calls=[
                        _tool_call("real_tool", call_id="ur1", query="go"),
                    ],
                ),
                AIMessage(content="finished"),
            ),
            tool_registry={"real_tool": real_tool},
            retrieve_tools_coroutine=retrieve_tools,
            agent_name="test_agent",
        )
        graph = builder.compile(checkpointer=MemorySaver())
        config = {"configurable": {"thread_id": str(uuid4()), "user_id": "user-42"}}

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="please")]},
            config=config,
        )

        assert captured["query"] == "find a tool", (
            f"Retriever must be called with the call's query arg. Got: {captured.get('query')!r}"
        )
        assert captured["user_id"] == "user-42", (
            "select_tools must inject the config user_id into the retriever kwargs. "
            f"Got: {captured.get('user_id')!r}"
        )

        contents = [m.content for m in _tool_messages(result)]
        assert any("subagent:planner" in c and "real_tool" in c for c in contents), (
            "The 'Available tools' response message must list both the real and the "
            f"subagent tool. Got tool messages: {contents}"
        )
        assert any(c == "real: go" for c in contents), (
            "The retrieved real_tool must be bound (subagent: filtered out) and execute "
            f"on the next turn. Got tool messages: {contents}"
        )

        bound_ids = (await graph.aget_state(config)).values.get("selected_tool_ids")
        assert bound_ids == ["real_tool"], (
            "Only the non-subagent id may be bound to the model. "
            f"Expected ['real_tool'], got: {bound_ids}"
        )


@pytest.mark.unit
@pytest.mark.asyncio
class TestRetrievalDisabled:
    """disable_retrieve_tools=True removes the retrieve_tools mechanism entirely."""

    async def test_retrieve_tools_call_is_unbound_when_retrieval_disabled(self):
        """With retrieval disabled, a retrieve_tools call has no special route.

        It is treated as any other unknown tool and rejected. Kills mutants that
        keep the select_tools route alive when disable_retrieve_tools is True.
        """
        graph = _compile_no_retrieval(
            _llm(
                AIMessage(
                    content="",
                    tool_calls=[
                        _tool_call("retrieve_tools", call_id="rt1", query="x"),
                    ],
                ),
                AIMessage(content="recovered"),
            ),
        )

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="retrieve")]},
            config=_thread_config(),
        )

        tool_msgs = _tool_messages(result)
        assert len(tool_msgs) == 1
        assert "is not bound" in tool_msgs[0].content, (
            "When retrieval is disabled, a retrieve_tools call must be rejected as "
            f"unbound (no select_tools route). Got: {tool_msgs[0].content!r}"
        )


@pytest.mark.unit
@pytest.mark.asyncio
class TestAcallModelResponseShaping:
    """acall_model rewrites empty output and appends the comms breaker."""

    async def test_comms_agent_appends_new_message_breaker(self):
        """agent_name == 'comms_agent' appends NEW_MESSAGE_BREAKER to string content.

        Kills a mutant that drops the comms_agent suffix or appends to the wrong agent.
        """
        graph = _compile_no_retrieval(
            _llm(AIMessage(content="hello world")),
            agent_name="comms_agent",
        )

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="hi")]},
            config=_thread_config(),
        )

        assert _final_ai(result).content == "hello world" + NEW_MESSAGE_BREAKER, (
            "comms_agent must append NEW_MESSAGE_BREAKER to the model's string content. "
            f"Got: {_final_ai(result).content!r}"
        )

    async def test_non_comms_agent_does_not_append_breaker(self):
        """A non-comms agent leaves string content untouched.

        Kills a mutant that appends the breaker unconditionally.
        """
        graph = _compile_no_retrieval(
            _llm(AIMessage(content="hello world")),
            agent_name="executor_agent",
        )

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="hi")]},
            config=_thread_config(),
        )

        assert _final_ai(result).content == "hello world", (
            "A non-comms agent must NOT append NEW_MESSAGE_BREAKER. "
            f"Got: {_final_ai(result).content!r}"
        )

    async def test_empty_model_output_is_replaced_with_sentinel(self):
        """No tool_calls and empty content → 'Empty response from model.' sentinel.

        Kills a mutant that drops the empty-response guard or changes the literal.
        """
        graph = _compile_no_retrieval(
            _llm(AIMessage(content="")),
            agent_name="executor_agent",
        )

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="hi")]},
            config=_thread_config(),
        )

        assert _final_ai(result).content == "Empty response from model.", (
            "Empty model output must be replaced with the sentinel string. "
            f"Got: {_final_ai(result).content!r}"
        )

    async def test_empty_comms_output_gets_sentinel_then_breaker(self):
        """Empty content on comms_agent → sentinel THEN breaker appended.

        Confirms the empty guard runs before the comms suffix (ordering of the
        two acall_model branches). Kills a mutant that reverses or skips either.
        """
        graph = _compile_no_retrieval(
            _llm(AIMessage(content="")),
            agent_name="comms_agent",
        )

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="hi")]},
            config=_thread_config(),
        )

        assert _final_ai(result).content == "Empty response from model." + NEW_MESSAGE_BREAKER, (
            "Empty comms output must become the sentinel with the breaker appended. "
            f"Got: {_final_ai(result).content!r}"
        )
