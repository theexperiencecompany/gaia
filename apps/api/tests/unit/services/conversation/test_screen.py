"""The screen projection: nothing shown moves, one bubble per piece of work, live equals reload."""

from dataclasses import dataclass, field
import itertools
import json
from pathlib import Path

from hypothesis import given, settings, strategies as st
import pytest

from app.constants.general import CALL_EXECUTOR_NAME
from app.models.conversation_frame_models import (
    EntryFrame,
    EntryUpdatedFrame,
    ToolDataEvent,
    WorkDeltaFrame,
)
from app.models.conversation_log_models import (
    Entry,
    FailureReason,
    LoggedEntry,
    Reply,
    ReplyOutcome,
    ReplySettled,
    WorkFinished,
    WorkOutcome,
    WorkStarted,
)
from app.models.conversation_screen_models import (
    ScreenInsertFrame,
    ScreenItem,
    ScreenItemKind,
    ScreenPatch,
    WorkStatus,
)
from app.models.conversation_send_models import ConversationEvent
from app.models.tool_data_models import ToolDataEntry
from app.services.conversation.screen import TOOL_CALL_CARD, project_screen
from app.services.conversation.screen_patches import ScreenItemMoved, ScreenTracker, screen_patches
from tests.unit.services.conversation.log_helpers import asked, decided, logged, notice, user


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
    tracker: ScreenTracker = field(default_factory=lambda: ScreenTracker([]))
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
        self.screens.append(project_screen(self.entries))
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
        reply = Reply(
            id=f"{attempt_id}:reply",
            reply_id=reply_id,
            attempt_id=attempt_id,
            narrates=tuple(self.finished),
            **update,
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


@settings(max_examples=300, deadline=None)
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
    assert final == project_screen(list(sim.log.entries))
    users = [item.id for item in final if item.kind is ScreenItemKind.USER]
    assert users == sim.sent
    works = [item for item in final if item.kind is ScreenItemKind.WORK]
    assert sorted(item.task_id for item in works) == sorted(sim.roots)
    for item in final:
        if item.kind is ScreenItemKind.REPLY:
            assert all(card["data"]["tool_name"] != CALL_EXECUTOR_NAME for card in item.tool_data)


def test_a_projection_that_moves_a_shown_item_fails_loudly() -> None:
    first, second = project_screen([logged(1, user("u1")), logged(2, user("u2"))])
    with pytest.raises(ScreenItemMoved):
        screen_patches([first, second], [second, first])
    with pytest.raises(ScreenItemMoved):
        screen_patches([first, second], [second])


def test_a_handed_over_tasks_delta_streams_into_the_work_item_it_joined() -> None:
    tracker = ScreenTracker(
        [
            logged(1, user("u1")),
            logged(2, WorkStarted(id="work:t1", task_id="t1", cause_through=1, answers=("u1",))),
        ]
    )
    joined = WorkStarted(id="work:t2", task_id="t2", cause_through=1, answers=(), joins="t1")
    tracker.take(EntryFrame(seq=3, at=logged(3, joined).at, entry=joined))
    delta = WorkDeltaFrame(task_id="t2", index=0, payload=ToolDataEvent(tool_data=_card("x")))
    assert tracker.on_its_item(delta).task_id == "t1"
    assert [item.id for item in tracker.items] == ["u1", "work:t1"]


# The clients' tests replay these frames: the server's own serialization of the founder's conversation.
_FOUNDER_FRAMES = (
    Path(__file__).parents[6] / "libs/shared/ts/src/conversation/fixtures/c41f18c5.frames.json"
)


def test_the_founder_conversations_patches_are_the_frames_the_clients_replay() -> None:
    log = _founder_log(legacy=False)
    frames = [ConversationEvent(frame=patch).model_dump(mode="json") for patch in log.patches]
    assert json.loads(_FOUNDER_FRAMES.read_text()) == frames


def test_work_lists_the_approvals_it_waits_on_until_each_is_decided() -> None:
    started = WorkStarted(id="work:t1", task_id="t1", cause_through=1, answers=("u1",))
    log = [logged(1, user("u1")), logged(2, started), logged(3, asked("ask:a1", "t1", "a1"))]
    [_, waiting] = project_screen(log)
    assert waiting.kind is ScreenItemKind.WORK
    assert [request.approval_id for request in waiting.asking] == ["a1"]
    [_, decided_work] = project_screen([*log, logged(4, decided("dec:a1", "a1"))])
    assert decided_work.kind is ScreenItemKind.WORK
    assert decided_work.asking == ()
