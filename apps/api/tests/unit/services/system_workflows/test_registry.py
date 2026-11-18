"""What the engine reads for each system workflow: the briefs' declared behaviour, a user's for the rest."""

import pytest

from app.constants.briefing import DAILY_BRIEFING_WORKFLOW_KEY, WEEKLY_DIGEST_WORKFLOW_KEY
from app.models.user_models import UserDocument
from app.services.system_workflows.behaviour import USER_WORKFLOW_BEHAVIOUR
from app.services.system_workflows.registry import (
    UNLISTED_KEYS,
    UNPAUSABLE_KEYS,
    behaviour_of,
)

pytestmark = pytest.mark.unit

BRIEF_KEYS = (DAILY_BRIEFING_WORKFLOW_KEY, WEEKLY_DIGEST_WORKFLOW_KEY)


@pytest.mark.parametrize("key", [None, "calendar:meeting_prep", "unknown"])
def test_a_workflow_without_a_declaration_is_treated_as_the_users(key: str | None) -> None:
    assert behaviour_of(key) is USER_WORKFLOW_BEHAVIOUR


@pytest.mark.parametrize("key", BRIEF_KEYS)
def test_a_brief_is_unlisted_unpausable_and_silent_on_failure(key: str) -> None:
    behaviour = behaviour_of(key)

    assert (behaviour.listed, behaviour.pausable, behaviour.notify_on_failure) == (
        False,
        False,
        False,
    )


@pytest.mark.parametrize(
    ("key", "cron"),
    [(DAILY_BRIEFING_WORKFLOW_KEY, "0 8 * * *"), (WEEKLY_DIGEST_WORKFLOW_KEY, "0 17 * * 0")],
)
def test_a_brief_runs_on_the_cron_its_users_schedule_gives_it(key: str, cron: str) -> None:
    cron_for = behaviour_of(key).cron_for

    assert cron_for is not None
    assert cron_for(UserDocument(id="u1")) == cron


def test_the_key_sets_the_engine_filters_by_are_the_briefs() -> None:
    assert UNLISTED_KEYS == UNPAUSABLE_KEYS == frozenset(BRIEF_KEYS)
