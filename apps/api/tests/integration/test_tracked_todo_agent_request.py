"""The request a tracked-todo run hands the agent must actually carry its prompt.

``construct_langchain_messages`` reads the user's content from ``messages[-1]``;
``request.message`` is only passed along as ``query=`` for memory retrieval. A
caller that fills ``message`` but leaves ``messages`` empty, and supplies no
selected workflow/tool/calendar event either, produces empty content and the
whole run raises before the model is ever called.

That is not hypothetical. Every agent-path tracked todo — any tracked todo
without a ``workflow_id`` — failed exactly this way on every attempt, burned its
three retries and was marked failed. The unit tests never saw it because they
mock ``call_agent_silent``, so the real message construction never ran.

``workflow_tasks`` looks like the same shape but is not: it passes
``selectedWorkflow``, and that branch builds content without ever reading
``messages``.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.agents.core.messages import construct_langchain_messages
from app.models.agent_models import SilentRunResult
from app.models.message_models import MessageRequestWithHistory
from app.models.todo_models import TodoDocument
from app.workers.tasks.tracked_todo_tasks import _execute_via_agent

pytestmark = pytest.mark.integration

_MOD = "app.workers.tasks.tracked_todo_tasks"
USER_ID = "507f1f77bcf86cd799439011"
TODO_ID = "todo-1"


def _todo() -> TodoDocument:
    return TodoDocument.model_validate(
        {"id": TODO_ID, "user_id": USER_ID, "title": "Chase Acme about invoice 4021"}
    )


async def _captured_request() -> MessageRequestWithHistory:
    """Run the real agent path far enough to capture the request it builds."""
    silent = AsyncMock(return_value=SilentRunResult(message="done", tool_data={}))
    with (
        patch(f"{_MOD}.call_agent_silent", silent),
        patch(f"{_MOD}.read_canvas", new_callable=AsyncMock, return_value=None),
        patch(f"{_MOD}._collect_reference_context", new_callable=AsyncMock, return_value=""),
        patch(f"{_MOD}.tracked_todo_service.append_canvas_timeline", new_callable=AsyncMock),
        patch(f"{_MOD}.tracked_todo_service.system_log", new_callable=AsyncMock),
    ):
        await _execute_via_agent(_todo(), USER_ID, user_data={"user_id": USER_ID})
    return silent.await_args.kwargs["request"]


class TestTheRequestCarriesItsPrompt:
    async def test_the_prompt_is_where_content_is_actually_read_from(self) -> None:
        request = await _captured_request()

        assert request.messages, "messages is empty, so the run has no user content at all"
        assert request.messages[-1]["role"] == "user"
        assert "Chase Acme about invoice 4021" in request.messages[-1]["content"]

    async def test_the_real_message_construction_accepts_it(self) -> None:
        """The end-to-end contract: no ValueError, and the prompt reaches the model.

        Asserting the request shape alone would only pin our own opinion of it.
        This runs the real constructor, which is what actually rejected it.
        """
        request = await _captured_request()

        with (
            patch(
                "app.agents.core.messages.assemble_context",
                new_callable=AsyncMock,
            ) as assemble,
            patch(
                "app.agents.core.messages.build_current_time_message",
                return_value=None,
            ),
        ):
            assemble.return_value = type("Assembled", (), {"stable": None, "volatile": None})()
            messages = await construct_langchain_messages(
                messages=request.messages,
                user_id=USER_ID,
                query=request.message,
                user_dict={"user_id": USER_ID},
                agent_type="executor",
                execution_mode="background",
                active_todo_id=TODO_ID,
            )

        rendered = " ".join(str(getattr(m, "content", "")) for m in messages)
        assert "Chase Acme about invoice 4021" in rendered
