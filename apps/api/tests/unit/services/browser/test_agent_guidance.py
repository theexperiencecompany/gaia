"""What a blocked run shows the executor that has to unstick it."""

from __future__ import annotations

import pytest

from app.constants.browser import BROWSER_GUIDANCE_ANSWER, BROWSER_GUIDANCE_HEADER
from app.schemas.browser import (
    AgentGuidanceRequest,
    GuidanceAction,
    GuidanceElement,
    PendingAgentGuidance,
)
from app.services.browser.agent_guidance import (
    clear_guidance_request,
    get_guidance_request,
    guidance_message,
    put_guidance_request,
)
from app.services.browser.job_lifetime import browser_job_ttl_seconds

pytestmark = pytest.mark.unit


def _request(**extra: object) -> AgentGuidanceRequest:
    return AgentGuidanceRequest(
        reason="The upvote control is not on this screen.",
        task="Upvote the top post on r/python",
        url="https://www.reddit.com/r/python",
        title="r/python",
        **extra,  # type: ignore[arg-type]  # the test varies one optional field per case
    )


def test_the_changed_instruction_is_stated_before_the_task_it_overrides() -> None:
    """Regression: guidance was written against the original task, so it sent the run back to the login the user had cancelled."""
    note = "skip the upvote, just tell me the title of the top post"

    message = guidance_message(_request(user_notes=[note]))

    assert note in message
    assert message.index(note) < message.index("Upvote the top post on r/python")


def test_the_guidance_is_told_never_to_send_the_run_back_to_a_declined_step() -> None:
    message = guidance_message(_request(user_notes=["skip the upvote, just tell me the title"]))

    assert "declined" in message.lower()


def test_a_run_nobody_redirected_is_told_nothing_about_a_changed_instruction() -> None:
    message = guidance_message(_request())

    assert "changed the instruction" not in message.lower()
    assert "Upvote the top post on r/python" in message


def test_every_instruction_the_user_sent_reaches_the_guidance() -> None:
    message = guidance_message(_request(user_notes=["skip the upvote", "just read the title"]))

    assert "skip the upvote" in message
    assert "just read the title" in message


def _sections(message: str) -> list[str]:
    return message.split("\n\n")


def test_a_bare_request_sends_only_the_parts_it_has() -> None:
    """Nothing seen, tried or redirected: no empty headings, and the page is named as unknown rather than blank."""
    message = guidance_message(
        AgentGuidanceRequest(reason="Blocked by a wall.", task="Read the post")
    )

    assert _sections(message) == [
        BROWSER_GUIDANCE_HEADER,
        "Why it is stuck: Blocked by a wall.",
        "Task it is working on: Read the post",
        "Page it is on: untitled (no url)",
        BROWSER_GUIDANCE_ANSWER,
    ]


def test_the_page_is_named_by_its_title_and_address() -> None:
    message = guidance_message(_request())

    assert "Page it is on: r/python (https://www.reddit.com/r/python)" in _sections(message)


def test_the_user_notes_reach_the_guidance_in_the_order_they_were_sent() -> None:
    message = guidance_message(_request(user_notes=["skip the upvote", "just read the title"]))

    assert '"skip the upvote", then "just read the title"' in message


def test_each_recent_action_says_whether_it_moved_the_page() -> None:
    actions = [
        GuidanceAction(action="click Upvote", page_changed=True),
        GuidanceAction(action="type hello", page_changed=False),
        GuidanceAction(action="scroll down"),
    ]

    (section,) = [
        s
        for s in _sections(guidance_message(_request(recent_actions=actions)))
        if "click Upvote" in s
    ]

    assert section.splitlines()[1:] == [
        "  - click Upvote (the page changed)",
        "  - type hello (the page did not change)",
        "  - scroll down",
    ]


def test_each_visible_control_is_listed_by_the_index_the_run_acts_on() -> None:
    elements = [
        GuidanceElement(index=3, label="Upvote", role="button"),
        GuidanceElement(index=7, label="Search", role="textbox"),
    ]

    (section,) = [
        s for s in _sections(guidance_message(_request(elements=elements))) if "[3] Upvote" in s
    ]

    assert section.splitlines()[1:] == ["  [3] Upvote (button)", "  [7] Search (textbox)"]


def test_the_screen_text_is_passed_on_when_the_run_has_it() -> None:
    message = guidance_message(_request(page_text="Log in to vote"))

    assert "Text on this screen:\nLog in to vote" in _sections(message)


async def test_a_published_request_is_read_back_by_its_job_only(fake_redis) -> None:
    pending = PendingAgentGuidance(handoff_id="h-1", request=_request(page_text="Log in"))

    await put_guidance_request("job-1", pending)

    assert await get_guidance_request("job-1") == pending
    assert await get_guidance_request("job-2") is None


async def test_a_request_outlives_the_run_that_waits_on_it_and_no_longer(fake_redis) -> None:
    await put_guidance_request("job-1", PendingAgentGuidance(handoff_id="h-1", request=_request()))

    (key,) = await fake_redis.keys("*")
    # A request that expired while its run still waits could never be answered.
    assert browser_job_ttl_seconds() - 5 <= await fake_redis.ttl(key) <= browser_job_ttl_seconds()


async def test_a_withdrawn_request_is_no_longer_answerable(fake_redis) -> None:
    await put_guidance_request("job-1", PendingAgentGuidance(handoff_id="h-1", request=_request()))
    await put_guidance_request("job-2", PendingAgentGuidance(handoff_id="h-2", request=_request()))

    await clear_guidance_request("job-1")

    assert await get_guidance_request("job-1") is None
    assert await get_guidance_request("job-2") is not None
