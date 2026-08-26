"""The ``<playbook_check>`` gate and where the block is delivered.

It exists to ask one question once: is this run worth freezing? So it must be
absent whenever the answer is already known (a playbook that replayed cleanly,
or one not yet tried) and present when it is not (no playbook, or one whose
last replay failed).

Where it is delivered is load-bearing too, and is pinned here: it rides in the
executor's brief, because ``write_playbook`` is an executor tool and comms —
which narrates the finished result — binds only call_executor/cancel_executor/
memory and is built with ``disable_retrieve_tools=True``. Delivered at
narration time it would ask the narrator for a tool it cannot reach.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.core.subagents.subagent_runner import compose_executor_brief
from app.agents.prompts.playbook_prompts import PLAYBOOK_CHECK_BRIEF
from app.models.playbook_models import PlaybookDocument, PlaybookRunStatus
from app.services.workflow.playbook.check import playbook_check_brief

MODULE = "app.services.workflow.playbook.check"
USER_ID = "user-1"
WORKFLOW_ID = "wf-1"


def _playbook(status: PlaybookRunStatus) -> PlaybookDocument:
    now = datetime.now(UTC)
    return PlaybookDocument(
        playbook_id="pb-1",
        workflow_id=WORKFLOW_ID,
        user_id=USER_ID,
        workflow_hash="h",
        raw_yaml="description: d\nsteps: []\nsynthesize: s\n",
        description="d",
        steps=[],
        synthesize="s",
        last_run_status=status,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_asks_when_the_workflow_has_no_playbook():
    with patch(f"{MODULE}.playbook_repository.get_for_workflow", AsyncMock(return_value=None)):
        assert await playbook_check_brief(WORKFLOW_ID, USER_ID) == PLAYBOOK_CHECK_BRIEF


@pytest.mark.asyncio
async def test_asks_again_when_the_last_replay_failed():
    playbook = _playbook(PlaybookRunStatus.FAILED)
    with patch(f"{MODULE}.playbook_repository.get_for_workflow", AsyncMock(return_value=playbook)):
        assert await playbook_check_brief(WORKFLOW_ID, USER_ID) == PLAYBOOK_CHECK_BRIEF


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [PlaybookRunStatus.SUCCESS, PlaybookRunStatus.NOT_RUN])
async def test_stays_silent_when_there_is_nothing_to_re_decide(status: PlaybookRunStatus):
    playbook = _playbook(status)
    with patch(f"{MODULE}.playbook_repository.get_for_workflow", AsyncMock(return_value=playbook)):
        assert await playbook_check_brief(WORKFLOW_ID, USER_ID) == ""


@pytest.mark.asyncio
async def test_a_lookup_failure_costs_the_check_not_the_run():
    with patch(
        f"{MODULE}.playbook_repository.get_for_workflow",
        AsyncMock(side_effect=RuntimeError("mongo down")),
    ):
        assert await playbook_check_brief(WORKFLOW_ID, USER_ID) == ""


def test_the_check_closes_the_executor_brief():
    brief = compose_executor_brief(
        "do the thing",
        ["it is done"],
        verbatim_request="please do the thing",
        last_run="<last_run>previously</last_run>",
        playbook_check=PLAYBOOK_CHECK_BRIEF,
    )
    assert brief.rstrip().endswith("</playbook_check>")
    assert brief.index("Definition of done") < brief.index("<playbook_check>")


def test_the_brief_is_unchanged_when_there_is_no_check():
    brief = compose_executor_brief("do the thing", ["it is done"], playbook_check="")
    assert "playbook_check" not in brief


def test_the_check_names_write_playbook_so_the_executor_can_act_on_it():
    # Regression: the block first shipped into comms narration, which binds only
    # call_executor/cancel_executor/memory. Naming the tool is what makes the
    # brief actionable, and the executor is the only tier that has it.
    assert "write_playbook" in PLAYBOOK_CHECK_BRIEF
