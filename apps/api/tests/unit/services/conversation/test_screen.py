"""The screen projection: nothing shown moves, one bubble per piece of work, live equals reload."""

from dataclasses import dataclass, field
import itertools
import json
from unittest.mock import AsyncMock

from hypothesis import given, settings, strategies as st
import pytest

from app.constants.conversation import REPLY_FAILURE_LINE
from app.constants.general import CALL_EXECUTOR_NAME
from app.constants.hil import APPROVAL_REQUEST_TOOL_NAME
from app.models.conversation_frame_models import (
    EntryFrame,
    EntryUpdatedFrame,
    ImageEvent,
    StreamPayload,
    ToolDataEvent,
    WorkDeltaFrame,
)
from app.models.conversation_log_models import (
    Entry,
    LoggedEntry,
    Notice,
    Reply,
    ReplySettled,
    WorkFinished,
    WorkOutcome,
    WorkStarted,
)
from app.models.conversation_screen_models import (
    NoticeItem,
    ScreenInsertFrame,
    ScreenItem,
    ScreenPatch,
    ScreenUpdateFrame,
    TodoWokeItem,
    WorkItem,
    WorkStatus,
)
from app.models.conversation_send_models import ConversationEvent
from app.models.hil_models import ApprovalDescription, ApprovalDetail
from app.services.conversation import screen_patches as screen_patches_module
from app.services.conversation.screen import (
    TOOL_CALL_CARD,
    project_screen,
    work_root,
    work_timeline,
)
from app.services.conversation.screen_patches import ScreenItemMoved, ScreenTracker, screen_patches
from app.utils.artifact_utils import FILE_LINKS
from app.utils.message_breaks import split_message_bubbles
from shared.py.approvals import ApprovalStatus
from shared.py.conversation_wire import (
    FailureReason,
    ImageData,
    ReplyItem,
    ReplyOutcome,
    ScreenItemKind,
    ToolDataEntry,
    ToolProgress,
)
from tests.factories import CONVERSATION_ID
from tests.helpers import REPO_ROOT, TEST_FILE_LINKS
from tests.hypothesis_profiles import property_examples
from tests.unit.services.conversation.log_helpers import (
    asked,
    at,
    decided,
    finished,
    logged,
    notice,
    todo_woke,
    user,
)


def _handoff(call_id: str) -> ToolDataEntry:
    return {
        "tool_name": TOOL_CALL_CARD,
        "data": {
            "tool_name": CALL_EXECUTOR_NAME,
            "tool_call_id": call_id,
            "message": "Working on it",
        },
    }


def _card(name: str) -> ToolDataEntry:
    return {"tool_name": TOOL_CALL_CARD, "data": {"tool_name": name, "tool_call_id": name}}


def _ids(screen: list[ScreenItem]) -> list[str]:
    return [item.id for item in screen]


def _apply(screen: list[ScreenItem], patches: list[ScreenPatch]) -> list[ScreenItem]:
    """Apply patches the way a client does: insert before the first later seq, replace by id."""
    patched = list(screen)
    for patch in patches:
        if isinstance(patch, ScreenInsertFrame):
            later = [at for at, item in enumerate(patched) if item.seq > patch.item.seq]
            patched.insert(later[0] if later else len(patched), patch.item)
        else:
            patched = [patch.item if item.id == patch.item.id else item for item in patched]
    return patched


@dataclass
class _Log:
    """A log growing as the step writes it: appends take the next seq, fills replace a reply in place."""

    entries: list[LoggedEntry] = field(default_factory=list)
    screens: list[list[ScreenItem]] = field(default_factory=list)
    tracker: ScreenTracker = field(default_factory=lambda: ScreenTracker("c1", [], {}))
    patched: list[ScreenItem] = field(default_factory=list)
    patches: list[ScreenPatch] = field(default_factory=list)

    def append(self, entry: Entry) -> int:
        seq = len(self.entries) + 1
        self.entries.append(written := logged(seq, entry))
        self._shown(EntryFrame(seq=seq, at=written.at, entry=entry))
        return seq

    def fill(self, seq: int, entry: Reply) -> None:
        self.entries[seq - 1] = logged(seq, entry)
        self._shown(EntryUpdatedFrame(seq=seq, entry=entry))

    def _shown(self, frame: EntryFrame | EntryUpdatedFrame) -> None:
        """Project the log, and check the client patched from empty shows exactly that screen."""
        self.screens.append(project_screen(CONVERSATION_ID, self.entries, TEST_FILE_LINKS))
        patches = self.tracker.take(frame)
        self.patches.extend(patches)
        self.patched = _apply(self.patched, patches)
        assert self.patched == self.screens[-1]


def _assert_nothing_moves(screens: list[list[ScreenItem]]) -> None:
    for before, after in itertools.pairwise(screens):
        old, new = _ids(before), _ids(after)
        assert new[: len(old)] == old, f"an item moved or vanished: {old} -> {new}"


def _founder_log(*, legacy: bool) -> _Log:
    """Write the founder's conversation c41f18c5: three sends, a hand-off, a quick answer, a thank-you, the result."""
    log = _Log()
    log.append(user("u1"))
    log.append(user("u2"))
    task = "c4f22a9a"
    log.append(
        WorkStarted(
            id=f"work:{task}",
            task_id=task,
            cause_through=2,
            answers=("u1", "u2"),
            handoff=None if legacy else "call_1",
        )
    )
    log.append(user("u3"))
    log.append(
        Reply(id="1.2:reply", reply_id="r1.2", attempt_id="1.2", tool_data=(_handoff("call_1"),))
    )
    log.append(
        ReplySettled(
            id="1.2:settled",
            reply_id="r1.2",
            outcome=ReplyOutcome.ANSWERED,
            answers=("u1", "u2"),
            through=2,
            quote_target="u2",
        )
    )
    log.append(Reply(id="1.3:reply", reply_id="r1.3", attempt_id="1.3"))
    log.append(
        ReplySettled(
            id="1.3:settled",
            reply_id="r1.3",
            outcome=ReplyOutcome.SILENT,
            answers=("u3",),
            through=4,
            quote_target=None,
        )
    )
    cards = (_card("search_todos"), _card("create_todo"))
    log.append(
        WorkFinished(
            id=f"work:{task}:finished",
            task_id=task,
            outcome=WorkOutcome.DONE,
            report="done",
            tool_data=cards,
        )
    )
    narrating = Reply(
        id="2.1:reply",
        reply_id=task if legacy else "r2.1",
        attempt_id="2.1",
        tool_data=cards if legacy else (),
        narrates=() if legacy else (task,),
    )
    seq = log.append(narrating)
    log.fill(
        seq,
        narrating.model_copy(update={"text": "Buy milk was already on your list.", "revision": 1}),
    )
    log.append(
        ReplySettled(
            id="2.1:settled",
            reply_id=narrating.reply_id,
            outcome=ReplyOutcome.ANSWERED,
            answers=("u1", "u2"),
            through=9,
            quote_target="u2",
        )
    )
    return log


def test_founder_conversation_keeps_every_bubble_in_place_with_one_work_bubble() -> None:
    log = _founder_log(legacy=False)
    _assert_nothing_moves(log.screens)
    final = log.screens[-1]
    assert [item.kind for item in final] == [
        ScreenItemKind.USER,
        ScreenItemKind.USER,
        ScreenItemKind.WORK,
        ScreenItemKind.USER,
        ScreenItemKind.REPLY,
    ]
    work, reply = final[2], final[4]
    assert work.kind is ScreenItemKind.WORK and reply.kind is ScreenItemKind.REPLY
    assert work.status is WorkStatus.DONE
    assert work.handoff == _handoff("call_1")
    assert [card["data"]["tool_name"] for card in work.tool_data] == ["search_todos", "create_todo"]
    assert reply.tool_data == ()
    assert reply.narrates == ("c4f22a9a",)
    assert reply.quote is not None and reply.quote.id == "u2"


def test_founder_conversation_logged_before_narrates_renders_the_same_bubbles() -> None:
    legacy = _founder_log(legacy=True).screens[-1]
    current = _founder_log(legacy=False).screens[-1]
    assert [item.kind for item in legacy] == [item.kind for item in current]
    assert legacy[4].kind is ScreenItemKind.REPLY and legacy[4].tool_data == ()


def test_a_reply_that_failed_before_showing_anything_appears_where_it_failed() -> None:
    log = _Log()
    log.append(user("u1"))
    log.append(Reply(id="a:reply", reply_id="ra", attempt_id="a"))
    log.append(user("u2"))
    log.append(
        ReplySettled(
            id="a:settled",
            reply_id="ra",
            outcome=ReplyOutcome.FAILED,
            answers=(),
            through=1,
            quote_target=None,
            failure=FailureReason.MODEL_ERROR,
        )
    )
    _assert_nothing_moves(log.screens)
    assert _ids(log.screens[-1]) == ["u1", "u2", "ra"]


def test_an_open_approval_shows_as_awaiting_and_its_decision_ends_it() -> None:
    log = _Log()
    log.append(user("u1"))
    log.append(WorkStarted(id="work:t", task_id="t", cause_through=1))
    log.append(asked("approval:a", "t", "a"))
    awaiting = log.screens[-1][1]
    log.append(decided("approval:a:decided", "a"))
    running = log.screens[-1][1]
    assert awaiting.kind is ScreenItemKind.WORK and awaiting.status is WorkStatus.AWAITING_APPROVAL
    assert running.kind is ScreenItemKind.WORK and running.status is WorkStatus.RUNNING


_ACTIONS = st.sampled_from(
    [
        "send",
        "open_text",
        "open_card",
        "handoff",
        "fill",
        "settle",
        "ask",
        "decide",
        "finish",
        "notice",
    ]
)


@dataclass
class _Sim:
    """Writes entries the way the step and the executor do, driven by drawn actions."""

    log: _Log = field(default_factory=_Log)
    sent: list[str] = field(default_factory=list)
    attempts: int = 0
    tasks: int = 0
    # The open reply: its seq once appended (None while it shows nothing), its id and attempt.
    reply: tuple[int | None, str, str] | None = None
    live: list[str] = field(default_factory=list)
    roots: set[str] = field(default_factory=set)
    open_approvals: list[str] = field(default_factory=list)
    finished: list[str] = field(default_factory=list)

    def step(self, action: str, choice: int) -> None:
        getattr(self, f"_{action}")(choice)

    def _send(self, _choice: int) -> None:
        message_id = f"u{len(self.sent)}"
        self.sent.append(message_id)
        self.log.append(user(message_id))

    def _open(self, update: dict[str, object]) -> None:
        if self.reply is not None and self.reply[0] is not None:
            return
        _, reply_id, attempt_id = self._reply_ids()
        reply = Reply.model_validate(
            {
                "id": f"{attempt_id}:reply",
                "reply_id": reply_id,
                "attempt_id": attempt_id,
                "narrates": tuple(self.finished),
                **update,
            }
        )
        self.reply = (self.log.append(reply), reply_id, attempt_id)

    def _open_text(self, _choice: int) -> None:
        self._open({"text": "hi"})

    def _open_card(self, _choice: int) -> None:
        self._open({"tool_data": (_card(f"c{self.attempts}"),)})

    def _handoff(self, choice: int) -> None:
        if not self.sent:
            return
        self.reply = self._reply_ids()
        self.tasks += 1
        task = f"t{self.tasks}"
        joins = self.live[choice % len(self.live)] if self.live and choice % 2 else None
        self.log.append(
            WorkStarted(
                id=f"work:{task}",
                task_id=task,
                cause_through=len(self.log.entries),
                joins=joins,
                handoff=f"call-{task}",
            )
        )
        if joins is None:
            self.roots.add(task)
            self.live.append(task)
        self._handoffs.append(_handoff(f"call-{task}"))

    def _fill(self, _choice: int) -> None:
        if self.reply is None or self.reply[0] is None:
            return
        seq = self.reply[0]
        held = self.log.entries[seq - 1].entry
        assert isinstance(held, Reply)
        update = {"text": held.text + " more", "revision": held.revision + 1}
        self.log.fill(seq, held.model_copy(update=update))

    def _ask(self, choice: int) -> None:
        if not self.live:
            return
        task = self.live[choice % len(self.live)]
        approval = f"a{len(self.log.entries)}"
        self.open_approvals.append(approval)
        self.log.append(asked(f"approval:{approval}", task, approval))

    def _decide(self, choice: int) -> None:
        if not self.open_approvals:
            return
        approval = self.open_approvals.pop(choice % len(self.open_approvals))
        self.log.append(decided(f"approval:{approval}:decided", approval))

    def _finish(self, choice: int) -> None:
        if not self.live:
            return
        task = self.live.pop(choice % len(self.live))
        cards = (_card(f"{task}-search"), _card(f"{task}-create"))
        self.log.append(
            WorkFinished(
                id=f"work:{task}:finished",
                task_id=task,
                outcome=list(WorkOutcome)[choice % len(WorkOutcome)],
                report="r",
                tool_data=cards,
            )
        )
        self.finished.append(task)

    def _notice(self, _choice: int) -> None:
        self.log.append(notice(f"n{len(self.log.entries)}"))

    _handoffs: list[ToolDataEntry] = field(default_factory=list)

    def _reply_ids(self) -> tuple[int | None, str, str]:
        if self.reply is not None:
            return self.reply
        self.attempts += 1
        attempt = f"{self.attempts}"
        return (None, f"r{attempt}", attempt)

    def _settle(self, choice: int) -> None:
        if self.reply is None:
            return
        seq, reply_id, attempt_id = self.reply
        handoffs = tuple(self._handoffs)
        if seq is None:
            # Nothing visible was shown: the reply is appended at settle with only its hand-offs.
            self.log.append(
                Reply(
                    id=f"{attempt_id}:reply",
                    reply_id=reply_id,
                    attempt_id=attempt_id,
                    tool_data=handoffs,
                )
            )
        elif handoffs:
            held = self.log.entries[seq - 1].entry
            assert isinstance(held, Reply)
            update = {"tool_data": (*held.tool_data, *handoffs), "revision": held.revision + 1}
            self.log.fill(seq, held.model_copy(update=update))
        outcome = (
            list(ReplyOutcome)[choice % len(ReplyOutcome)] if self.sent else ReplyOutcome.FAILED
        )
        self.log.append(
            ReplySettled(
                id=f"{attempt_id}:settled",
                reply_id=reply_id,
                outcome=outcome,
                answers=tuple(self.sent[-1:]),
                through=len(self.log.entries),
                failure=FailureReason.MODEL_ERROR if outcome is ReplyOutcome.FAILED else None,
                quote_target=self.sent[-1] if self.sent else None,
                narrates=tuple(self.finished),
            )
        )
        self.finished = []
        self._handoffs = []
        self.reply = None


@settings(max_examples=property_examples(300), deadline=None)
@given(st.lists(st.tuples(_ACTIONS, st.integers(min_value=0, max_value=7)), max_size=40))
def test_any_conversation_only_grows_at_the_end_and_reloads_to_what_was_shown(
    actions: list[tuple[str, int]],
) -> None:
    sim = _Sim()
    for action, choice in actions:
        sim.step(action, choice)
    screens = sim.log.screens
    _assert_nothing_moves(screens)
    if not screens:
        return
    final = screens[-1]
    assert final == project_screen(CONVERSATION_ID, list(sim.log.entries), TEST_FILE_LINKS)
    users = [item.id for item in final if item.kind is ScreenItemKind.USER]
    assert users == sim.sent
    works = [item for item in final if item.kind is ScreenItemKind.WORK]
    assert sorted(item.task_id for item in works) == sorted(sim.roots)
    for item in final:
        if item.kind is ScreenItemKind.REPLY:
            assert all(card["data"]["tool_name"] != CALL_EXECUTOR_NAME for card in item.tool_data)


def test_every_patch_names_the_log_head_it_reflects_even_when_it_amends_an_older_entry() -> None:
    log = _Log()
    log.append(user("u1"))
    reply = Reply(id="1.1:reply", reply_id="r1.1", attempt_id="1.1", text="Seco")
    seq = log.append(reply)
    log.fill(seq, reply.model_copy(update={"text": "Second turn.", "revision": 1}))
    log.append(
        ReplySettled(
            id="1.1:settled",
            reply_id="r1.1",
            outcome=ReplyOutcome.ANSWERED,
            answers=("u1",),
            through=1,
            quote_target="u1",
        )
    )
    assert [(patch.item.id, patch.head) for patch in log.patches] == [
        ("u1", 1),
        ("r1.1", 2),
        ("r1.1", 2),
        ("r1.1", 3),
    ]


def test_a_projection_that_moves_a_shown_item_fails_loudly() -> None:
    first, second = project_screen(
        CONVERSATION_ID, [logged(1, user("u1")), logged(2, user("u2"))], TEST_FILE_LINKS
    )
    with pytest.raises(ScreenItemMoved):
        screen_patches([first, second], [second, first], 2)
    with pytest.raises(ScreenItemMoved):
        screen_patches([first, second], [second], 2)


async def test_a_handed_over_tasks_cards_show_on_the_work_item_it_joined() -> None:
    tracker = ScreenTracker(
        "c1",
        [
            logged(1, user("u1")),
            logged(2, WorkStarted(id="work:t1", task_id="t1", cause_through=1, answers=("u1",))),
        ],
        {},
    )
    joined = WorkStarted(id="work:t2", task_id="t2", cause_through=1, answers=(), joins="t1")
    tracker.take(EntryFrame(seq=3, at=logged(3, joined).at, entry=joined))
    delta = WorkDeltaFrame(task_id="t2", index=0, payload=ToolDataEvent(tool_data=_card("x")))
    (patch,) = await tracker.on_work(delta)
    assert isinstance(patch, ScreenUpdateFrame)
    assert isinstance(patch.item, WorkItem)
    assert (patch.item.task_id, patch.item.tool_data) == ("t1", (_card("x"),))
    assert [item.id for item in tracker.items] == ["u1", "work:t1"]


# The clients' tests replay these frames: the server's own serialization of the founder's conversation.
_FOUNDER_FRAMES = REPO_ROOT / "libs/shared/ts/src/conversation/fixtures/c41f18c5.frames.json"


def test_the_founder_conversations_patches_are_the_frames_the_clients_replay() -> None:
    log = _founder_log(legacy=False)
    frames = [ConversationEvent(frame=patch).model_dump(mode="json") for patch in log.patches]
    assert json.loads(_FOUNDER_FRAMES.read_text()) == frames


def test_work_lists_the_approvals_it_waits_on_until_each_is_decided() -> None:
    started = WorkStarted(id="work:t1", task_id="t1", cause_through=1, answers=("u1",))
    log = [logged(1, user("u1")), logged(2, started), logged(3, asked("ask:a1", "t1", "a1"))]
    [_, waiting] = project_screen(CONVERSATION_ID, log, TEST_FILE_LINKS)
    assert waiting.kind is ScreenItemKind.WORK
    assert [request.approval_id for request in waiting.asking] == ["a1"]
    [_, decided_work] = project_screen(
        CONVERSATION_ID, [*log, logged(4, decided("dec:a1", "a1"))], TEST_FILE_LINKS
    )
    assert decided_work.kind is ScreenItemKind.WORK
    assert decided_work.asking == ()


def test_a_run_that_ended_leaving_its_approval_to_the_user_still_asks_for_it() -> None:
    started = WorkStarted(id="work:t1", task_id="t1", cause_through=1, answers=("u1",))
    ended = WorkFinished(
        id="fin:t1",
        task_id="t1",
        outcome=WorkOutcome.DONE,
        report="asked",
        continued_by_decision=True,
    )
    log = [
        logged(1, user("u1")),
        logged(2, started),
        logged(3, asked("ask:a1", "t1", "a1")),
        logged(4, ended),
    ]
    [_, parked] = project_screen(CONVERSATION_ID, log, TEST_FILE_LINKS)
    assert parked.kind is ScreenItemKind.WORK
    assert [request.approval_id for request in parked.asking] == ["a1"]
    assert (parked.status, parked.asked_seq) == (WorkStatus.AWAITING_APPROVAL, 3)


def test_an_approval_its_run_left_waiting_when_it_ended_is_withdrawn_and_no_longer_asked() -> None:
    started = WorkStarted(id="work:t1", task_id="t1", cause_through=1, answers=("u1",))
    ended = WorkFinished(id="fin:t1", task_id="t1", outcome=WorkOutcome.DONE, report="done")
    log = [
        logged(1, user("u1")),
        logged(2, started),
        logged(3, asked("ask:a1", "t1", "a1")),
        logged(4, ended),
    ]
    [_, work] = project_screen(CONVERSATION_ID, log, TEST_FILE_LINKS)
    assert work.kind is ScreenItemKind.WORK
    assert (work.asking, work.status) == ((), WorkStatus.DONE)
    [card] = work.approvals
    assert (card.data.status, card.data.outcome) == (ApprovalStatus.WITHDRAWN, None)


def test_an_approval_reads_expired_once_the_log_moves_past_its_time() -> None:
    started = WorkStarted(id="work:t1", task_id="t1", cause_through=1, answers=("u1",))
    request = asked("ask:a1", "t1", "a1").model_copy(update={"expires_at": at(3)})
    log = [logged(1, user("u1")), logged(2, started), logged(3, request)]
    [_, waiting] = project_screen(CONVERSATION_ID, log, TEST_FILE_LINKS)
    assert waiting.kind is ScreenItemKind.WORK
    assert [card.data.status for card in waiting.approvals] == [ApprovalStatus.WAITING]
    [_, lapsed, _] = project_screen(CONVERSATION_ID, [*log, logged(4, user("u2"))], TEST_FILE_LINKS)
    assert lapsed.kind is ScreenItemKind.WORK
    assert lapsed.asking == ()
    assert [card.data.status for card in lapsed.approvals] == [ApprovalStatus.EXPIRED]


def test_a_yes_with_a_change_reads_approved_with_change() -> None:
    started = WorkStarted(id="work:t1", task_id="t1", cause_through=1, answers=("u1",))
    change = decided("dec:a1", "a1").model_copy(update={"feedback": "cc Sam"})
    log = [
        logged(1, user("u1")),
        logged(2, started),
        logged(3, asked("ask:a1", "t1", "a1")),
        logged(4, change),
    ]
    [_, work] = project_screen(CONVERSATION_ID, log, TEST_FILE_LINKS)
    assert work.kind is ScreenItemKind.WORK
    assert [card.data.status for card in work.approvals] == [ApprovalStatus.APPROVED_WITH_CHANGE]


def test_a_work_item_says_where_the_newest_approval_it_waits_on_was_logged() -> None:
    started = WorkStarted(id="work:t1", task_id="t1", cause_through=1, answers=("u1",))
    log = [logged(1, user("u1")), logged(2, started)]
    [_, running] = project_screen(CONVERSATION_ID, log, TEST_FILE_LINKS)
    assert running.kind is ScreenItemKind.WORK
    assert running.asked_seq == 0
    log += [logged(3, user("u2")), logged(4, asked("ask:a1", "t1", "a1"))]
    [_, waiting, _] = project_screen(CONVERSATION_ID, log, TEST_FILE_LINKS)
    assert waiting.kind is ScreenItemKind.WORK
    assert (waiting.seq, waiting.asked_seq) == (2, 4)


def test_a_work_items_approval_card_is_drawn_in_its_timeline_and_ends_with_its_decision() -> None:
    started = WorkStarted(id="work:t1", task_id="t1", cause_through=1, answers=("u1",))
    log = [logged(1, user("u1")), logged(2, started), logged(3, asked("ask:a1", "t1", "a1"))]
    [_, waiting] = project_screen(CONVERSATION_ID, log, TEST_FILE_LINKS)
    assert waiting.kind is ScreenItemKind.WORK
    [shown] = [entry.card for entry in waiting.timeline.cards]
    [asking] = shown["data"]
    assert (shown["tool_name"], asking["approval_id"], asking["outcome"]) == (
        APPROVAL_REQUEST_TOOL_NAME,
        "a1",
        None,
    )
    [_, ended] = project_screen(
        CONVERSATION_ID, [*log, logged(4, decided("dec:a1", "a1"))], TEST_FILE_LINKS
    )
    assert ended.kind is ScreenItemKind.WORK
    [card] = [entry.card for entry in ended.timeline.cards]
    [answered] = card["data"]
    assert (answered["outcome"], answered["decider"]) == ("approved", "user")


def test_an_approval_card_carries_the_calls_plain_description_for_every_surface() -> None:
    described = ApprovalDescription(
        action="Pay an invoice",
        headline="Pay invoice INV-7 to Acme",
        confirm="pay it",
        details=[
            ApprovalDetail(label="Amount", value="$120"),
            ApprovalDetail(label="Payee", value="Acme"),
        ],
    )
    started = WorkStarted(id="work:t1", task_id="t1", cause_through=1, answers=("u1",))
    log = [
        logged(1, user("u1")),
        logged(2, started),
        logged(3, asked("ask:a1", "t1", "a1", described)),
    ]
    [_, waiting] = project_screen(CONVERSATION_ID, log, TEST_FILE_LINKS)
    assert waiting.kind is ScreenItemKind.WORK
    [card] = [entry.card for entry in waiting.timeline.cards]
    [shown] = card["data"]
    assert shown["description"] == described.model_dump(mode="json")
    [request] = waiting.asking
    assert request.description == described


def _artifact(path: str) -> ToolDataEntry:
    data = {"event": "upsert", "path": path, "content_type": "application/pdf"}
    return {"tool_name": "artifact_data", "data": data}


def test_a_reply_delivers_the_files_it_and_the_work_it_narrates_wrote_once_each() -> None:
    started = WorkStarted(id="work:t1", task_id="t1", cause_through=1, answers=("u1",))
    finished = WorkFinished(
        id="work:t1:finished",
        task_id="t1",
        outcome=WorkOutcome.DONE,
        report="done",
        tool_data=(_artifact("out/a.pdf"),),
    )
    reply = Reply(
        id="r:reply",
        reply_id="r",
        attempt_id="1",
        text="here",
        narrates=("t1",),
        tool_data=(_artifact("out/a.pdf"), _artifact("out/b.pdf")),
    )
    log = [logged(1, user("u1")), logged(2, started), logged(3, finished), logged(4, reply)]
    [*_, item] = project_screen(CONVERSATION_ID, log, TEST_FILE_LINKS)
    assert item.kind is ScreenItemKind.REPLY
    assert [file.path for file in item.files] == ["out/a.pdf", "out/b.pdf"]


def test_a_reply_and_its_work_name_the_newest_user_message_they_answer_as_the_retry_target() -> (
    None
):
    work = WorkStarted(id="work:t1", task_id="t1", cause_through=3, answers=("u1", "u2"))
    reply = Reply(id="r:reply", reply_id="r", attempt_id="1", text="done")
    settle = ReplySettled(
        id="r:settled",
        reply_id="r",
        outcome=ReplyOutcome.ANSWERED,
        answers=("u2", "u1"),
        through=3,
        quote_target=None,
    )
    log = [
        logged(1, user("u1")),
        logged(2, user("u2")),
        logged(3, user("u3")),
        logged(4, work),
        logged(5, reply),
        logged(6, settle),
    ]
    targets = {
        item.id: item.retry_target
        for item in project_screen(CONVERSATION_ID, log, TEST_FILE_LINKS)
        if isinstance(item, WorkItem | ReplyItem)
    }
    assert targets == {"work:t1": "u2", "r": "u2"}


def test_a_reply_quoting_a_newer_message_than_it_answers_retries_the_quoted_one() -> None:
    reply = Reply(id="r:reply", reply_id="r", attempt_id="1", text="done")
    settle = ReplySettled(
        id="r:settled",
        reply_id="r",
        outcome=ReplyOutcome.ANSWERED,
        answers=("u1",),
        through=2,
        quote_target="u2",
    )
    log = [logged(1, user("u1")), logged(2, user("u2")), logged(3, reply), logged(4, settle)]
    [*_, item] = project_screen(CONVERSATION_ID, log, TEST_FILE_LINKS)
    assert isinstance(item, ReplyItem)
    assert item.retry_target == "u2"


def test_a_reply_showing_only_its_own_card_is_on_the_screen() -> None:
    reply = Reply(id="r:reply", reply_id="r", attempt_id="1", tool_data=(_card("search"),))
    [*_, item] = project_screen(
        CONVERSATION_ID, [logged(1, user("u1")), logged(2, reply)], TEST_FILE_LINKS
    )
    assert isinstance(item, ReplyItem)
    assert (item.bubbles, item.tool_data) == ((), (_card("search"),))


def test_the_progress_line_skips_other_cards_and_silent_calls_down_to_the_newest_that_speaks() -> (
    None
):
    speaks: ToolDataEntry = {
        "tool_name": TOOL_CALL_CARD,
        "data": {
            "tool_name": "gmail_send",
            "message": "Sending the email",
            "icon_url": "https://cdn.example/gmail.png",
            "show_category": False,
        },
    }
    silent: ToolDataEntry = {"tool_name": TOOL_CALL_CARD, "data": {"tool_name": "think"}}
    other: ToolDataEntry = {"tool_name": "search", "data": {"message": "not a tool call"}}
    reply = Reply(
        id="r:reply", reply_id="r", attempt_id="1", text="hi", tool_data=(speaks, silent, other)
    )
    [*_, item] = project_screen(
        CONVERSATION_ID, [logged(1, user("u1")), logged(2, reply)], TEST_FILE_LINKS
    )
    assert isinstance(item, ReplyItem)
    assert item.timeline.progress == ToolProgress(
        message="Sending the email",
        tool_name="gmail_send",
        tool_category="",
        integration_name=None,
        icon_url="https://cdn.example/gmail.png",
        show_category=False,
    )


def test_work_answering_no_user_message_has_no_retry_target() -> None:
    work = WorkStarted(id="work:t1", task_id="t1", cause_through=1, answers=("n1",))
    [_, item] = project_screen(
        CONVERSATION_ID, [logged(1, notice("n1")), logged(2, work)], TEST_FILE_LINKS
    )
    assert isinstance(item, WorkItem)
    assert item.retry_target is None


def test_an_items_timeline_states_the_newest_tool_calls_progress_line() -> None:
    first: ToolDataEntry = {
        "tool_name": TOOL_CALL_CARD,
        "data": {"tool_name": "search", "message": "Searching the web", "show_category": False},
    }
    newest: ToolDataEntry = {
        "tool_name": TOOL_CALL_CARD,
        "data": {
            "tool_name": "gmail_send",
            "tool_category": "gmail",
            "message": "Sending the email",
            "integration_name": "Gmail",
            "icon_url": None,
        },
    }
    reply = Reply(
        id="r:reply",
        reply_id="r",
        attempt_id="1",
        text="hi",
        tool_data=(first, newest, _card("no_message")),
    )
    [*_, item] = project_screen(
        CONVERSATION_ID, [logged(1, user("u1")), logged(2, reply)], TEST_FILE_LINKS
    )
    assert isinstance(item, ReplyItem)
    assert item.timeline.progress == ToolProgress(
        message="Sending the email",
        tool_name="gmail_send",
        tool_category="gmail",
        integration_name="Gmail",
        icon_url=None,
        show_category=True,
    )


def test_a_moved_item_is_named_with_both_orders() -> None:
    first, second = project_screen(
        CONVERSATION_ID, [logged(1, user("u1")), logged(2, user("u2"))], TEST_FILE_LINKS
    )
    with pytest.raises(ScreenItemMoved) as moved:
        screen_patches([first, second], [second, first], 2)
    assert str(moved.value) == "shown ['u1', 'u2'], projected ['u2', 'u1']"


_RUNNING = [
    logged(1, user("u1")),
    logged(2, WorkStarted(id="work:t1", task_id="t1", cause_through=1, answers=("u1",))),
]
_MADE = ImageData(url="https://img.example/1.png", prompt="a cat")


def test_a_running_tasks_published_cards_and_image_show_on_its_work_item() -> None:
    published: list[StreamPayload] = [
        ToolDataEvent(tool_data=_card("x")),
        ImageEvent(image_data=_MADE),
    ]
    tracker = ScreenTracker("c1", _RUNNING, {"t1": published})
    [_, work] = tracker.items
    assert isinstance(work, WorkItem)
    assert (work.tool_data, work.image) == ((_card("x"),), _MADE)
    assert work.timeline == work_timeline(work.handoff, (_card("x"),), work.approvals)


async def test_a_reader_that_missed_a_tasks_frames_reads_its_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = AsyncMock(
        return_value=[ToolDataEvent(tool_data=_card("x")), ToolDataEvent(tool_data=_card("y"))]
    )
    monkeypatch.setattr(screen_patches_module, "work_payloads", record)
    tracker = ScreenTracker("c1", _RUNNING, {})
    gap = WorkDeltaFrame(task_id="t1", index=1, payload=ToolDataEvent(tool_data=_card("y")))
    (patch,) = await tracker.on_work(gap)
    record.assert_awaited_once_with("c1", "t1")
    assert isinstance(patch.item, WorkItem)
    assert patch.item.tool_data == (_card("x"), _card("y"))


def test_a_hand_over_chain_that_loops_ends_at_the_task_it_came_back_to() -> None:
    chain = {
        "t1": WorkStarted(id="work:t1", task_id="t1", cause_through=1, joins="t2"),
        "t2": WorkStarted(id="work:t2", task_id="t2", cause_through=1, joins="t3"),
        "t3": WorkStarted(id="work:t3", task_id="t3", cause_through=1, joins="t2"),
    }
    assert work_root(chain, "t1") == "t2"
    back = {**chain, "t2": WorkStarted(id="work:t2", task_id="t2", cause_through=1, joins="t1")}
    assert work_root(back, "t1") == "t1"


def test_a_woken_todo_and_a_notice_show_as_their_own_items() -> None:
    woke = todo_woke("tw1")
    said = Notice(id="n1", text="first\n\nsecond", origin="reminder")
    [woken, noticed] = project_screen(
        CONVERSATION_ID, [logged(1, woke), logged(2, said)], TEST_FILE_LINKS
    )
    assert woken == TodoWokeItem(id="tw1", seq=1, at=logged(1, woke).at, wake=woke.run.wake)
    assert isinstance(noticed, NoticeItem)
    assert noticed.bubbles == tuple(split_message_bubbles("first\n\nsecond"))


_IMAGE = ImageData(url="https://img.example/2.png", prompt="a dog")


def test_work_and_a_reply_show_the_image_each_made() -> None:
    started = WorkStarted(id="work:t1", task_id="t1", cause_through=1, answers=("u1",))
    done = WorkFinished(id="f1", task_id="t1", outcome=WorkOutcome.DONE, report="r", image=_IMAGE)
    reply = Reply(id="o1", reply_id="r1", attempt_id="a1", text="here", image=_IMAGE)
    items = project_screen(
        CONVERSATION_ID,
        [logged(1, user("u1")), logged(2, started), logged(3, done), logged(4, reply)],
        TEST_FILE_LINKS,
    )
    images = {item.id: getattr(item, "image", None) for item in items}
    assert (images["work:t1"], images["r1"]) == (_IMAGE, _IMAGE)


def test_a_reply_narrates_what_its_settle_names_and_keeps_its_failure() -> None:
    started = WorkStarted(id="work:t1", task_id="t1", cause_through=1, answers=("u1",))
    done = WorkFinished(id="f1", task_id="t1", outcome=WorkOutcome.DONE, report="r")
    reply = Reply(id="o1", reply_id="t9", attempt_id="a1", text="partly")
    failed = ReplySettled(
        id="s1",
        reply_id="t9",
        outcome=ReplyOutcome.FAILED,
        answers=("u1",),
        through=1,
        quote_target=None,
        failure=FailureReason.MODEL_ERROR,
        narrates=("t1",),
    )
    items = project_screen(
        CONVERSATION_ID,
        [
            logged(1, user("u1")),
            logged(2, started),
            logged(3, done),
            logged(4, reply),
            logged(5, failed),
        ],
        TEST_FILE_LINKS,
    )
    [shown] = [item for item in items if isinstance(item, ReplyItem)]
    assert (shown.narrates, shown.failure) == (("t1",), FailureReason.MODEL_ERROR)


def test_a_reply_naming_its_work_is_not_rekeyed_by_a_task_sharing_its_id() -> None:
    first = WorkStarted(id="work:t1", task_id="t1", cause_through=1, answers=("u1",))
    second = WorkStarted(id="work:r1", task_id="r1", cause_through=1, answers=("u1",))
    ends = [
        WorkFinished(id=f"f-{task}", task_id=task, outcome=WorkOutcome.DONE, report="r")
        for task in ("t1", "r1")
    ]
    reply = Reply(id="o1", reply_id="r1", attempt_id="a1", text="both", narrates=("t1",))
    log: list[Entry] = [user("u1"), first, second, *ends, reply]
    items = project_screen(
        CONVERSATION_ID,
        [logged(seq, entry) for seq, entry in enumerate(log, start=1)],
        TEST_FILE_LINKS,
    )
    [shown] = [item for item in items if isinstance(item, ReplyItem)]
    assert shown.narrates == ("t1",)


def test_an_imported_reply_shows_once_its_history_settled_it() -> None:
    reply = Reply(id="o1", reply_id="r1", attempt_id="a1", text="old answer", imported=True)
    settle = ReplySettled(
        id="s1",
        reply_id="r1",
        outcome=ReplyOutcome.ANSWERED,
        answers=("u1",),
        through=1,
        quote_target=None,
        imported=True,
    )
    log = [logged(1, user("u1")), logged(2, reply)]
    assert [item.id for item in project_screen(CONVERSATION_ID, log, TEST_FILE_LINKS)] == ["u1"]
    assert [
        item.id
        for item in project_screen(CONVERSATION_ID, [*log, logged(3, settle)], TEST_FILE_LINKS)
    ] == [
        "u1",
        "r1",
    ]


def test_an_approval_card_on_a_work_item_carries_wire_json() -> None:
    started = WorkStarted(id="work:t1", task_id="t1", cause_through=1, answers=("u1",))
    log = [logged(1, user("u1")), logged(2, started), logged(3, asked("ask:a1", "t1", "a1"))]
    [_, ended] = project_screen(
        CONVERSATION_ID, [*log, logged(4, decided("dec:a1", "a1"))], TEST_FILE_LINKS
    )
    assert isinstance(ended, WorkItem)
    [card] = [entry.card for entry in ended.timeline.cards]
    [answered] = card["data"]
    assert type(answered["outcome"]) is str


async def test_loading_reads_the_record_of_running_work_and_its_hand_overs_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entries = [
        *_RUNNING,
        logged(3, WorkStarted(id="work:t2", task_id="t2", cause_through=1, joins="t1")),
        logged(4, user("u2")),
        logged(5, WorkStarted(id="work:t3", task_id="t3", cause_through=4, answers=("u2",))),
        logged(6, finished("f3", "t3")),
    ]
    records = {"t1": [ToolDataEvent(tool_data=_card("x"))], "t2": [], "t3": []}
    reads: list[tuple[str, str]] = []

    async def record(conversation_id: str, task_id: str) -> list[StreamPayload]:
        reads.append((conversation_id, task_id))
        return list(records[task_id])

    monkeypatch.setattr(screen_patches_module, "work_payloads", record)
    tracker = await ScreenTracker.load("c1", entries)
    assert reads == [("c1", "t1"), ("c1", "t2")]
    running = next(
        item for item in tracker.items if isinstance(item, WorkItem) and item.task_id == "t1"
    )
    assert running.tool_data == (_card("x"),)
    records["t1"].append(ToolDataEvent(tool_data=_card("y")))
    await tracker.on_work(
        WorkDeltaFrame(task_id="t1", index=5, payload=ToolDataEvent(tool_data=_card("z")))
    )
    assert reads[-1] == ("c1", "t1")


@pytest.mark.parametrize("reason", list(FailureReason))
def test_a_failed_reply_carries_the_line_a_chat_platform_shows_under_it(
    reason: FailureReason,
) -> None:
    settled = ReplySettled(
        id="s1",
        reply_id="r1",
        outcome=ReplyOutcome.FAILED,
        answers=("u1",),
        through=1,
        quote_target=None,
        failure=reason,
    )
    reply = Reply(id="o1", reply_id="r1", attempt_id="a1")
    items = project_screen(
        CONVERSATION_ID,
        [logged(1, user("u1")), logged(2, reply), logged(3, settled)],
        TEST_FILE_LINKS,
    )
    [shown] = [item for item in items if isinstance(item, ReplyItem)]
    assert shown.failure_line == REPLY_FAILURE_LINE[reason]


def test_an_answered_reply_carries_no_failure_line() -> None:
    reply = Reply(id="o1", reply_id="r1", attempt_id="a1", text="done")
    settled = ReplySettled(
        id="s1",
        reply_id="r1",
        outcome=ReplyOutcome.ANSWERED,
        answers=("u1",),
        through=1,
        quote_target=None,
    )
    items = project_screen(
        CONVERSATION_ID,
        [logged(1, user("u1")), logged(2, reply), logged(3, settled)],
        TEST_FILE_LINKS,
    )
    [shown] = [item for item in items if isinstance(item, ReplyItem)]
    assert shown.failure_line is None


# A link a user taps in a chat app opens the conversation, where the file's card is, in the web app.
_WEB = f"https://gaia.test/c/{CONVERSATION_ID}"


@pytest.mark.parametrize(
    "written",
    [
        "./artifacts/reports/q3.pdf",
        "artifacts/reports/q3.pdf",
        "/artifacts/reports/q3.pdf",
        "/workspace/sessions/executor_c1/artifacts/reports/q3.pdf",
    ],
)
def test_a_reply_links_an_artifact_to_its_conversation_in_the_web_app_and_embeds_images_by_url(
    written: str,
) -> None:
    text = f"Done: [the plan]({written}) and ![chart](./artifacts/chart.png)"
    reply = Reply(id="o1", reply_id="r1", attempt_id="a1", text=text)
    [_, shown] = project_screen(
        CONVERSATION_ID, [logged(1, user("u1")), logged(2, reply)], TEST_FILE_LINKS
    )
    base = f"https://api.gaia.test/api/v1/sessions/{CONVERSATION_ID}/artifacts"
    assert isinstance(shown, ReplyItem)
    assert shown.bubbles == (f"Done: [the plan]({_WEB}) and ![chart]({base}/chart.png)",)
    assert reply.text == text


def test_a_reply_leaves_links_that_are_not_artifacts_as_written() -> None:
    text = "See [docs](https://example.com/artifacts/x) and [notes](./notes/artifacts.md)"
    reply = Reply(id="o1", reply_id="r1", attempt_id="a1", text=text)
    [_, shown] = project_screen(
        CONVERSATION_ID, [logged(1, user("u1")), logged(2, reply)], TEST_FILE_LINKS
    )
    assert isinstance(shown, ReplyItem)
    assert shown.bubbles == (text,)


@pytest.mark.parametrize(
    "written",
    [
        "/workspace/sessions/d28765d3/artifacts/inner planets.csv",
        "`/workspace/sessions/d28765d3/artifacts/inner planets.csv`",
    ],
)
def test_a_reply_naming_an_artifact_by_its_sandbox_path_links_it_by_name(written: str) -> None:
    path = written.replace(" ", "_")
    text = f"Saved it: {path}. Anything else?"
    reply = Reply(id="o1", reply_id="r1", attempt_id="a1", text=text)
    [_, shown] = project_screen(
        CONVERSATION_ID, [logged(1, user("u1")), logged(2, reply)], TEST_FILE_LINKS
    )
    assert isinstance(shown, ReplyItem)
    assert shown.bubbles == (f"Saved it: [inner_planets.csv]({_WEB}). Anything else?",)


def test_a_notice_names_a_sandbox_file_outside_artifacts_by_its_name_alone() -> None:
    said = Notice(id="n1", text="Wrote /workspace/sessions/c1/scratch/notes.txt", origin="reminder")
    [noticed] = project_screen(CONVERSATION_ID, [logged(1, said)], TEST_FILE_LINKS)
    assert isinstance(noticed, NoticeItem)
    assert noticed.bubbles == ("Wrote notes.txt",)


def test_a_notice_links_an_artifact_to_its_own_conversation() -> None:
    said = Notice(id="n1", text="Wrote /workspace/sessions/c1/artifacts/a.csv", origin="reminder")
    [noticed] = project_screen(CONVERSATION_ID, [logged(1, said)], TEST_FILE_LINKS)
    assert isinstance(noticed, NoticeItem)
    assert noticed.bubbles == (f"Wrote [a.csv]({_WEB})",)


def test_a_readers_screen_links_files_to_its_own_conversation() -> None:
    said = Notice(id="n1", text="Wrote /workspace/sessions/c1/artifacts/a.csv", origin="reminder")
    [noticed] = ScreenTracker(CONVERSATION_ID, [logged(1, said)], {}).items
    assert isinstance(noticed, NoticeItem)
    assert noticed.bubbles == (f"Wrote [a.csv]({FILE_LINKS.conversation_page(CONVERSATION_ID)})",)


def test_a_link_labelled_with_its_sandbox_path_is_labelled_by_the_files_name() -> None:
    written = "/workspace/sessions/c1/artifacts/a.csv"
    reply = Reply(id="o1", reply_id="r1", attempt_id="a1", text=f"[{written}]({written})")
    [_, shown] = project_screen(
        CONVERSATION_ID, [logged(1, user("u1")), logged(2, reply)], TEST_FILE_LINKS
    )
    assert isinstance(shown, ReplyItem)
    assert shown.bubbles == (f"[a.csv]({_WEB})",)
