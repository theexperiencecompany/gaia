"""Browser tasks through the whole stack, judged on what the Telegram user receives.

Each scenario is one user's chat: a message to the bot endpoint, the comms and
executor agents, the ARQ worker, a real browser host and engine, the fixture
site, and the outbound queue the bot would send from. The models are scripted
(see _stack/fake_models.py), so these prove the product's plumbing and its
promises (one answer, no leaked secret, a stop that stops, a handoff that hands
over), never a model's judgement; that is the browser eval's job.

Assertions that hold only once a parallel stream of PR #876 has merged carry its
name in a mark-free comment: teller (one teller, results through the executor
inbox, Cancel is a stop), reader (comms' browser_step_done / stop_browser_task /
tell_browser_task tools), runcore (forward-only Jev, done_when, human checks).
"""

from __future__ import annotations

import json
import uuid

import pytest

from tests.integration.real.browser._stack.fake_models import PAGE_URL, AgentStep, JevMove
from tests.integration.real.browser._stack.fixture_site import FORM_RECEIVED
from tests.integration.real.browser._stack.observe import wait_for
from tests.integration.real.browser._stack.stack import RUN_SECONDS, BrowserStack

pytestmark = [pytest.mark.asyncio(loop_scope="module"), pytest.mark.timeout(900)]

_PASSWORD = "gaia-test-123"  # pragma: allowlist secret


def _marker() -> str:
    """Return a token that ties a run's task to its script."""
    return f"run-{uuid.uuid4().hex[:10]}"


def _browser_message(
    task: str, start_url: str, secrets: dict[str, dict[str, str]] | None = None
) -> str:
    """Return the user's message: comms forwards it, and the executor starts exactly this browser task."""
    args: dict[str, object] = {"task": task, "start_url": start_url}
    if secrets:
        args["secrets"] = secrets
    return f"Use the browser for this. [[tool:browser_task {json.dumps(args)}]]"


async def test_a_form_is_filled_with_a_secret_and_the_answer_reaches_the_user_once(
    stack: BrowserStack,
) -> None:
    user = await stack.new_user()
    dm = await stack.watch(user.telegram_id)
    marker = _marker()
    form = stack.site.url("/form")
    task = (
        f'Fill the form at {form}: text input "Aryan", password <secret>password</secret>, '
        'pick "Two" in the dropdown, tick "Checkbox 2", choose "Radio 2", set the date to '
        f"09/22/2026, submit it, and tell me the message and the page you land on. {marker}"
    )
    stack.models.script(
        marker,
        jev=[
            JevMove("TYPE_TEXT", "Text input", value="Aryan"),
            JevMove("TYPE_TEXT", "Password", value="<secret>password</secret>"),
            JevMove("SELECT", "Dropdown", option="Two"),
            JevMove("CLICK", "Checkbox 2"),
            JevMove("CLICK", "Radio 2"),
            JevMove("TYPE_TEXT", "Date picker", value="09/22/2026"),
            JevMove("CLICK", "Submit"),
            JevMove("DONE"),
        ],
        agent=[
            AgentStep(
                [
                    {
                        "done": {
                            "text": f"The page says {FORM_RECEIVED} at {PAGE_URL}",
                            "success": True,
                        }
                    }
                ],
                require=(FORM_RECEIVED,),
            )
        ],
    )

    reply = await stack.say(
        user,
        _browser_message(task, form, {"password": {"value": _PASSWORD, "site": "localhost"}}),
    )
    assert reply.conversation_id, reply
    job_id = await stack.job_for(reply.conversation_id)
    state = await stack.finished(job_id)
    answer = await wait_for(dm, FORM_RECEIVED, timeout=RUN_SECONDS)
    await stack.settled(reply.conversation_id)

    assert state.result is not None and state.result.success, state.result
    assert stack.models.errors == []
    # The site received every value, the real password among them.
    (submitted,) = stack.site.posts_to("/submitted-form.html")
    assert submitted.fields["my-text"] == ["Aryan"]
    assert submitted.fields["my-password"] == [_PASSWORD]
    assert submitted.fields["my-select"] == ["2"]
    assert submitted.fields["my-check"] == ["on", "on"]
    assert submitted.fields["my-date"] == ["09/22/2026"]
    # The user read the page's answer and the page it landed on, without the password in it.
    assert "/submitted-form.html?" in answer.said
    assert all(_PASSWORD not in delivery.said for delivery in dm.deliveries)
    assert dm.photos, "no step photo reached the chat"
    # teller: the answer is told once, by the one teller.
    assert len(dm.matching(FORM_RECEIVED)) == 1, [d.said for d in dm.deliveries]
