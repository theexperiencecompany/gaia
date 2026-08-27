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
from pathlib import Path
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError
import pytest

from app.agents.core.subagents.subagent_runner import compose_executor_brief
from app.agents.prompts.playbook_prompts import (
    PLAYBOOK_CHECK_BRIEF,
    PLAYBOOK_HEAL_BRIEF,
    PLAYBOOK_SUSPECT_FALLBACK_TEMPLATE,
)
from app.agents.tools.playbook_tools import write_playbook
from app.constants.agents import PLAYBOOK_DECLINE_LIMIT
from app.models.playbook_models import (
    PlaybookDocument,
    PlaybookRunStatus,
    PlaybookStep,
    PlaybookStepInput,
)
from app.models.workflow_models import TriggerConfig, TriggerType, WorkflowDocument
from app.services.workflow.playbook.check import playbook_check_brief
from app.services.workflow.playbook.workflow_hash import workflow_hash

MODULE = "app.services.workflow.playbook.check"
USER_ID = "user-1"
WORKFLOW_ID = "wf-1"


def _workflow(*, declines: int = 0, declined_hash: str | None = None) -> WorkflowDocument:
    return WorkflowDocument(
        id=WORKFLOW_ID,
        user_id=USER_ID,
        title="Daily agenda",
        prompt="Mail the agenda",
        steps=[],
        trigger_config=TriggerConfig(type=TriggerType.SCHEDULE, enabled=True),
        playbook_declines=declines,
        playbook_declined_hash=declined_hash,
    )


@pytest.fixture(autouse=True)
def _workflow_lookup():
    """The workflow read behind the decline gate; a fresh workflow by default."""
    with patch(
        f"{MODULE}.workflow_repository.get_for_user", AsyncMock(return_value=_workflow())
    ) as lookup:
        yield lookup


def _playbook(status: PlaybookRunStatus, reason: str | None = None) -> PlaybookDocument:
    now = datetime.now(UTC)
    return PlaybookDocument(
        playbook_id="pb-1",
        workflow_id=WORKFLOW_ID,
        user_id=USER_ID,
        workflow_hash="h",
        description="d",
        steps=[PlaybookStep(id="s1", tool="create_todo", args={})],
        synthesize="s",
        last_run_status=status,
        last_run_reason=reason,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_asks_when_the_workflow_has_no_playbook():
    with patch(f"{MODULE}.playbook_repository.get_for_workflow", AsyncMock(return_value=None)):
        assert await playbook_check_brief(WORKFLOW_ID, USER_ID) == PLAYBOOK_CHECK_BRIEF


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [PlaybookRunStatus.FAILED, PlaybookRunStatus.SUSPECT])
async def test_asks_to_heal_when_the_last_replay_did_not_hold(status: PlaybookRunStatus):
    """A broken playbook is healed, not re-decided from scratch.

    The agent gets the recorded reason and is told to read the stored sequence,
    so it fixes the step that went wrong instead of rediscovering everything.
    """
    reason = "step events (list_events) returned no items"
    playbook = _playbook(status, reason)
    with patch(f"{MODULE}.playbook_repository.get_for_workflow", AsyncMock(return_value=playbook)):
        brief = await playbook_check_brief(WORKFLOW_ID, USER_ID)

    assert brief != PLAYBOOK_CHECK_BRIEF
    assert brief.startswith("<playbook_check>")
    assert brief.rstrip().endswith("</playbook_check>")
    assert reason in brief
    assert "read_playbook" in brief


@pytest.mark.asyncio
async def test_the_heal_brief_says_whether_the_replay_stopped_or_was_not_trusted():
    """Same loop, different diagnosis: a stop points at a call that broke, a
    suspect result at a call that answered with the wrong thing."""
    with patch(
        f"{MODULE}.playbook_repository.get_for_workflow",
        AsyncMock(return_value=_playbook(PlaybookRunStatus.FAILED, "boom")),
    ):
        failed = await playbook_check_brief(WORKFLOW_ID, USER_ID)
    with patch(
        f"{MODULE}.playbook_repository.get_for_workflow",
        AsyncMock(return_value=_playbook(PlaybookRunStatus.SUSPECT, "empty")),
    ):
        suspect = await playbook_check_brief(WORKFLOW_ID, USER_ID)

    assert "stopped partway" in failed
    assert "not trusted" in suspect
    assert failed != suspect


@pytest.mark.asyncio
async def test_a_missing_reason_is_said_plainly_rather_than_rendered_as_none():
    playbook = _playbook(PlaybookRunStatus.FAILED, None)
    with patch(f"{MODULE}.playbook_repository.get_for_workflow", AsyncMock(return_value=playbook)):
        brief = await playbook_check_brief(WORKFLOW_ID, USER_ID)

    assert "None" not in brief
    assert "no reason was recorded" in brief


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


@pytest.mark.asyncio
async def test_a_swallowed_lookup_failure_is_still_reported():
    """The one swallow in this path must stay visible in the wide event.

    Returning "" on a lookup failure is deliberate, but a silent swallow would
    make a permanently broken playbooks collection look exactly like a workflow
    that simply never qualified — the check would stop happening and nothing
    anywhere would say why.
    """
    with (
        patch(
            f"{MODULE}.playbook_repository.get_for_workflow",
            AsyncMock(side_effect=RuntimeError("mongo down")),
        ),
        patch(f"{MODULE}.log.warning") as warning,
    ):
        await playbook_check_brief(WORKFLOW_ID, USER_ID)

    warning.assert_called_once()
    message, kwargs = warning.call_args[0][0], warning.call_args[1]
    assert "playbook_check_brief" in message
    assert "lookup failed" in message
    assert kwargs["workflow_id"] == WORKFLOW_ID
    assert kwargs["error_type"] == "RuntimeError"
    assert kwargs["error"] == "mongo down"


@pytest.mark.asyncio
class TestDeclinesAreRemembered:
    """Declining used to persist nothing, so a workflow whose order genuinely
    varies was asked the ~600-token question on every fire, forever."""

    def _hash(self) -> str:
        workflow = _workflow()
        return workflow_hash(workflow.prompt, workflow.steps)

    async def test_stays_silent_after_the_limit_on_the_same_workflow(self, _workflow_lookup):
        _workflow_lookup.return_value = _workflow(
            declines=PLAYBOOK_DECLINE_LIMIT, declined_hash=self._hash()
        )
        with patch(f"{MODULE}.playbook_repository.get_for_workflow", AsyncMock(return_value=None)):
            assert await playbook_check_brief(WORKFLOW_ID, USER_ID) == ""

    async def test_keeps_asking_below_the_limit(self, _workflow_lookup):
        _workflow_lookup.return_value = _workflow(
            declines=PLAYBOOK_DECLINE_LIMIT - 1, declined_hash=self._hash()
        )
        with patch(f"{MODULE}.playbook_repository.get_for_workflow", AsyncMock(return_value=None)):
            assert await playbook_check_brief(WORKFLOW_ID, USER_ID) == PLAYBOOK_CHECK_BRIEF

    async def test_asks_again_once_the_workflow_is_edited(self, _workflow_lookup):
        """The declines were about a different workflow; an edit changes the hash."""
        _workflow_lookup.return_value = _workflow(
            declines=PLAYBOOK_DECLINE_LIMIT, declined_hash="hash-of-the-workflow-before-the-edit"
        )
        with patch(f"{MODULE}.playbook_repository.get_for_workflow", AsyncMock(return_value=None)):
            assert await playbook_check_brief(WORKFLOW_ID, USER_ID) == PLAYBOOK_CHECK_BRIEF

    async def test_a_stored_playbook_never_consults_the_declines(self, _workflow_lookup):
        _workflow_lookup.return_value = _workflow(
            declines=PLAYBOOK_DECLINE_LIMIT, declined_hash=self._hash()
        )
        with patch(
            f"{MODULE}.playbook_repository.get_for_workflow",
            AsyncMock(return_value=_playbook(PlaybookRunStatus.FAILED, "boom")),
        ):
            brief = await playbook_check_brief(WORKFLOW_ID, USER_ID)

        assert "boom" in brief
        _workflow_lookup.assert_not_awaited()


FALLBACK_NOTE = (
    "<playbook_fallback>\n"
    "The playbook for this workflow was replayed first and it stopped partway.\n\n"
    "Playbook stopped at step 2 (send_email): rejected argument 'body'.\n\n"
    "These steps ALREADY RAN in this same execution, and their effects are real:\n"
    "- events (list_events) -> 12 events\n\n"
    "Do not repeat them. Pick up from where the replay stopped and finish the workflow.\n"
    "</playbook_fallback>"
)


@pytest.mark.asyncio
class TestSameFireFallbackBrief:
    """A replay that stops partway is finished by the agent in the same fire.

    ``call_executor`` then saw FAILED and injected the heal brief ("do the work
    properly yourself") while the "these steps ALREADY RAN" note only reached
    comms. The executor read one without the other and repeated side effects.
    """

    async def test_the_heal_brief_carries_the_already_ran_record_verbatim(self):
        playbook = _playbook(PlaybookRunStatus.FAILED, "stopped at step 2")
        with patch(
            f"{MODULE}.playbook_repository.get_for_workflow", AsyncMock(return_value=playbook)
        ):
            brief = await playbook_check_brief(WORKFLOW_ID, USER_ID, fallback_note=FALLBACK_NOTE)

        assert FALLBACK_NOTE in brief
        assert brief.startswith("<playbook_check>")
        assert brief.rstrip().endswith("</playbook_check>")
        assert "read_playbook" in brief, "still the heal brief"
        assert brief.index("stopped at step 2") < brief.index(FALLBACK_NOTE)
        assert brief.index(FALLBACK_NOTE) < brief.index("Do not lean on the playbook")

    async def test_without_a_note_the_heal_brief_has_no_already_ran_block(self):
        playbook = _playbook(PlaybookRunStatus.FAILED, "stopped at step 2")
        with patch(
            f"{MODULE}.playbook_repository.get_for_workflow", AsyncMock(return_value=playbook)
        ):
            brief = await playbook_check_brief(WORKFLOW_ID, USER_ID)

        assert "same execution" not in brief
        assert "\n\n\n" not in brief, "the empty slot must not leave a hole in the prompt"

    async def test_a_note_reaches_the_executor_even_when_the_outcome_did_not_land(self):
        """The note is proof the replay stopped this fire, whatever the stored status says."""
        playbook = _playbook(PlaybookRunStatus.SUCCESS)
        with patch(
            f"{MODULE}.playbook_repository.get_for_workflow", AsyncMock(return_value=playbook)
        ):
            brief = await playbook_check_brief(WORKFLOW_ID, USER_ID, fallback_note=FALLBACK_NOTE)

        assert FALLBACK_NOTE in brief

    async def test_a_note_with_no_playbook_left_still_reaches_the_executor(self):
        with patch(f"{MODULE}.playbook_repository.get_for_workflow", AsyncMock(return_value=None)):
            brief = await playbook_check_brief(WORKFLOW_ID, USER_ID, fallback_note=FALLBACK_NOTE)

        assert brief.startswith(FALLBACK_NOTE)
        assert brief.endswith(PLAYBOOK_CHECK_BRIEF)


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


def test_the_check_names_both_decision_tools_so_the_executor_can_act():
    # Regression: the block first shipped into comms narration, which binds only
    # call_executor/cancel_executor/memory. Naming the tool is what makes the
    # brief actionable, and the executor is the only tier that has it.
    assert "write_playbook" in PLAYBOOK_CHECK_BRIEF
    # A decision is mandatory now: silence used to be how "no" was expressed,
    # which made a model lapse indistinguishable from a considered decline.
    assert "decline_playbook" in PLAYBOOK_CHECK_BRIEF
    assert "exactly one of" in PLAYBOOK_CHECK_BRIEF


def test_the_check_asks_whether_every_frozen_call_actually_returned_the_data():
    # Regression: a playbook froze a call that came back empty, because the
    # agent had reasoned around the gap and the sequence still "worked". The
    # sixth question makes an empty, errored or partial result a reason to fix
    # the args or decline, and the decision rule has to read against it.
    assert "6." in PLAYBOOK_CHECK_BRIEF
    assert "these six" in PLAYBOOK_CHECK_BRIEF
    assert "came back empty, with an error, or partial" in PLAYBOOK_CHECK_BRIEF
    assert "If 5 and 6 are both yes, call write_playbook" in PLAYBOOK_CHECK_BRIEF
    assert "If either 5 or 6 is no, call decline_playbook" in PLAYBOOK_CHECK_BRIEF
    assert "exactly one of write_playbook or decline_playbook" in PLAYBOOK_CHECK_BRIEF


def test_the_heal_brief_names_the_tools_the_executor_needs():
    # read_playbook to see the sequence, then exactly one of the two verdicts.
    # decline_playbook is the wrong tool here: there is a stored playbook, so
    # "no" means disabling it, not declining to write one.
    assert "read_playbook" in PLAYBOOK_HEAL_BRIEF
    assert "write_playbook" in PLAYBOOK_HEAL_BRIEF
    assert "disable_playbook" in PLAYBOOK_HEAL_BRIEF
    assert "decline_playbook" not in PLAYBOOK_HEAL_BRIEF
    assert "exactly one of write_playbook or disable_playbook" in PLAYBOOK_HEAL_BRIEF
    assert "{reason}" in PLAYBOOK_HEAL_BRIEF
    assert "\u2014" not in PLAYBOOK_HEAL_BRIEF, "no em dashes in model-facing text"
    assert "\u2014" not in PLAYBOOK_CHECK_BRIEF


def test_the_heal_brief_makes_the_agent_probe_before_accepting_an_empty_result():
    # A heal run that re-ran the frozen call, got nothing again, and rewrote
    # the same sequence proved nothing: the call may simply be asking the
    # wrong question. Emptiness has to be established more broadly than the
    # frozen call before the same sequence is written back.
    assert "probing more broadly than the frozen call" in PLAYBOOK_HEAL_BRIEF
    assert "a longer window, the filter dropped" in PLAYBOOK_HEAL_BRIEF
    assert "Say in the result what you checked" in PLAYBOOK_HEAL_BRIEF
    assert "Only a broader probe that also comes back empty" in PLAYBOOK_HEAL_BRIEF
    assert "the rewrite must use the args that found them" in PLAYBOOK_HEAL_BRIEF
    assert "—" not in PLAYBOOK_HEAL_BRIEF


def test_the_heal_brief_demands_a_decision_even_when_no_more_calls_are_needed():
    # Seen live: two of six fallback agents answered the user from the steps
    # that had already run, made no further calls, and ended without a
    # decision. "No work left" is exactly when the decision gets forgotten.
    for text in (PLAYBOOK_HEAL_BRIEF, PLAYBOOK_SUSPECT_FALLBACK_TEMPLATE):
        assert "even if you make no further calls" in text
        assert "—" not in text


def test_the_check_points_at_the_handoff_result_for_a_handoffs_nested_steps():
    # A handoff step must carry the calls its subagent ran, and the only place
    # the executor can copy them from is the handoff's own result record.
    assert "record of the calls" in PLAYBOOK_CHECK_BRIEF
    assert "nested steps" in PLAYBOOK_CHECK_BRIEF


def test_write_playbook_is_statically_bound_to_the_executor():
    """The check names write_playbook, so the executor must always be able to call it.

    Regression: the tool was registered in a ToolCategory and left to
    ``retrieve_tools`` semantic retrieval. On a machine whose tool index was
    incomplete it was never surfaced, so every run read the instruction and
    silently authored nothing. A prompt that names a tool by hand needs that
    tool bound by hand.
    """
    source = (
        Path(__file__).resolve().parents[4]
        / "app"
        / "agents"
        / "core"
        / "graph_builder"
        / "build_graph.py"
    ).read_text(encoding="utf-8")
    executor_block = source.split('agent_name="executor_agent"', 1)[1].split("]", 1)[0]

    assert '"write_playbook"' in executor_block
    assert '"decline_playbook"' in executor_block


def test_the_tools_own_schema_carries_the_step_shape():
    """The binding, not the prompt, is what teaches the model the shape.

    Regression: the playbook arrived as one opaque YAML string, so the bound
    schema said only "argument 2 is a string" and a live run invented a `goal`
    field three times running. The structure has to be in the schema, and a key
    that is not in it has to be refused.
    """
    schema = write_playbook.tool_call_schema.model_json_schema()

    assert {"description", "steps", "synthesize", "ask"} <= set(schema["properties"])
    # The workflow is resolved from the run's config server-side. Exposing it as
    # an argument is what let a live run hallucinate "inbox-triage" as an id.
    assert "workflow_id" not in schema["properties"]
    step = schema["$defs"][PlaybookStepInput.__name__]
    assert {"id", "tool", "args", "handoff", "steps"} <= set(step["properties"])

    child_name = step["properties"]["steps"]["items"]["$ref"].rsplit("/", 1)[-1]
    child = schema["$defs"][child_name]
    assert {"id", "tool", "args"} <= set(child["properties"])
    # Depth-1 by construction: the child cannot carry steps, so the schema has
    # no self-$ref for a provider to mishandle.
    assert "steps" not in child["properties"]

    with pytest.raises(ValidationError, match="goal"):
        PlaybookStepInput.model_validate({"id": "agenda", "goal": "read the events"})
