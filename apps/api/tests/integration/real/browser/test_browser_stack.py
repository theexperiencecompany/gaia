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

import asyncio
from collections.abc import Awaitable, Callable
import json
import re
import time
import uuid

import pytest

from app.agents.core.background.executor_queue import is_executor_busy
from app.constants.browser import BROWSER_HANDOFF_REPLY_PROMPT, BrowserSessionStatus, JobEnding
from app.db.repositories.browser_tasks import browser_task_repository
from tests.integration.real.browser._stack.fake_models import PAGE_URL, AgentStep, JevMove
from tests.integration.real.browser._stack.fixture_site import (
    CAPTCHA_HEADING,
    DYNAMIC_TEXT,
    FORM_RECEIVED,
    LOGIN_FLASH,
    LOGIN_PASSWORD,
    LOGIN_USER,
    NEW_WINDOW_HEADING,
    SECURE_HEADING,
)
from tests.integration.real.browser._stack.observe import Delivery, Transcript, wait_for
from tests.integration.real.browser._stack.stack import (
    RUN_SECONDS,
    SCENARIO_SECONDS,
    BotUser,
    BrowserStack,
)

pytestmark = [pytest.mark.asyncio(loop_scope="module"), pytest.mark.timeout(SCENARIO_SECONDS)]

_PASSWORD = "gaia-test-123"  # pragma: allowlist secret


def _marker() -> str:
    """Return a token that ties a run's task to its script."""
    return f"run-{uuid.uuid4().hex[:10]}"


#: The handoff message's live-view line; the link is the page whose Done and Cancel a person presses.
_LIVE_LINK = re.compile(r"Open the live browser: (\S+)")
#: Lines a run sends that are not anything it was asked: step captions and the closing recap link.
_PROGRESS = re.compile(r"^(Step \d+ ·|📽 )")
_LOGIN_JS = f"""(() => {{
  document.querySelector('#username').value = '{LOGIN_USER}';
  document.querySelector('#password').value = '{LOGIN_PASSWORD}';
  document.querySelector('#login').submit();
}})()"""


def _told(transcript: Transcript) -> list[Delivery]:
    """Return what the chat was told in words: no photo, no progress line, no handoff prompt."""
    return [
        d
        for d in transcript.deliveries
        if d.text
        and not d.photo_url
        and not _PROGRESS.match(d.text)
        and BROWSER_HANDOFF_REPLY_PROMPT not in d.text
    ]


async def _until(
    condition: Callable[[], Awaitable[bool]], what: str, *, timeout: float = RUN_SECONDS
) -> None:
    """Poll an async predicate until it holds, failing with what it waited for."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if await condition():
            return
        await asyncio.sleep(0.2)
    raise AssertionError(f"{what} did not happen within {timeout}s")


async def _start(
    stack: BrowserStack,
    user: BotUser,
    task: str,
    start_url: str,
    *,
    secrets: dict[str, dict[str, str]] | None = None,
    channel_id: str | None = None,
) -> tuple[str, str]:
    """Send the message that starts one browser run; return its conversation and job."""
    reply = await stack.say(user, _browser_message(task, start_url, secrets), channel_id=channel_id)
    assert reply.conversation_id, reply
    return reply.conversation_id, await stack.job_for(reply.conversation_id)


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
    result = await stack.finished(job_id)
    answer = await wait_for(dm, FORM_RECEIVED, timeout=RUN_SECONDS)
    await stack.settled(reply.conversation_id)

    assert result.success, result
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
    # One message started one run.
    assert len(await browser_task_repository.list_recent_for_user(user.user_id)) == 1
    # teller: the answer is told once, by the one teller.
    assert len(dm.matching(FORM_RECEIVED)) == 1, [d.said for d in dm.deliveries]


async def test_content_that_appears_after_a_wait_is_read_once_it_is_there(
    stack: BrowserStack,
) -> None:
    user = await stack.new_user()
    dm = await stack.watch(user.telegram_id)
    marker = _marker()
    page = stack.site.url("/dynamic_loading")
    stack.models.script(
        marker,
        jev=[JevMove("CLICK", "Start"), JevMove("DONE")],
        agent=[
            AgentStep(
                [{"done": {"text": f"The page now says {DYNAMIC_TEXT}", "success": True}}],
                wait_for=DYNAMIC_TEXT,
                require=(DYNAMIC_TEXT,),
            )
        ],
    )

    conversation_id, job_id = await _start(
        stack, user, f"Open {page}, click Start and tell me what loads. {marker}", page
    )
    result = await stack.finished(job_id)
    await wait_for(dm, re.escape(DYNAMIC_TEXT), timeout=RUN_SECONDS)
    await stack.settled(conversation_id)

    assert result.success, result
    assert stack.models.errors == []
    # teller: told once.
    assert len([d for d in _told(dm) if DYNAMIC_TEXT in d.text]) == 1, dm.texts


async def test_a_link_that_opens_a_new_window_is_followed_into_it(stack: BrowserStack) -> None:
    user = await stack.new_user()
    dm = await stack.watch(user.telegram_id)
    marker = _marker()
    page = stack.site.url("/windows")
    stack.models.script(
        marker,
        jev=[JevMove("CLICK", "Click Here"), JevMove("DONE")],
        agent=[
            AgentStep(
                [
                    {
                        "done": {
                            "text": f"The new window is headed {NEW_WINDOW_HEADING}",
                            "success": True,
                        }
                    }
                ],
                wait_for=NEW_WINDOW_HEADING,
                require=(NEW_WINDOW_HEADING,),
            )
        ],
    )

    conversation_id, job_id = await _start(
        stack,
        user,
        f"Open {page}, click Click Here and tell me the new page's heading. {marker}",
        page,
    )
    result = await stack.finished(job_id)
    await wait_for(dm, NEW_WINDOW_HEADING, timeout=RUN_SECONDS)
    await stack.settled(conversation_id)

    assert result.success, result
    assert stack.models.errors == []


async def test_a_page_that_never_answers_does_not_freeze_the_run(stack: BrowserStack) -> None:
    user = await stack.new_user()
    dm = await stack.watch(user.telegram_id)
    marker = _marker()
    hang, home = stack.site.url("/hang"), stack.site.url("/")
    stack.models.script(
        marker,
        agent=[
            AgentStep([{"navigate": {"url": home}}]),
            AgentStep(
                [
                    {
                        "done": {
                            "text": "The first page never loaded; the other is Fixture Domain",
                            "success": True,
                        }
                    }
                ],
                wait_for="Fixture Domain",
                require=("Fixture Domain",),
            ),
        ],
    )

    conversation_id, job_id = await _start(
        stack,
        user,
        f"Open {hang} and tell me what it shows; if it never loads, tell me the heading of {home}. {marker}",
        hang,
    )
    result = await stack.finished(job_id)
    await wait_for(dm, "Fixture Domain", timeout=RUN_SECONDS)
    await stack.settled(conversation_id)

    assert result.success, result
    assert stack.models.errors == []


async def test_a_secret_is_never_typed_on_a_site_it_was_not_given_for(stack: BrowserStack) -> None:
    user = await stack.new_user()
    dm = await stack.watch(user.telegram_id)
    marker = _marker()
    page = stack.site.url("/elsewhere")
    stack.models.script(
        marker,
        jev=[
            JevMove("CLICK", "Continue to partner"),
            JevMove("TYPE_TEXT", "Password", value="<secret>password</secret>"),
        ],
        agent=[
            AgentStep(
                [
                    {
                        "done": {
                            "text": "That password is for another site; I typed nothing here.",
                            "success": False,
                        }
                    }
                ]
            )
        ],
    )

    conversation_id, job_id = await _start(
        stack,
        user,
        f"Open {page}, continue to the partner and sign in with <secret>password</secret>. {marker}",
        page,
        secrets={"password": {"value": _PASSWORD, "site": "localhost"}},
    )
    result = await stack.finished(job_id)
    await stack.settled(conversation_id)

    assert not result.success, result
    assert stack.models.errors == []
    # The partner (another host) received nothing, and the password reached no message.
    assert stack.site.posts_to("/partner-login") == []
    assert all(_PASSWORD not in d.said for d in dm.deliveries)


async def test_a_login_is_handed_to_the_user_and_then_reused_without_asking_again(
    stack: BrowserStack,
) -> None:
    user = await stack.new_user()
    dm = await stack.watch(user.telegram_id)
    login = stack.site.url("/login")
    first = _marker()
    stack.models.script(
        first,
        jev=[JevMove("BLOCKED")],
        agent=[
            AgentStep(
                [
                    {
                        "request_human_takeover": {
                            "reason": "Sign in with your username and password. After that I'll read the page.",
                            "category": "credentials",
                        }
                    }
                ]
            ),
            AgentStep(
                [
                    {
                        "done": {
                            "text": f"After signing in the page says {LOGIN_FLASH}",
                            "success": True,
                        }
                    }
                ],
                wait_for=LOGIN_FLASH,
                require=(LOGIN_FLASH,),
            ),
        ],
    )

    conversation_id, job_id = await _start(
        stack,
        user,
        f"Log me in at {login}; I'll type my username and password myself. Then tell me the message shown. {first}",
        login,
    )
    prompt = await wait_for(dm, _LIVE_LINK.pattern, timeout=RUN_SECONDS)
    live_match = _LIVE_LINK.search(prompt.said)
    assert live_match is not None
    await stack.in_live_page(job_id, _LOGIN_JS)
    await stack.page_reaches(job_id, "/secure")
    assert await stack.decide_on_live_page(live_match.group(1), "continue") == 200
    result = await stack.finished(job_id)
    await wait_for(dm, LOGIN_FLASH, timeout=RUN_SECONDS)
    await stack.settled(conversation_id)
    assert result.success, result

    # The next run on the site starts signed in: no second handoff.
    second = _marker()
    secure = stack.site.url("/secure")
    stack.models.script(
        second,
        jev=[JevMove("DONE")],
        agent=[
            AgentStep(
                [{"done": {"text": f"The heading is {SECURE_HEADING}", "success": True}}],
                require=(SECURE_HEADING,),
            )
        ],
    )
    asked_before = len(dm.matching(_LIVE_LINK.pattern))
    conversation_id, job_id = await _start(
        stack, user, f"Open {secure} and tell me its heading. {second}", secure
    )
    reuse = await stack.finished(job_id)
    await stack.settled(conversation_id)

    assert reuse.success, reuse
    assert len(dm.matching(_LIVE_LINK.pattern)) == asked_before, "the saved login was not reused"
    assert stack.models.errors == []


async def test_cancelling_a_captcha_handoff_stops_the_run_and_nothing_more_is_said(
    stack: BrowserStack,
) -> None:
    user = await stack.new_user()
    dm = await stack.watch(user.telegram_id)
    marker = _marker()
    page = stack.site.url("/captcha")
    stack.models.script(
        marker,
        jev=[JevMove("BLOCKED")],
        agent=[
            AgentStep(
                [
                    {
                        "solve_captcha_with_help": {
                            "challenge": "Tick I'm not a robot, then press Done."
                        }
                    }
                ]
            ),
        ],
    )

    conversation_id, job_id = await _start(
        stack, user, f"Open {page}, get past the check and tell me what it says. {marker}", page
    )
    prompt = await wait_for(dm, _LIVE_LINK.pattern, timeout=RUN_SECONDS)
    live_match = _LIVE_LINK.search(prompt.said)
    assert live_match is not None
    told_before = len(_told(dm))
    assert await stack.decide_on_live_page(live_match.group(1), "cancel") == 200
    result = await stack.finished(job_id)
    await stack.settled(conversation_id)

    assert result.status is BrowserSessionStatus.CANCELLED
    assert CAPTCHA_HEADING not in result.summary
    # teller: Cancel is a stop: the ending is STOPPED and nothing wakes to tell anything.
    assert await stack.ending(job_id) is JobEnding.STOPPED
    assert len(_told(dm)) == told_before, [d.text for d in _told(dm)]


async def test_a_captcha_on_a_site_the_user_never_named_is_skipped_not_handed_over(
    stack: BrowserStack,
) -> None:
    user = await stack.new_user()
    dm = await stack.watch(user.telegram_id)
    marker = _marker()
    page = stack.site.url("/partner-offers")
    stack.models.script(
        marker,
        jev=[JevMove("CLICK", "See the partner"), JevMove("BLOCKED")],
        agent=[
            AgentStep([{"solve_captcha_with_help": {"challenge": "Tick I'm not a robot."}}]),
            AgentStep(
                [{"done": {"text": "The partner's page could not be opened.", "success": False}}]
            ),
        ],
    )

    conversation_id, job_id = await _start(
        stack, user, f"Open {page} and tell me the partner's offer. {marker}", page
    )
    # runcore: a check on a host the user never named is skipped, never handed to them.
    await _until(
        lambda: _ended_or_handed_over(stack, user, job_id), "the run ending or handing over"
    )
    assert not await stack.handoff_waiting(user), (
        "the run handed an unnamed site's check to the user"
    )
    result = await stack.finished(job_id)
    await stack.settled(conversation_id)

    assert result.status is not BrowserSessionStatus.CANCELLED
    assert dm.matching(_LIVE_LINK.pattern) == []
    assert stack.models.errors == []


async def _a_run_that_waits(
    stack: BrowserStack, user: BotUser, *, channel_id: str | None = None
) -> tuple[str, str, str]:
    """Start a run whose agent waits until it is stopped; return its marker, conversation and job."""
    marker = _marker()
    home = stack.site.url("/")
    stack.models.script(
        marker,
        jev=[JevMove("DONE")],
        agent=[
            AgentStep(
                [{"done": {"text": "This run was never meant to finish.", "success": True}}],
                gate=asyncio.Event(),
                patience=600,
            )
        ],
    )
    conversation_id, job_id = await _start(
        stack, user, f"Open {home} and keep watching it. {marker}", home, channel_id=channel_id
    )
    await _until(lambda: _asked(stack, marker, 2), "the agent waiting on the page")
    return marker, conversation_id, job_id


async def _asked(stack: BrowserStack, marker: str, times: int) -> bool:
    return stack.models.calls_for(marker, "agent") >= times


async def _executor_idle(conversation_id: str) -> bool:
    return not await is_executor_busy(conversation_id)


async def _ended(stack: BrowserStack, job_id: str) -> bool:
    return await stack.ending(job_id) is not None


async def _moved(stack: BrowserStack, job_id: str) -> bool:
    return len(await stack.sessions_of(job_id)) == 2


async def _ended_or_handed_over(stack: BrowserStack, user: BotUser, job_id: str) -> bool:
    return await _ended(stack, job_id) or await stack.handoff_waiting(user)


async def test_a_stop_from_the_dm_ends_a_run_started_in_a_group_and_nothing_more_is_said(
    stack: BrowserStack,
) -> None:
    user = await stack.new_user()
    group_id = f"group-{uuid.uuid4().hex[:8]}"
    group = await stack.watch(group_id)
    dm = await stack.watch(user.telegram_id)
    marker, conversation_id, job_id = await _a_run_that_waits(stack, user, channel_id=group_id)
    told_before = len(_told(group)) + len(_told(dm))

    await stack.stop_command(user)
    result = await stack.finished(job_id)
    await stack.settled(conversation_id)
    asked = stack.models.calls_for(marker, "agent")
    await stack.settled(conversation_id)

    assert result.status is BrowserSessionStatus.CANCELLED
    assert await stack.ending(job_id) is JobEnding.STOPPED
    assert stack.models.calls_for(marker, "agent") == asked, "the agent kept running after the stop"
    # A group run's steps and handoffs go to the requester's DM, never the group.
    assert group.photos == [] and dm.photos
    # teller: a stopped run tells nothing more, anywhere.
    assert len(_told(group)) + len(_told(dm)) == told_before


async def test_a_stop_said_in_chat_stops_the_run(stack: BrowserStack) -> None:
    user = await stack.new_user()
    dm = await stack.watch(user.telegram_id)
    _, conversation_id, job_id = await _a_run_that_waits(stack, user)
    told_before = len(_told(dm))

    stops_before = stack.models.tool_calls.count("stop_browser_task")

    # reader: comms answers a stop by calling stop_browser_task on the chat's own job.
    await stack.say(user, "stop that [[tool:stop_browser_task {}]]")
    assert stack.models.tool_calls.count("stop_browser_task") == stops_before + 1
    result = await stack.finished(job_id)
    await stack.settled(conversation_id)

    assert result.status is BrowserSessionStatus.CANCELLED
    assert await stack.ending(job_id) is JobEnding.STOPPED
    assert len(_told(dm)) <= told_before + 1, "more than the stop's own reply was said"


async def test_what_the_user_adds_mid_run_reaches_the_run(stack: BrowserStack) -> None:
    user = await stack.new_user()
    dm = await stack.watch(user.telegram_id)
    marker = _marker()
    token = f"also-{uuid.uuid4().hex[:6]}"
    home = stack.site.url("/")
    stack.models.script(
        marker,
        jev=[JevMove("DONE")],
        agent=[
            AgentStep(
                [{"done": {"text": f"Fixture Domain, and noted {token}", "success": True}}],
                heard=token,
                patience=600,
                require=("Fixture Domain",),
            )
        ],
    )
    conversation_id, job_id = await _start(
        stack, user, f"Open {home} and tell me its heading. {marker}", home
    )
    await _until(lambda: _asked(stack, marker, 2), "the agent waiting on the page")

    tells_before = stack.models.tool_calls.count("tell_browser_task")

    # reader: comms passes what the user added to the running job with tell_browser_task.
    await stack.say(
        user, f"and note {token} [[tool:tell_browser_task {json.dumps({'text': token})}]]"
    )
    assert stack.models.tool_calls.count("tell_browser_task") == tells_before + 1
    result = await stack.finished(job_id)
    await wait_for(dm, token, timeout=RUN_SECONDS)
    await stack.settled(conversation_id)

    assert result.success, result
    assert stack.models.errors == []


async def test_a_run_whose_engine_dies_finishes_in_chrome(stack: BrowserStack) -> None:
    user = await stack.new_user()
    await stack.set_obscura(user)
    dm = await stack.watch(user.telegram_id)
    marker = _marker()
    form, home = stack.site.url("/form"), stack.site.url("/")
    moved = asyncio.Event()
    stack.models.script(
        marker,
        jev=[JevMove("TYPE_TEXT", "Text input", value="Aryan"), JevMove("DONE")],
        agent=[
            AgentStep([{"navigate": {"url": home}}], gate=moved, patience=600),
            AgentStep(
                [{"done": {"text": "The other page is Fixture Domain", "success": True}}],
                wait_for="Fixture Domain",
                require=("Fixture Domain",),
            ),
        ],
    )

    conversation_id, job_id = await _start(
        stack,
        user,
        f'Type "Aryan" into the form at {form}, then tell me the heading of {home}. {marker}',
        form,
    )
    await _until(lambda: _asked(stack, marker, 1), "the agent's first step on the fast engine")
    stack.kill_obscura_engine()
    await _until(lambda: _moved(stack, job_id), "the run opening its Chrome session")
    moved.set()
    result = await stack.finished(job_id)
    await wait_for(dm, "Fixture Domain", timeout=RUN_SECONDS)
    await stack.settled(conversation_id)

    assert result.success, result
    assert stack.models.errors == []


async def test_a_result_survives_its_worker_dying_right_after_the_run_ends(
    stack: BrowserStack,
) -> None:
    user = await stack.new_user()
    dm = await stack.watch(user.telegram_id)
    marker = _marker()
    home = stack.site.url("/")
    stack.models.script(
        marker,
        jev=[JevMove("DONE")],
        agent=[
            AgentStep(
                [{"done": {"text": "Its heading is Fixture Domain", "success": True}}],
                require=("Fixture Domain",),
            )
        ],
    )
    conversation_id, job_id = await _start(
        stack, user, f"Open {home} and tell me its heading. {marker}", home
    )
    # Whatever tells the result goes through a comms or executor model call: hold those, so the
    # worker dies with the run ended but its result not yet told.
    await _until(lambda: _executor_idle(conversation_id), "the starting turn's executor run ending")
    stack.models.agent_tier_open.clear()
    try:
        await _until(lambda: _ended(stack, job_id), "the run's ending being recorded")
        assert stack.worker is not None
        stack.worker.kill()
        await stack.worker.restart()
    finally:
        stack.models.agent_tier_open.set()

    # teller: the ending and the executor-inbox entry landed together, and the reaper tells it once.
    await wait_for(dm, "Fixture Domain", timeout=RUN_SECONDS)
    await stack.settled(conversation_id)
    assert len([d for d in _told(dm) if "Fixture Domain" in d.text]) == 1, dm.texts
