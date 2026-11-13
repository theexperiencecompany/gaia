"""The one way anything outside the step enters a conversation's log: append, publish, run effects."""

from dataclasses import dataclass, field

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
from app.models.work_cancel_models import WorkCancelled
from app.services.conversation.ports import Appended, Effects, Frames, RuntimePorts
from shared.py.wide_events import log


@dataclass(frozen=True)
class Accepted:
    """A durable append, the effects that raised after it, and what its CancelWork cancelled."""

    appended: Appended
    failed_effects: tuple[Effect, ...]
    cancelled: WorkCancelled = field(default_factory=WorkCancelled)

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
    failed: list[Effect] = []
    cancelled = WorkCancelled()
    for effect in appended.effects:
        try:
            outcome = await _run(ports.effects, conversation_id, user_id, effect)
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
            failed.append(effect)
            continue
        cancelled = outcome or cancelled
    return Accepted(appended=appended, failed_effects=tuple(failed), cancelled=cancelled)


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


async def _run(
    effects: Effects, conversation_id: str, user_id: str, effect: Effect
) -> WorkCancelled | None:
    """Run one effect; a CancelWork returns what it cancelled."""
    match effect:
        case KickStep():
            await effects.kick(conversation_id, user_id)
        case CancelWork():
            return await effects.cancel_work(conversation_id, user_id, effect)
        case StartAck(message_id=message_id):
            await effects.start_ack(conversation_id, user_id, message_id)
        case Preempt():
            pass
    return None
