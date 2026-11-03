"""What counts as use, and that the dashboards' active-user action counts the same events."""

import json
from pathlib import Path

import pytest

from shared.py.analytics.activity import ACTIVE_USE_EVENTS, is_active_use
from shared.py.analytics.catalog import CATALOG
from shared.py.analytics.catalog.attribution import Actor, Attribution, EntrySurface, Trigger
from shared.py.analytics.catalog.auth import UserSignedUp
from shared.py.analytics.catalog.chat import ChatMessageSubmitted
from shared.py.analytics.catalog.workflows import WorkflowExecuted

REPO_ROOT = Path(__file__).resolve().parents[4]
ACTIONS_JSON = REPO_ROOT / "config" / "posthog" / "actions.json"
ACTIVE_USER_ACTION = "Active user (human)"

USER = Attribution(actor=Actor.USER, trigger=Trigger.INTERACTIVE, surface=EntrySurface.BOT)
AGENT = Attribution(actor=Actor.AGENT, trigger=Trigger.SCHEDULE, surface=EntrySurface.WORKER)
SUBMITTED = ChatMessageSubmitted(source="telegram", has_files=False, stream_id="s", is_retry=False)


def _current_name(name: str) -> str:
    return next((event for event, model in CATALOG.items() if name in model.previous_names), name)


def test_the_active_user_action_counts_exactly_the_events_that_mark_a_day_active() -> None:
    actions = json.loads(ACTIONS_JSON.read_text())["actions"]
    [action] = [a for a in actions if a["name"] == ACTIVE_USER_ACTION]

    steps = {_current_name(step["event"]) for step in action["steps"]}

    assert steps == {model.event for model in ACTIVE_USE_EVENTS}


@pytest.mark.parametrize("event", [SUBMITTED, WorkflowExecuted()])
def test_a_message_or_a_workflow_run_by_the_user_is_use(
    event: ChatMessageSubmitted | WorkflowExecuted,
) -> None:
    assert is_active_use(event, USER)


def test_the_same_event_done_by_the_agent_is_not() -> None:
    assert not is_active_use(WorkflowExecuted(trigger_type="schedule"), AGENT)


def test_a_signup_is_not_use() -> None:
    assert not is_active_use(UserSignedUp(), USER)
