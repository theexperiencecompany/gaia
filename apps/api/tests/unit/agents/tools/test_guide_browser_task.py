"""The executor's answer to a stuck browser run: what reaches the run, and what it is told when nothing is waiting.

The failure paths are the point here: an instruction sent at a run that is not
waiting resolves nothing, and the model has to hear that rather than go on
believing the browser was told something.
"""

from langchain_core.runnables.config import RunnableConfig
import pytest

from app.agents.tools import browser_tool as tool_mod
from app.agents.tools.browser_tool import guide_browser_task
from app.constants.browser import HandoffDecision, HandoffStatus
from app.constants.log_tags import LogTag
from app.schemas.browser import AgentGuidanceRequest, PendingAgentGuidance
from tests.helpers import captured_wide_event

pytestmark = pytest.mark.unit

UI_CONFIG: RunnableConfig = {
    "configurable": {"user_id": "u1", "thread_id": "c1", "stream_id": "s1"}
}

STUCK = PendingAgentGuidance(
    handoff_id="h-1",
    request=AgentGuidanceRequest(reason="no date fits", task="book a table"),
)


class Guided:
    """What the answer did to the handoff and to the pending request."""

    def __init__(self) -> None:
        self.resolved: list[tuple[str, HandoffDecision, str, str | None]] = []
        self.cleared: list[str] = []
        self.refreshed: list[tuple[str, str]] = []
        self.asked_conversations: list[str] = []
        self.asked_jobs: list[str] = []


def _install(
    monkeypatch: pytest.MonkeyPatch,
    *,
    slot: str | None = "job-1",
    pending: PendingAgentGuidance | None = STUCK,
    status: HandoffStatus | None = HandoffStatus.COMPLETED,
) -> Guided:
    g = Guided()

    async def _slot(conversation_id: str) -> str | None:
        g.asked_conversations.append(conversation_id)
        return slot

    async def _pending(job_id: str) -> PendingAgentGuidance | None:
        g.asked_jobs.append(job_id)
        return pending

    async def _resolve(
        handoff_id: str, decision: HandoffDecision, user_id: str, message: str | None = None
    ) -> HandoffStatus | None:
        g.resolved.append((handoff_id, decision, user_id, message))
        return status

    async def _clear(job_id: str) -> None:
        g.cleared.append(job_id)

    async def _refresh(job_id: str, stream_id: str) -> None:
        g.refreshed.append((job_id, stream_id))

    monkeypatch.setattr(tool_mod, "get_conversation_slot", _slot)
    monkeypatch.setattr(tool_mod, "get_guidance_request", _pending)
    monkeypatch.setattr(tool_mod, "resolve_handoff", _resolve)
    monkeypatch.setattr(tool_mod, "clear_guidance_request", _clear)
    monkeypatch.setattr(tool_mod, "refresh_joiner_lease", _refresh)
    return g


async def test_an_instruction_reaches_the_waiting_run_as_its_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    g = _install(monkeypatch)

    out = await guide_browser_task.ainvoke(
        {"instruction": "  open the Contact tab  "}, config=UI_CONFIG
    )

    assert g.resolved == [("h-1", HandoffDecision.CONTINUE, "u1", "open the Contact tab")]
    assert "wait_for_browser_task" in out


async def test_giving_up_cancels_the_pause_and_carries_the_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cancel with no reason leaves the user a failure card that says nothing about why."""
    g = _install(monkeypatch)

    await guide_browser_task.ainvoke(
        {"give_up": True, "reason": "the site needs an account"}, config=UI_CONFIG
    )

    assert g.resolved == [("h-1", HandoffDecision.CANCEL, "u1", "the site needs an account")]


async def test_answering_withdraws_the_request_so_the_next_join_is_not_asked_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The run clears it too, but a join landing in that window would be handed the same stuck page and spend another instruction on it."""
    g = _install(monkeypatch)

    await guide_browser_task.ainvoke({"instruction": "click Search"}, config=UI_CONFIG)

    assert g.cleared == ["job-1"]


async def test_the_turns_claim_on_the_result_is_re_armed_while_it_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A model call sits between the ask and this answer; an expired lease lets the worker narrate the run behind the executor's back."""
    g = _install(monkeypatch)

    await guide_browser_task.ainvoke({"instruction": "click Search"}, config=UI_CONFIG)

    assert g.refreshed == [("job-1", "s1")]


@pytest.mark.parametrize(
    ("slot", "pending"),
    [(None, STUCK), ("job-1", None)],
)
async def test_guiding_a_run_that_is_not_waiting_says_so_instead_of_resolving_anything(
    monkeypatch: pytest.MonkeyPatch, slot: str | None, pending: PendingAgentGuidance | None
) -> None:
    g = _install(monkeypatch, slot=slot, pending=pending)

    out = await guide_browser_task.ainvoke({"instruction": "click Search"}, config=UI_CONFIG)

    assert "No browser task is waiting for guidance" in out
    assert g.resolved == []


async def test_an_empty_instruction_is_refused_rather_than_sent_as_an_empty_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty note resolves the pause with nothing to act on, and the run would block again on the same page having lost one of its three tries."""
    g = _install(monkeypatch)

    out = await guide_browser_task.ainvoke({"instruction": "   "}, config=UI_CONFIG)

    assert "An instruction is required" in out
    assert g.resolved == []


async def test_a_pause_that_already_ended_is_reported_rather_than_confirmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Confirming an instruction that landed nowhere would have the executor wait on a run already reporting a failure."""
    _install(monkeypatch, status=None)

    out = await guide_browser_task.ainvoke({"instruction": "click Search"}, config=UI_CONFIG)

    assert "stopped waiting for guidance" in out


async def test_an_instruction_is_confirmed_as_sent_and_the_request_is_the_conversations_own(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    g = _install(monkeypatch)

    async with captured_wide_event() as event:
        out = await guide_browser_task.ainvoke({"instruction": "click Search"}, config=UI_CONFIG)

    assert out == tool_mod._INSTRUCTION_SENT
    assert g.asked_conversations == ["c1"]
    assert g.asked_jobs == ["job-1"]
    assert event["browser"] == {"operation": "guide"}


async def test_only_an_instruction_given_is_sent_as_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The raw coroutine, so its own defaults decide: the schema the model sees is read from them."""
    g = _install(monkeypatch)

    assert await guide_browser_task.coroutine(config=UI_CONFIG) == tool_mod._INSTRUCTION_REQUIRED
    await guide_browser_task.coroutine(config=UI_CONFIG, instruction="click Search")

    assert g.resolved == [("h-1", HandoffDecision.CONTINUE, "u1", "click Search")]


async def test_giving_up_without_a_reason_invents_none_and_withdraws_the_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    g = _install(monkeypatch)

    out = await guide_browser_task.coroutine(config=UI_CONFIG, give_up=True)

    assert out == tool_mod._TOLD_TO_STOP
    assert g.resolved == [("h-1", HandoffDecision.CANCEL, "u1", "")]
    assert g.cleared == ["job-1"]


async def test_a_turn_with_no_stream_still_re_arms_its_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    g = _install(monkeypatch)

    await guide_browser_task.ainvoke(
        {"instruction": "click Search"},
        config={"configurable": {"user_id": "u1", "thread_id": "c1"}},
    )

    assert g.refreshed == [("job-1", "")]


async def test_nothing_waiting_points_the_model_back_at_the_join(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, pending=None)

    out = await guide_browser_task.ainvoke({"instruction": "click Search"}, config=UI_CONFIG)

    assert out == tool_mod._NOTHING_WAITING


async def test_guidance_that_landed_after_the_pause_ended_is_a_warning_naming_both_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, status=None)

    async with captured_wide_event() as event:
        out = await guide_browser_task.ainvoke({"instruction": "click Search"}, config=UI_CONFIG)

    assert out == tool_mod._STOPPED_WAITING
    (warning,) = [w for w in event["warnings"] if "browser" in w]
    assert warning["msg"].startswith(LogTag.BROWSER)
    assert warning["browser"] == {"job_id": "job-1", "handoff_id": "h-1"}
