"""The prompt layer, pinned at the model boundary.

``construct_langchain_messages`` assembles the conversation — static system
prompt, dynamic context, the user's turn, the clock — and the graph's pre-model
hooks (``filter_messages_node``, ``executor_status_hook``,
``manage_system_prompts_node``) are free to rewrite it before the model sees it.
The recording model captures the message list right before it produces output,
so these tests pin the bytes that actually reach the model: a prompt change that
looks right in the builder but gets mangled by a hook fails here.

Tool declarations do NOT ride the message list: ``acall_model`` hands them to
the provider through ``bind_tools``. The recording model captures that binding
too, so the tool surface is asserted on ``model_bound_tools`` — the same channel
the real provider receives schemas on.
"""

from __future__ import annotations

from datetime import UTC, datetime

from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage
import pytest

from app.agents.core.messages import construct_langchain_messages
from app.agents.templates.agent_template import get_comms_static_prompt
from tests.e2e._harness.graph_run import comms_graph, run_graph, scripted_model_of

pytestmark = pytest.mark.e2e

USER_TURN = "Do I have any meetings tomorrow?"


async def _construct_web_prompt(user_turn: str) -> list[AnyMessage]:
    """The message list the production prompt builder assembles for a web turn."""
    return await construct_langchain_messages(
        messages=[{"role": "user", "content": user_turn}],
        source="web",
    )


class TestPromptContract:
    async def test_the_model_sees_the_constructed_prompt_unchanged(self):
        """On a fresh thread the pre-model hooks rewrite nothing: the prompt the
        model reports receiving is byte-identical to what the builder produced."""
        messages = await _construct_web_prompt(USER_TURN)

        async with comms_graph(["ok"]) as graph:
            run = await run_graph(graph, USER_TURN, state={"messages": messages, "todos": []})
            model = scripted_model_of(graph)

        assert run.prompts, "the model was never called"
        assert len(model.chat_messages_log) == len(run.prompts) == 1
        assert model.last_chat_messages == run.last_prompt()
        assert run.last_prompt() == messages
        assert run.last_prompt() == model.chat_messages_log[0]

    async def test_the_system_prompt_is_the_static_comms_prompt(self):
        messages = await _construct_web_prompt(USER_TURN)

        async with comms_graph(["ok"]) as graph:
            run = await run_graph(graph, USER_TURN, state={"messages": messages, "todos": []})

        first = run.last_prompt()[0]
        assert isinstance(first, SystemMessage)
        assert str(first.content) == get_comms_static_prompt("web")

    async def test_the_prompt_carries_todays_date(self):
        """The clock rides a HumanMessage tagged ``time_context`` (kept out of
        system_instruction so minute ticks never invalidate the cache prefix),
        and the model must see the current date in it."""
        messages = await _construct_web_prompt(USER_TURN)

        async with comms_graph(["ok"]) as graph:
            run = await run_graph(graph, USER_TURN, state={"messages": messages, "todos": []})

        clocks = [
            message
            for message in run.last_prompt()
            if isinstance(message, HumanMessage) and message.additional_kwargs.get("time_context")
        ]
        assert len(clocks) == 1, f"expected exactly one clock frame, got {len(clocks)}"
        clock = str(clocks[0].content)
        assert "[Current UTC Time:" in clock
        assert datetime.now(UTC).strftime("%B %d, %Y") in clock

    async def test_the_user_turn_reaches_the_model_verbatim(self):
        messages = await _construct_web_prompt(USER_TURN)

        async with comms_graph(["ok"]) as graph:
            run = await run_graph(graph, USER_TURN, state={"messages": messages, "todos": []})

        joined = " ".join(str(message.content) for message in run.last_prompt())
        assert USER_TURN in joined

    async def test_the_comms_tool_surface_is_bound_for_the_model(self):
        """The provider receives tool declarations via ``bind_tools``; the
        recording model captures what was bound on each call."""
        messages = await _construct_web_prompt(USER_TURN)

        async with comms_graph(["ok"]) as graph:
            run = await run_graph(graph, USER_TURN, state={"messages": messages, "todos": []})

        bound = run.model_bound_tools()
        for tool in ("call_executor", "cancel_executor", "add_memory", "search_memory"):
            assert tool in bound, f"{tool} was never bound to the model: {bound}"
