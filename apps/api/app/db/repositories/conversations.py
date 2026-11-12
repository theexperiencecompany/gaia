"""Repository for a conversation's head (the conversations collection) and its entry log (conversation_entries).

Identity is the business key conversation_id scoped to user_id, never Mongo's
ObjectId _id. Messages are entries, one document each, ordered by a seq that
only one conditional head write allocates (append). A committed entry sits in
the head's outbox until a flush copies it into conversation_entries; every
message read unions the two through _read_entries, head first.

Caching is disabled (cache_policy = None). createdAt (ISO string) and
updatedAt (BSON date) are a legacy camelCase pair; each mutating method that
must advance the sync clock bumps updatedAt explicitly.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from datetime import datetime
import random
from typing import ClassVar

from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from app.constants.chat import (
    CONVERSATION_APPEND_JITTER_SECONDS,
    CONVERSATION_APPEND_MAX_ATTEMPTS,
    CONVERSATION_ENTRIES_COLLECTION,
    SUBAGENT_GROUP_TOOL_NAME,
    USER_MESSAGE_TYPE,
)
from app.db.repositories.base import UserScopedRepository
from app.db.repositories.cache import CachePolicy
from app.db.repositories.conversation_entries import (
    DROP_EMBEDDED_STAGE,
    EMBEDDED_STATE_STAGE,
    FOLDED_CARDS_FIELD,
    LOG_HEAD_FIELD,
    OUTBOX_FIELD,
    UNMIGRATED_HEADS,
    EntryWindow,
    Head,
    StoredRow,
    absorbing,
    at_its_seq,
    at_log_head,
    filled,
    head_fields,
    head_from_raw,
    head_with_existing,
    is_same_entry,
    outbox_entries_matching,
    parked,
    still_waiting,
    store_errors,
    stored_message,
    stored_row,
    unmigrated,
)
from app.models.artifact_models import ArtifactRegistryEntry
from app.models.chat_models import (
    BOT_CONVERSATION_SOURCES,
    ConversationSource,
    ConversationSyncItem,
    MessageModel,
    SavedSubagentGroup,
    SystemPurpose,
    ToolDataEntry,
)
from app.models.conversation_models import (
    ConversationDescriptionHit,
    ConversationDocument,
    ConversationEntry,
    ConversationHead,
    ConversationMessageHit,
    ConversationSearchResults,
    ConversationSummary,
    ConversationUpdate,
    StoredEntry,
    _ConversationIdRow,
    _ConversationOwnerRow,
    _SourceRow,
    _SystemGeneratedRow,
    _TodoBindingRow,
)
from app.utils.errors import (
    ConversationNotFoundError,
    ConversationStoreError,
)
from shared.py.wide_events import spawn_logged_task

_JITTER = random.SystemRandom()
_BOT_SOURCE_VALUES: list[str] = [s.value for s in BOT_CONVERSATION_SOURCES]
_NEWEST_FIRST: list[tuple[str, int]] = [("seq", -1)]
_OUTBOX_FIELDS: dict[str, object] = {"conversation_id": 1, "user_id": 1, OUTBOX_FIELD: 1}
_ENTRY_KEY_FIELDS: dict[str, object] = {"_id": 0, "id": 1, "seq": 1}
_SUMMARY_PROJECTION: dict[str, object] = {
    "_id": 0,
    "conversation_id": 1,
    "user_id": 1,
    "description": 1,
    "starred": 1,
    "is_system_generated": 1,
    "system_purpose": 1,
    "is_unread": 1,
    "source": 1,
    "has_live_approval": 1,
    "createdAt": 1,
    "updatedAt": 1,
}


class ConversationRepository(UserScopedRepository[ConversationDocument, ConversationUpdate]):
    """The conversations collection repository (the chat hot path).

    Identity is the business key conversation_id; caching is disabled
    (see the module docstring for why)."""

    collection_name = "conversations"
    document_model = ConversationDocument
    update_model = ConversationUpdate
    uses_object_id = True
    identity_field = "conversation_id"
    cache_policy: ClassVar[CachePolicy | None] = None

    # ---- conversation-list reads (projected: no messages) ----

    async def list_starred_summaries(self, user_id: str) -> list[ConversationSummary]:
        """Return the user's starred conversations (projected summaries, newest first)."""
        return await self._aggregate(
            [
                {"$match": {"user_id": user_id, "starred": True, **self._listed()}},
                {"$sort": {"createdAt": -1}},
                {"$project": _SUMMARY_PROJECTION},
            ],
            ConversationSummary,
        )

    async def list_active_summaries(
        self, user_id: str, *, skip: int, limit: int
    ) -> list[ConversationSummary]:
        """Paginated active conversation summaries for the sidebar, newest first."""
        return await self._aggregate(
            [
                {"$match": self._active_filter(user_id)},
                {"$sort": {"createdAt": -1}},
                {"$skip": skip},
                {"$limit": limit},
                {"$project": _SUMMARY_PROJECTION},
            ],
            ConversationSummary,
        )

    async def count_active(self, user_id: str) -> int:
        """How many active (non-starred, non-bot) conversations the user has."""
        return await self._count(self._active_filter(user_id))

    async def count_non_onboarding(self, user_id: str) -> int:
        """Real (non-onboarding) conversations for a user — the chat-usage signal.

        Excludes onboarding demo conversations."""
        return await self._count(
            {
                "user_id": user_id,
                "is_onboarding_demo": {"$ne": True},
                # A tracked todo's chat is its runs' log, not a chat the user had.
                "todo_id": None,
            }
        )

    async def has_activity_since(self, user_id: str, since: datetime) -> bool:
        """Whether the user touched any conversation at or after since.

        The transport-agnostic usage signal (unlike users.last_active_at,
        which only a WorkOS web login bumps). updatedAt is a BSON date and
        createdAt an ISO string; Mongo does not compare across BSON types, so
        each is compared against its own type rather than one shared filter.
        """
        return (
            await self._count(
                {
                    "user_id": user_id,
                    # Excludes system-generated conversations: counting a workflow's
                    # own updatedAt bumps would let a user's automation vouch for
                    # them as "active" forever, defeating the dormancy sweep.
                    "is_system_generated": {"$ne": True},
                    # Same for a tracked todo's chat, bumped by every run's report.
                    "todo_id": None,
                    "$or": [
                        {"updatedAt": {"$gte": since}},
                        {"createdAt": {"$gte": since.isoformat()}},
                    ],
                }
            )
            > 0
        )

    async def has_sent_message(self, user_id: str) -> bool:
        """Whether the user has ever sent a message, from any surface.

        Workflow-execution threads also carry user messages (the workflow's
        own prompt), so system-generated conversations are excluded — the
        signal is a human typing, not an automation running.
        """
        sent = await self._first_entry(
            user_id, {"type": USER_MESSAGE_TYPE}, excluding={"is_system_generated": True}
        )
        return sent is not None

    async def owned_ids(self, user_id: str, conversation_ids: Sequence[str]) -> set[str]:
        """Which of these conversation ids the user owns."""
        return set(
            await self._distinct(
                "conversation_id",
                {"user_id": user_id, "conversation_id": {"$in": list(conversation_ids)}},
            )
        )

    async def exists(self, conversation_id: str, *, user_id: str) -> bool:
        """Whether the user owns a conversation with this id."""
        return await self._count({"conversation_id": conversation_id, "user_id": user_id}) > 0

    # ---- conversation-level writes (bump updatedAt) ----

    async def set_starred(self, conversation_id: str, *, user_id: str, starred: bool) -> bool:
        """Set the conversation's starred flag."""
        return await self._set_fields(conversation_id, user_id, {"starred": starred})

    async def set_description(
        self, conversation_id: str, *, user_id: str, description: str
    ) -> bool:
        """Set the conversation's summary description."""
        return await self._set_fields(conversation_id, user_id, {"description": description})

    async def set_unread(self, conversation_id: str, *, user_id: str, unread: bool) -> bool:
        """Set the conversation's unread flag."""
        return await self._set_fields(conversation_id, user_id, {"is_unread": unread})

    async def set_workflow_binding(
        self, conversation_id: str, *, user_id: str, workflow_id: str, workflow_title: str
    ) -> bool:
        """Bind an existing conversation to a workflow (source + metadata); does not advance updatedAt."""
        matched = await self._apply_raw_update_unfetched(
            {"conversation_id": conversation_id},
            {
                "$set": {
                    "source": ConversationSource.WORKFLOW_SYSTEM.value,
                    "metadata": {
                        "workflow_id": workflow_id,
                        "workflow_title": workflow_title,
                        "created_by": ConversationSource.WORKFLOW_SYSTEM.value,
                    },
                }
            },
            scope=user_id,
            doc_id=conversation_id,
            extra_filter={"user_id": user_id},
        )
        return matched > 0

    async def mark_background_with_live_approval(
        self, conversation_id: str, *, user_id: str
    ) -> bool:
        """Flag a background run's conversation while it holds a live approval.

        Stamps source BACKGROUND only when unset (never overwrites a real
        channel), and raises the sidebar flag. No-op when the conversation
        does not exist yet — the later persist carries no source either way,
        and the next register/publish for the same owner retries the stamp.
        """
        matched = await self._apply_raw_update_unfetched(
            {"conversation_id": conversation_id},
            {"$set": {"has_live_approval": True}},
            scope=user_id,
            doc_id=conversation_id,
            extra_filter={"user_id": user_id},
        )
        if matched:
            # pragma: no mutate start — scope/doc_id repeat the eviction the write above just
            # made, so no read can observe them; mutmut cannot pragma a single argument.
            await self._apply_raw_update_unfetched(
                {"conversation_id": conversation_id, "source": {"$exists": False}},
                {"$set": {"source": ConversationSource.BACKGROUND.value}},
                scope=user_id,
                doc_id=conversation_id,
                extra_filter={"user_id": user_id},
            )
            # pragma: no mutate end
        return matched > 0

    async def refresh_live_approval_flag(
        self, conversation_id: str, *, user_id: str, live: bool
    ) -> bool:
        """Rewrite the sidebar flag from a fresh live-rows read (ledger side).

        Plain setter by design: the caller (bridge sync helper) owns the
        ledger read, this owns the conversation write — one collection each.
        """
        matched = await self._apply_raw_update_unfetched(
            {"conversation_id": conversation_id},
            {"$set": {"has_live_approval": live}},
            scope=user_id,
            doc_id=conversation_id,
            extra_filter={"user_id": user_id},
        )
        return matched > 0

    # ---- the entry log: append, flush, read ----

    async def append(
        self, conversation_id: str, *, user_id: str, entries: Sequence[MessageModel]
    ) -> list[int]:
        """Commit entries at consecutive seqs in one conditional head write, returning each one's seq.

        All or none. An id already committed is not appended again; its seq is returned.
        Raises ConversationNotFoundError for a missing conversation, writing nothing.
        """
        batch: dict[str, dict[str, object]] = {}
        for message in entries:
            if message.message_id is None:
                raise ValueError("an appended entry carries its producer-minted id")
            batch.setdefault(message.message_id, stored_message(message))
        ids = [str(message.message_id) for message in entries]
        for _ in range(CONVERSATION_APPEND_MAX_ATTEMPTS):
            head = await self._read_head_for_append(conversation_id, user_id, list(batch))
            if head is None:
                raise ConversationNotFoundError(
                    message=f"conversation {conversation_id} does not exist for this user",
                    meta={"conversation_id": conversation_id},
                )
            known = head.known_seqs()
            fresh = [(entry_id, data) for entry_id, data in batch.items() if entry_id not in known]
            if not fresh:
                if head.outbox:
                    self._spawn_flush(conversation_id, user_id)
                return [known[entry_id] for entry_id in ids]
            seqs = {entry_id: head.log_head + n for n, (entry_id, _) in enumerate(fresh, 1)}
            if await self._commit(conversation_id, user_id, head.log_head, fresh, seqs):
                self._spawn_flush(conversation_id, user_id)
                return [known.get(entry_id) or seqs[entry_id] for entry_id in ids]
            await asyncio.sleep(_backoff())
        raise ConversationStoreError(
            message=f"append to conversation {conversation_id} lost every conditional write",
            why=f"the head moved under each of {CONVERSATION_APPEND_MAX_ATTEMPTS} attempts",
            meta={"conversation_id": conversation_id},
        )

    async def flush_outbox(self, conversation_id: str, *, user_id: str) -> None:
        """Copy every outbox entry into conversation_entries, then drop it from the head: insert first, always."""
        # Reads only the outbox: what is committed is flushed whatever the embedded array holds.
        head = {"conversation_id": conversation_id, "user_id": user_id}
        with store_errors("flush"):  # pragma: no mutate — error label only
            # The projection only trims the read: the head model ignores every other field.
            raw = await self._raw_collection().find_one(head, _OUTBOX_FIELDS)  # pragma: no mutate
        outbox = ConversationHead.model_validate(raw).outbox if raw else {}
        if not outbox:
            return
        # pragma: no mutate start — $unset ignores the value
        drained = {f"{OUTBOX_FIELD}.{seq}": "" for seq in outbox}
        # pragma: no mutate end
        with store_errors("flush"):  # pragma: no mutate — error label only
            await self._insert_entries(list(outbox.values()))
            unset = await self._raw_collection().update_one(head, {"$unset": drained})
            if not unset.matched_count:
                # The conversation was deleted while this flush ran: take back what it inserted.
                await self._sibling_collection(CONVERSATION_ENTRIES_COLLECTION).delete_many(
                    {
                        "user_id": user_id,
                        "conversation_id": conversation_id,
                        "seq": {"$in": list(outbox)},
                    }
                )

    async def append_messages(
        self, conversation_id: str, *, user_id: str, messages: Sequence[MessageModel]
    ) -> dict[str, int] | None:
        """Append messages to a conversation, returning each id's seq in order (None if it does not exist).

        Each message takes the folded cards waiting for its id in the same commit.
        """
        stamped = [
            message
            if message.message_id is not None
            else message.model_copy(update={"message_id": str(ObjectId())})
            for message in messages
        ]
        try:
            seqs = await self.append(conversation_id, user_id=user_id, entries=stamped)
        except ConversationNotFoundError:
            return None
        return {str(message.message_id): seqs[n] for n, message in enumerate(stamped)}

    async def park_folded_cards(
        self,
        conversation_id: str,
        *,
        user_id: str,
        message_id: str,
        entries: Sequence[Mapping[str, object]],
    ) -> bool:
        """Leave cards for message_id until its save absorbs them; False once it is saved.

        Parks only at the log_head its read saw, so no commit of the message slips between.
        """
        for _ in range(CONVERSATION_APPEND_MAX_ATTEMPTS):
            head = await self._read_head_for_append(conversation_id, user_id, [message_id])
            if head is None or message_id in head.known_seqs():
                return False
            with store_errors("park folded cards"):  # pragma: no mutate — error label only
                matched = await self._apply_pipeline_update_unfetched(
                    {"conversation_id": conversation_id, **at_log_head(head.log_head)},
                    [{"$set": {FOLDED_CARDS_FIELD: parked(message_id, entries)}}],
                    # The waiting room is write-side only: no cached read shows it.
                    scope=None,
                    extra_filter={"user_id": user_id},
                )
            if matched:
                return True
            await asyncio.sleep(_backoff())
        raise ConversationStoreError(
            message=f"parking cards on conversation {conversation_id} lost every conditional write",
            meta={"conversation_id": conversation_id},
        )

    async def set_message_pinned(
        self, conversation_id: str, *, user_id: str, message_id: str, pinned: bool
    ) -> bool:
        """Set one message's pinned flag and advance the conversation's updatedAt."""
        if not await self._update_entry(
            conversation_id, user_id, {"id": message_id}, {"$set": {"pinned": pinned}}
        ):
            return False
        await self._set_fields(conversation_id, user_id)
        return True

    async def update_artifact(
        self, conversation_id: str, *, user_id: str, path: str, fields: Mapping[str, object]
    ) -> bool:
        """Patch the registry entry at path; False when no entry exists yet."""
        matched = await self._apply_raw_update_unfetched(
            {"conversation_id": conversation_id, "artifacts.path": path},
            {
                "$set": {f"artifacts.$.{key}": value for key, value in fields.items()},
                "$currentDate": {"updatedAt": True},
            },
            scope=user_id,
            doc_id=conversation_id,
            extra_filter={"user_id": user_id},
        )
        return matched > 0

    async def push_artifact(
        self, conversation_id: str, *, user_id: str, path: str, element: Mapping[str, object]
    ) -> None:
        """Append a registry entry, but only when path is not already present.

        The $ne guard is what makes concurrent inserts idempotent: of two
        racing pushes for the same path, only one can match the filter.
        """
        await self._apply_raw_update_unfetched(
            {"conversation_id": conversation_id, "artifacts.path": {"$ne": path}},
            {"$push": {"artifacts": element}, "$currentDate": {"updatedAt": True}},
            scope=user_id,
            doc_id=conversation_id,
            extra_filter={"user_id": user_id},
        )

    async def remove_artifact(self, conversation_id: str, *, user_id: str, path: str) -> None:
        """Remove one artifact entry from the conversation's artifact registry."""
        await self._apply_raw_update_unfetched(
            {"conversation_id": conversation_id},
            {"$pull": {"artifacts": {"path": path}}, "$currentDate": {"updatedAt": True}},
            scope=user_id,
            doc_id=conversation_id,
            extra_filter={"user_id": user_id},
        )

    async def list_artifacts(
        self, conversation_id: str, *, user_id: str
    ) -> list[ArtifactRegistryEntry]:
        """Return the conversation's artifact registry, or an empty list when it has none."""
        document = await self._find_one({"conversation_id": conversation_id, "user_id": user_id})
        return list(document.artifacts) if document else []

    async def append_message_tool_data(
        self,
        conversation_id: str,
        *,
        user_id: str,
        message_id: str,
        entries: Sequence[Mapping[str, object]],
    ) -> bool:
        """Append tool-data entries onto one message; does not advance updatedAt."""
        return await self._update_entry(
            conversation_id,
            user_id,
            {"id": message_id},
            {"$push": {"tool_data": {"$each": [dict(entry) for entry in entries]}}},
        )

    async def extend_subagent_group(
        self, conversation_id: str, *, user_id: str, message_id: str, group: SavedSubagentGroup
    ) -> bool:
        """Append calls to one saved subagent group in place and stamp its end; False when absent."""
        path = "tool_data.$[group].data"
        return await self._update_entry(
            conversation_id,
            user_id,
            {"id": message_id, "tool_data.data.subagent_id": group.subagent_id},
            {
                "$push": {f"{path}.tool_calls": {"$each": group.tool_calls}},
                "$set": {
                    f"{path}.completed_at": group.completed_at,
                    f"{path}.duration_ms": group.duration_ms,
                },
            },
            array_filters=[
                {
                    "group.tool_name": SUBAGENT_GROUP_TOOL_NAME,
                    "group.data.subagent_id": group.subagent_id,
                }
            ],
        )

    async def fill_message(
        self, conversation_id: str, *, user_id: str, message: MessageModel
    ) -> bool:
        """Replace an opened entry's content with message in place, keeping its seq; False when absent.

        Cards folded into the entry since it was opened stay, after message's own.
        """
        return await self._update_entry(
            conversation_id, user_id, {"id": message.message_id}, filled(message)
        )

    async def fail_unfinished_replies(
        self, *, opened_before: datetime, error: str, owners: set[tuple[str, str]]
    ) -> int:
        """Settle the replies in progress since before opened_before in owners' conversations as failed with error.

        owners holds (user_id, conversation_id) pairs. Intentionally unscoped (a maintenance sweep).
        """
        if not owners:
            return 0
        with store_errors("unfinished reply sweep"):
            result = await self._sibling_collection(CONVERSATION_ENTRIES_COLLECTION).update_many(
                {
                    "in_progress": True,
                    "at": {"$lt": opened_before},
                    "$or": [
                        {"user_id": user_id, "conversation_id": conversation_id}
                        for user_id, conversation_id in sorted(owners)
                    ],
                },
                {"$set": {"error": error}, "$unset": {"in_progress": ""}},
            )
        return result.modified_count

    async def list_unfinished_reply_owners(
        self, *, opened_before: datetime
    ) -> set[tuple[str, str]]:
        """Return the (user_id, conversation_id) of every reply in progress since before opened_before.

        Intentionally unscoped (a maintenance sweep).
        """
        with store_errors("unfinished reply sweep"):
            rows = await (
                self._sibling_collection(CONVERSATION_ENTRIES_COLLECTION)
                .find(
                    {"in_progress": True, "at": {"$lt": opened_before}},
                    {"_id": 0, "user_id": 1, "conversation_id": 1},
                )
                .to_list(length=None)
            )
        owners = [_ConversationOwnerRow.model_validate(row) for row in rows]
        return {(owner.user_id, owner.conversation_id) for owner in owners}

    async def set_message_response(
        self, conversation_id: str, *, user_id: str, message_id: str, response: str
    ) -> bool:
        """Set a message's response text in place; does not advance updatedAt."""
        return await self._update_entry(
            conversation_id, user_id, {"id": message_id}, {"$set": {"response": response}}
        )

    async def set_message_tool_data(
        self, conversation_id: str, *, user_id: str, message_id: str, entries: list[ToolDataEntry]
    ) -> bool:
        """Replace a message's tool_data wholesale; does not advance updatedAt."""
        return await self._update_entry(
            conversation_id,
            user_id,
            {"id": message_id},
            {"$set": {"tool_data": [dict(entry) for entry in entries]}},
        )

    async def set_message_approval_status(
        self, conversation_id: str, *, user_id: str, approval_id: str, status: str
    ) -> bool:
        """Settle a persisted approval_request frame's status on every message holding it.

        Returns whether the frame was there to settle. Does not advance updatedAt.
        """
        return await self._update_entry(
            conversation_id,
            user_id,
            {"tool_data.data.approval_id": approval_id},
            {"$set": {"tool_data.$[entry].data.status": status}},
            array_filters=[{"entry.data.approval_id": approval_id}],
            every_match=True,
        )

    async def set_message_follow_up_actions(
        self, conversation_id: str, *, user_id: str, message_id: str, actions: list[str]
    ) -> bool:
        """Set a message's follow-up actions; does not advance updatedAt."""
        return await self._update_entry(
            conversation_id, user_id, {"id": message_id}, {"$set": {"follow_up_actions": actions}}
        )

    # ---- targeted / projected reads ----

    async def get(self, doc_id: str, *, user_id: str) -> ConversationDocument | None:
        """Read the conversation with its full message history, oldest first."""
        heads = await self._read_heads({"conversation_id": doc_id, "user_id": user_id})
        if not heads:
            return None
        [(head, entries)] = await self._entries_for(heads)
        return self._with_messages(head, entries)

    async def get_message(
        self, conversation_id: str, message_id: str, *, user_id: str
    ) -> ConversationEntry | None:
        """Read one message by id, without reading the rest of the conversation."""
        entries = await self._read_entries(
            conversation_id, user_id=user_id, window=EntryWindow(ids=[message_id])
        )
        return entries[0] if entries else None

    async def list_recent_messages(
        self, conversation_id: str, *, user_id: str, limit: int
    ) -> list[ConversationEntry]:
        """Return the conversation's newest limit messages, oldest first; empty when it does not exist."""
        return await self._read_entries(
            conversation_id, user_id=user_id, window=EntryWindow(limit=limit)
        )

    async def get_source(self, conversation_id: str, *, user_id: str) -> ConversationSource | None:
        """Return the conversation's source enum, or None when it doesn't exist."""
        row = await self._find_one_projected(
            {"conversation_id": conversation_id, "user_id": user_id},
            {"_id": 0, "source": 1},
            _SourceRow,
        )
        return None if row is None else ConversationSource.coerce(row.source)

    async def owner_ids(self, conversation_id: str) -> set[str]:
        """Every user holding a conversation under this id; more than one means they share its agent thread."""
        return set(await self._distinct("user_id", {"conversation_id": conversation_id}))

    async def is_system_generated(self, conversation_id: str) -> bool:
        """Whether GAIA created this conversation itself (workflow/email/reminder runs).

        Passive memory ingestion asks before learning from a transcript: a
        workflow execution is GAIA talking to itself, and its "user" turn is a
        generated instruction, not a disclosure by the person.
        """
        row = await self._find_one_projected(
            {"conversation_id": conversation_id},
            {"_id": 0, "is_system_generated": 1},
            _SystemGeneratedRow,
        )
        return bool(row and row.is_system_generated)

    async def is_workflow_execution(self, conversation_id: str) -> bool:
        """Whether this is the conversation a workflow's runs execute in.

        Narrower than is_system_generated: email and reminder runs are
        system-generated too, and the workflow thread reset must not touch them.
        """
        row = await self._find_one_projected(
            {"conversation_id": conversation_id},
            {"_id": 0, "is_system_generated": 1, "system_purpose": 1},
            _SystemGeneratedRow,
        )
        return bool(
            row
            and row.is_system_generated
            and row.system_purpose == SystemPurpose.WORKFLOW_EXECUTION
        )

    async def find_owner_of_message(
        self, user_id: str, message_id: str, *, message_type: str = "bot"
    ) -> str | None:
        """Return the conversation id owning a message of message_type with this id."""
        found = await self._first_entry(user_id, {"id": message_id, "type": message_type})
        return None if found is None else found[0]

    async def find_workflow_conversation_id(self, user_id: str, workflow_id: str) -> str | None:
        """Return the id of the system-generated conversation a workflow's runs execute in."""
        row = await self._find_one_projected(
            {
                "user_id": user_id,
                "is_system_generated": True,
                "system_purpose": SystemPurpose.WORKFLOW_EXECUTION.value,
                "metadata.workflow_id": workflow_id,
            },
            {"_id": 0, "conversation_id": 1},
            _ConversationIdRow,
        )
        return None if row is None else row.conversation_id

    async def recent_for_user(self, user_id: str, *, limit: int) -> list[ConversationDocument]:
        """Return the user's most recent conversations, each with its full message history."""
        heads = await self._read_heads({"user_id": user_id}, sort={"createdAt": -1}, limit=limit)
        return [
            self._with_messages(head, entries) for head, entries in await self._entries_for(heads)
        ]

    async def find_todo_conversation_id(self, user_id: str, todo_id: str) -> str | None:
        """Return the id of the chat bound to a tracked todo, or None before its first open or run."""
        row = await self._find_one_projected(
            {"user_id": user_id, **_todo_binding(todo_id)},
            # Equivalent under mutation: any truthy flag projects the field, and the row ignores _id.
            {"_id": 0, "conversation_id": 1},  # pragma: no mutate
            _ConversationIdRow,
        )
        return None if row is None else row.conversation_id

    async def get_todo_id(self, conversation_id: str, *, user_id: str) -> str | None:
        """Return the tracked todo this conversation belongs to, or None for any other chat."""
        row = await self._find_one_projected(
            {"conversation_id": conversation_id, "user_id": user_id},
            # Equivalent under mutation: any truthy flag projects the field, and the row ignores _id.
            {"_id": 0, "todo_id": 1},  # pragma: no mutate
            _TodoBindingRow,
        )
        return None if row is None else row.todo_id

    async def create(self, doc: ConversationDocument) -> ConversationDocument:
        """Insert the conversation's head at an empty log; messages are appended separately."""
        head = doc.model_dump(exclude={"id", "messages"}, exclude_none=True)
        head[LOG_HEAD_FIELD] = 0
        await self._raw_collection().insert_one(head)
        created = await self.get(doc.conversation_id, user_id=doc.user_id)
        if created is None:
            # pragma: no mutate start — error text only
            raise ConversationStoreError(message="inserted conversation could not be read back")
            # pragma: no mutate end
        return created

    async def try_create(self, doc: ConversationDocument) -> bool:
        """Insert the conversation; False when a unique index already holds its key.

        The partial unique index on (user_id, todo_id) admits one chat per tracked
        todo, so the loser of a creation race learns it here instead of duplicating it.
        """
        try:
            await self.create(doc)
        except DuplicateKeyError:
            return False
        return True

    async def delete(self, doc_id: str, *, user_id: str) -> bool:
        """Delete the conversation and every one of its entries."""
        return bool(await self._delete_conversations({"conversation_id": doc_id}, user_id))

    async def delete_for_todos(self, user_id: str, todo_ids: Sequence[str]) -> list[str]:
        """Delete the chats bound to these todos, returning their ids for checkpoint cleanup."""
        return await self._delete_conversations(_todo_chats(user_id, todo_ids), user_id)

    async def retitle_todo_chats(
        self, user_id: str, todo_ids: Sequence[str], description: str
    ) -> None:
        """Give the chats bound to these todos their todo's new title."""
        for conversation_id in await self._distinct(
            "conversation_id", _todo_chats(user_id, todo_ids)
        ):
            await self._set_fields(conversation_id, user_id, {"description": description})

    async def find_updated_since(
        self, user_id: str, items: list[ConversationSyncItem]
    ) -> list[ConversationDocument]:
        """Batch-fetch conversations updated since each item's last-seen timestamp (the client-sync read).

        A missing/unparseable timestamp includes that conversation unconditionally.
        """
        conditions: list[dict[str, object]] = []
        for item in items:
            condition: dict[str, object] = {
                "user_id": user_id,
                "conversation_id": item.conversation_id,
            }
            if item.last_updated:
                try:
                    cutoff = datetime.fromisoformat(item.last_updated)
                    condition["$or"] = [
                        {"updatedAt": {"$gt": cutoff}},
                        {"updatedAt": {"$exists": False}},
                    ]
                except (ValueError, AttributeError):
                    pass
            conditions.append(condition)
        if not conditions:
            return []
        heads = await self._read_heads({"$or": conditions})
        return [
            self._with_messages(head, entries) for head, entries in await self._entries_for(heads)
        ]

    # ---- search / pinned ----

    async def list_pinned_messages(self, user_id: str) -> list[ConversationMessageHit]:
        """Every pinned message across the user's conversations."""
        return [
            ConversationMessageHit(conversation_id=conversation_id, message=entry)
            for conversation_id, entry in await self._find_entries(user_id, {"pinned": True})
        ]

    async def search(self, user_id: str, *, pattern: str) -> ConversationSearchResults:
        """Regex search across message responses and conversation descriptions.

        pattern is treated as a literal — the caller passes an escaped query.
        """
        regex = {"$regex": pattern, "$options": "i"}
        # A tracked todo's chat is reached from its todo, never from search.
        todo_chat = {"todo_id": {"$type": "string"}}
        hits = await self._find_entries(user_id, {"response": regex}, excluding=todo_chat)
        described = await self._aggregate(
            [
                {"$match": {"user_id": user_id, "todo_id": None, "description": regex}},
                {
                    "$project": {
                        # Equivalent under mutation: the hit model ignores _id.
                        "_id": 0,  # pragma: no mutate
                        "conversation_id": 1,
                        "description": 1,
                    }
                },
            ],
            ConversationDescriptionHit,
        )
        return ConversationSearchResults(
            messages=[
                ConversationMessageHit(conversation_id=conversation_id, message=entry)
                for conversation_id, entry in hits
            ],
            conversations=described,
        )

    # ---- bulk deletes / maintenance sweeps ----

    async def delete_all_for_user(self, user_id: str) -> list[str]:
        """Delete every conversation for a user, returning the deleted ids.

        Callers use the ids to clean up the (non-user-scoped) checkpoint threads.
        """
        return await self._delete_conversations({}, user_id)

    async def delete_all_chats_for_user(self, user_id: str) -> list[str]:
        """Delete the user's chats, keeping each tracked todo's, which goes only with its todo."""
        return await self._delete_conversations({"todo_id": None}, user_id)

    async def delete_onboarding_demos(self, user_id: str) -> int:
        """Delete the user's onboarding-demo conversations."""
        return len(await self._delete_conversations({"is_onboarding_demo": True}, user_id))

    async def all_conversation_ids(self) -> list[str]:
        """Every live conversation id across all users — the checkpoint orphan sweep's source of truth.

        Intentionally unscoped (a maintenance sweep).
        """
        return await self._distinct("conversation_id")

    async def owners_of(self, conversation_ids: Sequence[str]) -> dict[str, str]:
        """Map each existing conversation id to its owner's user id.

        Intentionally unscoped (a maintenance migration that has ids but no user).
        """
        rows = await self._aggregate(
            [
                {"$match": {"conversation_id": {"$in": list(conversation_ids)}}},
                {"$project": {"_id": 0, "conversation_id": 1, "user_id": 1}},
            ],
            _ConversationOwnerRow,
        )
        return {row.conversation_id: row.user_id for row in rows}

    async def active_user_ids_since(self, cutoff: datetime) -> list[str]:
        """User ids with a conversation updated since cutoff — the workspace sync sweep's active-user set.

        Intentionally unscoped (a maintenance sweep).
        """
        return await self._distinct("user_id", {"updatedAt": {"$gte": cutoff}})

    # ---- internal helpers ----

    def _to_model(self, raw: Mapping[str, object]) -> ConversationDocument:
        return super()._to_model(head_fields(raw))

    def _spawn_flush(self, conversation_id: str, user_id: str) -> None:
        spawn_logged_task(
            "conversation_flush",
            self.flush_outbox(conversation_id, user_id=user_id),
            conversation_id=conversation_id,
        )

    async def _read_heads(
        self,
        match: Mapping[str, object],
        *,
        sort: Mapping[str, int] | None = None,
        limit: int = 0,
    ) -> list[Head]:
        """Read heads without their embedded arrays, refusing any the migration has not caught up with."""
        pipeline: list[Mapping[str, object]] = [{"$match": dict(match)}]
        if sort:
            pipeline.append({"$sort": dict(sort)})
        if limit:
            pipeline.append({"$limit": limit})
        pipeline += [EMBEDDED_STATE_STAGE, DROP_EMBEDDED_STAGE]
        with store_errors("head read"):
            raws = await self._raw_collection().aggregate(pipeline).to_list(length=None)
        return [head_from_raw(raw) for raw in raws]

    async def _read_head_for_append(
        self, conversation_id: str, user_id: str, ids: Sequence[str]
    ) -> Head | None:
        """Read the head and which of ids the collection already holds, in one round trip, head first.

        The $lookup runs after its head is read, so an entry flushed out of the outbox in
        between is still seen in the collection.
        """
        entries = self._sibling_collection(CONVERSATION_ENTRIES_COLLECTION).name
        pipeline = head_with_existing(conversation_id, user_id, ids, entries_collection=entries)
        with store_errors("head read"):  # pragma: no mutate — error label only
            raws = await self._raw_collection().aggregate(pipeline).to_list(length=None)
        return head_from_raw(raws[0]) if raws else None

    async def _commit(
        self,
        conversation_id: str,
        user_id: str,
        log_head: int,
        fresh: Sequence[tuple[str, dict[str, object]]],
        seqs: Mapping[str, int],
    ) -> bool:
        """Allocate seqs: the one conditional head write, absorbing each entry's folded cards with it."""
        committed = {
            str(seqs[entry_id]): absorbing(
                entry_id,
                {
                    **data,
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    "seq": seqs[entry_id],
                },
            )
            for entry_id, data in fresh
        }
        with store_errors("append"):  # pragma: no mutate — error label only
            matched = await self._apply_pipeline_update_unfetched(
                {"conversation_id": conversation_id, **at_log_head(log_head)},
                [
                    {
                        "$set": {
                            LOG_HEAD_FIELD: log_head + len(fresh),
                            OUTBOX_FIELD: {
                                "$mergeObjects": [{"$ifNull": [f"${OUTBOX_FIELD}", {}]}, committed]
                            },
                            "updatedAt": "$$NOW",
                            FOLDED_CARDS_FIELD: still_waiting(list(seqs)),
                        }
                    }
                ],
                # Conversations are uncached (cache_policy None): no read to invalidate.
                scope=None,
                extra_filter={"user_id": user_id},
            )
        return matched > 0

    async def _insert_entries(self, entries: Sequence[StoredEntry]) -> None:
        """Insert each outbox entry; one already stored at its seq was flushed before, any other conflict is a bug."""
        collection = self._sibling_collection(CONVERSATION_ENTRIES_COLLECTION)
        for entry in entries:
            try:
                await collection.insert_one(entry.document())
            except DuplicateKeyError as exc:
                at_seq = at_its_seq(entry)
                # The projection only trims the read: the key model ignores every other field.
                stored = await collection.find_one(at_seq, _ENTRY_KEY_FIELDS)  # pragma: no mutate
                if not is_same_entry(stored, entry):
                    raise ConversationStoreError(
                        message="an outbox entry conflicts with a stored entry",
                        why=str(exc),
                    ) from exc

    async def _read_entries(
        self, conversation_id: str, *, user_id: str, window: EntryWindow | None = None
    ) -> list[ConversationEntry]:
        """Read a conversation's entries in window (all, oldest first, by default); empty when it does not exist."""
        heads = await self._read_heads({"conversation_id": conversation_id, "user_id": user_id})
        if not heads:
            return []
        [(_, entries)] = await self._entries_for(heads, window)
        return entries

    async def _entries_for(
        self, heads: Sequence[Head], window: EntryWindow | None = None
    ) -> list[tuple[Head, list[ConversationEntry]]]:
        """Union each head's outbox with its collection entries, up to the log_head the head read saw."""
        window = window or EntryWindow()
        if not heads:
            return []
        clauses = [
            {
                "user_id": head.user_id,
                "conversation_id": head.conversation_id,
                "seq": window.seq_range(head.log_head),
                **window.id_clause(),
            }
            for head in heads
        ]
        # Newest first, so a single head's limit reads only the rows take() keeps.
        cursor = (
            self._sibling_collection(CONVERSATION_ENTRIES_COLLECTION)
            .find({"$or": clauses})
            .sort(_NEWEST_FIRST)
        )
        # pragma: no mutate start — the limit only spares reading rows take() drops
        if window.limit and len(heads) == 1:
            cursor = cursor.limit(window.limit)
        # pragma: no mutate end
        with store_errors("entry read"):  # pragma: no mutate — error label only
            rows = await cursor.to_list(length=None)
        stored: dict[tuple[str, str], dict[int, ConversationEntry]] = {}
        for row in map(stored_row, rows):
            stored.setdefault((row.user_id, row.conversation_id), {})[row.entry.seq] = row.entry
        result: list[tuple[Head, list[ConversationEntry]]] = []
        for head in heads:
            union = dict(stored.get((head.user_id, head.conversation_id), {}))
            for entry in head.pending():
                if window.admits(entry, head.log_head):
                    union.setdefault(entry.seq, entry)
            result.append((head, window.take(union)))
        return result

    async def _find_entries(
        self,
        user_id: str,
        match: Mapping[str, object],
        *,
        excluding: Mapping[str, object] | None = None,
        limit: int = 0,
    ) -> list[tuple[str, ConversationEntry]]:
        """Entries matching match across the user's conversations, outboxes first, then the collection.

        excluding names the heads whose entries never count; limit bounds the collection
        read for callers that need only whether one exists. Refuses a user with a
        conversation the migration has not caught up with, rather than missing its messages.
        """
        with store_errors("entry search"):  # pragma: no mutate — error label only
            if await self._count({"user_id": user_id, **UNMIGRATED_HEADS}):
                raise unmigrated(f"user {user_id}")
            pending = await (
                self._raw_collection()
                .aggregate(outbox_entries_matching(user_id, match, excluding=excluding))
                .to_list(length=None)
            )
            skipped = (
                await self._distinct("conversation_id", {"user_id": user_id, **excluding})
                if excluding
                else []
            )
            cursor = self._sibling_collection(CONVERSATION_ENTRIES_COLLECTION).find(
                {"user_id": user_id, **match, "conversation_id": {"$nin": skipped}}
            )
            # pragma: no mutate start — limit only bounds a read whose callers ask whether one exists
            if limit:
                cursor = cursor.limit(limit)
            # pragma: no mutate end
            rows = await cursor.to_list(length=None)
        found: dict[tuple[str, int], StoredRow] = {}
        for row in map(stored_row, [*pending, *rows]):
            found.setdefault((row.conversation_id, row.entry.seq), row)
        ordered = sorted(found.values(), key=lambda row: (row.at, row.entry.seq))
        return [(row.conversation_id, row.entry) for row in ordered]

    async def _first_entry(
        self,
        user_id: str,
        match: Mapping[str, object],
        *,
        excluding: Mapping[str, object] | None = None,
    ) -> tuple[str, ConversationEntry] | None:
        """Return one (conversation id, entry) matching match across the user's conversations, or None."""
        # pragma: no mutate start — limit only bounds a read whose callers ask whether one exists
        found = await self._find_entries(user_id, match, excluding=excluding, limit=1)
        # pragma: no mutate end
        return found[0] if found else None

    async def _update_entry(
        self,
        conversation_id: str,
        user_id: str,
        match: Mapping[str, object],
        update: Mapping[str, object] | Sequence[Mapping[str, object]],
        *,
        array_filters: Sequence[Mapping[str, object]] | None = None,
        every_match: bool = False,
    ) -> bool:
        """Update one stored entry (every matching one with every_match); an entry still in the outbox is flushed first.

        Never writes inside the outbox: a miss flushes it and retries once, and an
        every_match update flushes first, since a hit in the collection says nothing
        of a match still in the outbox.
        """
        query = {"user_id": user_id, "conversation_id": conversation_id, **match}
        filters = [dict(f) for f in array_filters] if array_filters is not None else None
        document: dict[str, object] | list[dict[str, object]] = (
            dict(update) if isinstance(update, Mapping) else [dict(stage) for stage in update]
        )
        entries = self._sibling_collection(CONVERSATION_ENTRIES_COLLECTION)
        if every_match:
            await self.flush_outbox(conversation_id, user_id=user_id)
            with store_errors("entry update"):  # pragma: no mutate — error label only
                result = await entries.update_many(query, document, array_filters=filters)
            return result.matched_count > 0
        with store_errors("entry update"):  # pragma: no mutate — error label only
            result = await entries.update_one(query, document, array_filters=filters)
        if result.matched_count:
            return True
        await self.flush_outbox(conversation_id, user_id=user_id)
        with store_errors("entry update"):  # pragma: no mutate — error label only
            retried = await entries.update_one(query, document, array_filters=filters)
        return retried.matched_count > 0

    async def _delete_conversations(self, match: Mapping[str, object], user_id: str) -> list[str]:
        """Delete the user's conversations matching match and their entries, returning their ids."""
        query = {"user_id": user_id, **match}
        ids = await self._distinct("conversation_id", query)
        if not ids:
            return []
        with store_errors("delete"):  # pragma: no mutate — error label only
            # Conversations are uncached (cache_policy None): there is no cache entry to evict.
            await self._raw_collection().delete_many(query)
            await self._sibling_collection(CONVERSATION_ENTRIES_COLLECTION).delete_many(
                {"user_id": user_id, "conversation_id": {"$in": ids}}
            )
        return ids

    def _with_messages(
        self, head: Head, entries: Sequence[ConversationEntry]
    ) -> ConversationDocument:
        doc = self._to_model(head.fields)
        doc.messages = list(entries)
        return doc

    def _listed(self) -> dict[str, object]:
        # Bot conversations live on their platform and a tracked todo's chat on its
        # todo: neither is listed. {todo_id: None} matches a null AND a missing field.
        return {"source": {"$nin": _BOT_SOURCE_VALUES}, "todo_id": None}

    def _active_filter(self, user_id: str) -> dict[str, object]:
        # Background runs stay out of the sidebar unless one holds a live approval
        # (its card is the only way to reach it). Sourceless legacy rows match $ne
        # and stay visible; {starred: null} matches a null AND a missing starred.
        return {
            "user_id": user_id,
            "$and": [
                {
                    "$or": [
                        {"starred": False},
                        {"starred": None},
                    ]
                },
                {
                    "$or": [
                        {"source": {"$ne": ConversationSource.BACKGROUND.value}},
                        {"has_live_approval": True},
                    ]
                },
            ],
            **self._listed(),
        }

    async def _set_fields(
        self, conversation_id: str, user_id: str, fields: dict[str, object] | None = None
    ) -> bool:
        update: dict[str, dict[str, object]] = {"$currentDate": {"updatedAt": {"$type": "date"}}}
        if fields:
            update["$set"] = fields
        matched = await self._apply_raw_update_unfetched(
            {"conversation_id": conversation_id},
            update,
            scope=user_id,
            doc_id=conversation_id,
            extra_filter={"user_id": user_id},
        )
        return matched > 0


conversation_repository = ConversationRepository()


def _backoff() -> float:
    """Return how long a writer that lost the conditional write waits before rereading the head."""
    # Any short wait is correct, so its bounds are not behaviour a test can pin.
    return _JITTER.uniform(0, CONVERSATION_APPEND_JITTER_SECONDS)  # pragma: no mutate


def _todo_binding(todo_id: str) -> dict[str, object]:
    # $type keeps the query inside the binding index's partial filter; a bare equality is not, and scans.
    return {"todo_id": {"$eq": todo_id, "$type": "string"}}


def _todo_chats(user_id: str, todo_ids: Sequence[str]) -> dict[str, object]:
    return {"user_id": user_id, "todo_id": {"$in": list(todo_ids), "$type": "string"}}
