"""An old hand-written attempt is re-expressed as picks the pick flow can build, or says why not."""

from scripts.playbook_corpus.replay import entries, replay
from scripts.playbook_corpus.translate import Unmappable, translate

from app.models.workflow_execution_models import RecordedCall, build_result_digest


def _handoff(subagent: str, task: str) -> RecordedCall:
    return RecordedCall(
        tool_name="handoff",
        args={"subagent_id": subagent, "task": task},
        result_digest=build_result_digest(f"{subagent} has two open items"),
    )


def _group(handoff: str, child_id: str, task: str) -> dict[str, list[dict[str, object]] | str]:
    args = {"subagent_id": handoff, "task": task}
    return {"handoff": handoff, "steps": [{"id": child_id, "tool": "handoff", "args": args}]}


async def test_the_same_child_id_in_two_handoff_groups_builds_two_steps() -> None:
    record = entries([_handoff("linear", "Linear status"), _handoff("github", "GitHub status")], 2)
    steps = [
        _group("linear", "gather", "Linear status"),
        _group("github", "gather", "GitHub status"),
    ]

    translation = translate({"steps": steps}, record, frozenset())
    outcome = await replay("Status", translation.picks, "", record)

    assert translation.unmappable is None
    assert len({pick.id for pick in translation.picks}) == 2
    assert outcome.refusals == []


def test_a_reference_inside_a_renamed_group_follows_its_own_child() -> None:
    calls = [
        _handoff("linear", "Linear status"),
        _handoff("github", "GitHub status"),
        _handoff("github", "Post the status"),
    ]
    post = {"subagent_id": "github", "task": "Post $steps.gather.summary"}
    github = _group("github", "gather", "GitHub status")
    github["steps"] = [*github["steps"], {"id": "post", "tool": "handoff", "args": post}]
    steps = [_group("linear", "gather", "Linear status"), github]

    picks = translate({"steps": steps}, entries(calls, 3), frozenset()).picks

    assert [pick.id for pick in picks] == ["gather", "github_gather", "post"]
    assert picks[2].vary["task"] == "Post $steps.github_gather.summary"


def test_a_handoff_step_with_a_blank_tool_and_no_children_says_which_handoff() -> None:
    record = entries(
        [RecordedCall(tool_name="search_memory", result_digest=build_result_digest("a memory"))], 1
    )
    steps = [{"id": "calendar", "tool": "", "handoff": "googlecalendar", "args": {"task": "t"}}]

    translation = translate({"steps": steps}, record, frozenset())

    assert (translation.unmappable, translation.detail) == (
        Unmappable.HANDOFF_WITHOUT_STEPS,
        "googlecalendar",
    )
