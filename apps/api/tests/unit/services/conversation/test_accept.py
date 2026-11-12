"""accept: append, publish the entry and any display change, then run the effects in order."""

from app.models.conversation_frame_models import EntryFrame, LiveTask, StateFrame
from app.models.conversation_log_models import CancelWork, DisplayState, KickStep, StartAck
from app.services.conversation.log import accept
from tests.unit.services.conversation.log_helpers import started, stop, user
from tests.unit.services.conversation.runtime_doubles import (
    CONVERSATION,
    USER,
    EffectCall,
    Runtime,
)


async def test_accept_publishes_the_entry_and_runs_the_effects_in_order() -> None:
    rt = Runtime()
    accepted = await accept(rt.ports, CONVERSATION, USER, user("u1"))
    assert rt.frames.published == [
        EntryFrame(seq=1, at=accepted.appended.logged.at, entry=user("u1"))
    ]
    assert rt.effects.calls == [EffectCall("kick"), EffectCall("start_ack", "u1")]
    assert (accepted.failed_effects, accepted.kick_failed) == ((), False)


async def test_a_duplicate_publishes_nothing_and_runs_no_effects() -> None:
    rt = Runtime()
    await accept(rt.ports, CONVERSATION, USER, user("u1"))
    rt.frames.published.clear()
    rt.effects.calls.clear()
    again = await accept(rt.ports, CONVERSATION, USER, user("u1"))
    assert again.appended.duplicate
    assert (rt.frames.published, rt.effects.calls) == ([], [])


async def test_a_display_change_publishes_a_state_frame_after_the_entry() -> None:
    rt = Runtime()
    await accept(rt.ports, CONVERSATION, USER, user("u1"))
    rt.frames.published.clear()
    await accept(rt.ports, CONVERSATION, USER, started("w", "t1", 1))
    assert [frame.kind for frame in rt.frames.published] == ["entry", "state"]
    assert rt.frames.published[-1] == StateFrame(
        head=2,
        display=DisplayState.WORKING,
        work=(LiveTask(task_id="t1", awaiting_approval=False),),
    )


async def test_a_failing_effect_keeps_the_entry_and_the_rest_still_run() -> None:
    rt = Runtime()
    await accept(rt.ports, CONVERSATION, USER, user("u1"))
    await accept(rt.ports, CONVERSATION, USER, started("w", "t1", 1))
    rt.effects.calls.clear()
    rt.effects.failing = frozenset({"cancel_work"})
    accepted = await accept(rt.ports, CONVERSATION, USER, stop("s"))
    assert rt.entries()[-1].entry == stop("s")
    assert accepted.failed_effects == (CancelWork(task_ids=("t1",)),)
    assert not accepted.kick_failed
    rt.effects.failing = frozenset({"kick"})
    accepted = await accept(rt.ports, CONVERSATION, USER, user("u4"))
    assert rt.entries()[-1].entry == user("u4")
    assert rt.effects.calls[-2:] == [EffectCall("kick"), EffectCall("start_ack", "u4")]
    assert (accepted.failed_effects, accepted.kick_failed) == ((KickStep(),), True)
    assert StartAck(message_id="u4") in accepted.appended.effects
