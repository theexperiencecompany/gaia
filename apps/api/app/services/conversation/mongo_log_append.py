"""Appending to the conversation log: seq order and the fold, committed by one conditional write on the head."""

import asyncio
import random

from app.constants.chat import CONVERSATION_APPEND_JITTER_SECONDS, CONVERSATION_APPEND_MAX_ATTEMPTS
from app.db.repositories.conversation_entries import stored_at
from app.db.repositories.conversation_log_append import LogHead
from app.models.conversation_log_models import (
    Entry,
    KickStep,
    LoggedEntry,
    Notice,
    Rejected,
    ReplySettled,
    StepClaim,
    TodoWoke,
    UserMessage,
)
from app.services.conversation.mongo_log_base import MongoLogBase
from app.services.conversation.mongo_log_hint import publish_hint
from app.services.conversation.ports import Appended, ClaimLost, EntryRejected
from app.services.conversation.reducer import reduce, stamped
from app.utils.errors import ConversationStoreError
from shared.py.conversation_wire import ReplyOutcome

_JITTER = random.SystemRandom()


class LogAppends(MongoLogBase):
    """Store each entry at the next seq, once per id, stamped with the clock."""

    async def append(self, conversation_id: str, user_id: str, entry: Entry) -> Appended:
        """Store entry at the next seq; the same id again returns the stored entry as a duplicate, with the current state and no effects."""
        return await self._append(conversation_id, user_id, entry, epoch=None)

    async def append_fenced(self, claim: StepClaim, entry: Entry) -> Appended:
        """Append only while claim holds the current epoch; raise ClaimLost otherwise."""
        return await self._append(claim.conversation_id, claim.user_id, entry, epoch=claim.epoch)

    async def _append(
        self, conversation_id: str, user_id: str, entry: Entry, *, epoch: int | None
    ) -> Appended:
        unread = await self._marks_unread(conversation_id, user_id, entry)
        for _ in range(CONVERSATION_APPEND_MAX_ATTEMPTS):
            head = await self._head(conversation_id, user_id, entry.id)
            if epoch is not None and head.holder != epoch:
                raise ClaimLost
            seq = head.known.get(entry.id)
            if seq is not None:
                return await self._duplicate(head, seq)
            logged = LoggedEntry(
                seq=head.log_head + 1,
                at=stored_at(self._clock()),
                entry=stamped(head.state, entry),
            )
            result = reduce(head.state, logged)
            if isinstance(result, Rejected):
                raise EntryRejected(result.reason)
            if await self._repository.commit_log_entry(
                head,
                logged,
                result.state,
                epoch=epoch,
                unread=unread,
                # The step an unfenced entry kicks carries it on its own commits, off the reply's path.
                flush=epoch is not None
                or not any(isinstance(effect, KickStep) for effect in result.effects),
            ):
                await publish_hint(conversation_id, user_id, logged, result.state)
                return Appended(
                    logged=logged,
                    previous=head.state,
                    state=result.state,
                    effects=result.effects,
                    duplicate=False,
                )
            await asyncio.sleep(_JITTER.uniform(0, CONVERSATION_APPEND_JITTER_SECONDS))
        raise ConversationStoreError(
            message=f"append to conversation {conversation_id} lost every conditional write",
            why=f"the head moved under each of {CONVERSATION_APPEND_MAX_ATTEMPTS} attempts",
            meta={"conversation_id": conversation_id},
        )

    async def _marks_unread(self, conversation_id: str, user_id: str, entry: Entry) -> bool:
        """Return whether entry is news the user did not ask for here: a Notice, or a reply answering no message of theirs.

        A todo's write-up never is: its chat is reached from the todo, so it carries no unread dot.
        """
        match entry:
            case Notice():
                return True
            case ReplySettled(outcome=ReplyOutcome.ANSWERED, answers=answers):
                answered = await self._repository.read_log(
                    conversation_id, user_id=user_id, ids=list(answers)
                )
                return not any(
                    isinstance(logged.entry, UserMessage | TodoWoke) for logged in answered or ()
                )
        return False

    async def _duplicate(self, head: LogHead, seq: int) -> Appended:
        """Return the entry already stored at seq: a duplicate changes nothing, so it carries the current state and no effects."""
        entries = await self._repository.read_log(
            head.conversation_id, user_id=head.user_id, after_seq=seq - 1, through_seq=seq
        )
        if not entries or entries[-1].seq != seq:
            raise ConversationStoreError(
                message=f"seq {seq} of conversation {head.conversation_id} holds a message, not a log entry",
                meta={"conversation_id": head.conversation_id, "seq": seq},
            )
        return Appended(
            logged=entries[-1], previous=head.state, state=head.state, effects=(), duplicate=True
        )
