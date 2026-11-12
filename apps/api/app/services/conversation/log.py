"""The one way anything outside the step enters a conversation's log: append, publish, run effects."""

from dataclasses import dataclass

from app.models.conversation_frame_models import EntryFrame, LiveTask, StateFrame
from app.models.conversation_log_models import (
    CancelWork,
    ConversationState,
    Effect,
    Entry,
    KickStep,
    Preempt,
    StartAck,
)
from app.services.conversation.ports import Appended, Effects, Frames, RuntimePorts
from shared.py.wide_events import log


@dataclass(frozen=True)
class Accepted:
    """A durable append and the effects that raised after it."""

    appended: Appended
    failed_effects: tuple[Effect, ...]

    @property
    def kick_failed(self) -> bool:
        """Return whether no step was started for the entry, so the caller must retry the kick."""
        return any(isinstance(effect, KickStep) for effect in self.failed_effects)


async def accept(ports: RuntimePorts, conversation_id: str, user_id: str, entry: Entry) -> Accepted:
    """Append entry, publish it, and run its effects; a duplicate does neither."""
    appended = await ports.log.append(conversation_id, user_id, entry)
    if appended.duplicate:
        return Accepted(appended=appended, failed_effects=())
    await publish_appended(ports.frames, conversation_id, appended)
    failed = [
        effect
        for effect in appended.effects
        if not await _ran(ports.effects, conversation_id, user_id, effect)
    ]
    return Accepted(appended=appended, failed_effects=tuple(failed))


async def publish_appended(frames: Frames, conversation_id: str, appended: Appended) -> None:
    """Publish an appended entry, then the state when what a client shows changed."""
    logged = appended.logged
    await frames.publish(
        conversation_id, EntryFrame(seq=logged.seq, at=logged.at, entry=logged.entry)
    )
    before, after = state_frame(appended.previous), state_frame(appended.state)
    if (before.display, before.work) != (after.display, after.work):
        await frames.publish(conversation_id, after)


def state_frame(state: ConversationState) -> StateFrame:
    """Return the frame a client shows the conversation's status from."""
    work = tuple(
        LiveTask(task_id=item.task_id, awaiting_approval=bool(item.pending_approvals))
        for item in state.work
    )
    return StateFrame(head=state.head, display=state.display, work=work)


async def _ran(effects: Effects, conversation_id: str, user_id: str, effect: Effect) -> bool:
    try:
        match effect:
            case KickStep():
                await effects.kick(conversation_id, user_id)
            case CancelWork(task_ids=task_ids):
                await effects.cancel_work(conversation_id, user_id, task_ids)
            case StartAck(message_id=message_id):
                await effects.start_ack(conversation_id, user_id, message_id)
            case Preempt():
                pass
    except (
        Exception
    ) as error:  # the entry is already durable; the caller gets the failed effect back
        log.error(
            "conversation effect failed after its entry was appended",
            effect=type(effect).__name__,
            error=str(error),
            error_type=type(error).__name__,
            conversation_id=conversation_id,
        )
        return False
    return True
