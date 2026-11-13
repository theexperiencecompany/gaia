"""Repository for a conversation's head (the conversations collection) and its entry log (conversation_entries).

Identity is the business key conversation_id scoped to user_id, never Mongo's
ObjectId _id. The log's entries are one document each, ordered by a seq that
only one conditional head write allocates. A committed entry sits in the
head's outbox until a flush copies it into conversation_entries; every read
unions the two through _union_for, head first. Messages are the log's
entries projected (conversation_history.project), never stored as such.

Caching is disabled (cache_policy = None). createdAt (ISO string) and
updatedAt (BSON date) are a legacy camelCase pair; each mutating method that
must advance the sync clock bumps updatedAt explicitly.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
import random
from typing import ClassVar

from pymongo.errors import DuplicateKeyError

from app.constants.chat import (
    CONVERSATION_APPEND_JITTER_SECONDS,
    CONVERSATION_ENTRIES_COLLECTION,
    CONVERSATION_READ_LIMIT,
)
from app.db.repositories.base import UserScopedRepository
from app.db.repositories.cache import CachePolicy
from app.db.repositories.conversation_entries import (
    AWAITING_APPROVAL,
    AWAITING_APPROVAL_STAGE,
    DROP_EMBEDDED_STAGE,
    LOG_HEAD_FIELD,
    OUTBOX_FIELD,
    REVISION_FIELD,
    STATE_FIELD,
    EntryWindow,
    Head,
    StoredRow,
    at_its_seq,
    committed_at,
    head_fields,
    head_from_raw,
    head_with_existing,
    is_same_entry,
    logged_of,
    newest,
    outbox_entries_matching,
    store_errors,
    stored_entries_matching,
    stored_row,
)
from app.db.repositories.conversation_history import (
    MESSAGE_KINDS,
    PINNABLE_KINDS,
    RELATED_KINDS,
    TEXT_KINDS,
    needed_beside,
    project,
)
from app.models.artifact_models import ArtifactRegistryEntry
from app.models.chat_models import (
    BOT_CONVERSATION_SOURCES,
    ConversationSource,
    ConversationSyncItem,
    SystemPurpose,
)
from app.models.conversation_log_models import EntryKind, LoggedEntry
from app.models.conversation_models import (
    ConversationDescriptionHit,
    ConversationDocument,
    ConversationEntry,
    ConversationHead,
    ConversationMessageHit,
    ConversationMessagesPage,
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
    ConversationAlreadyExistsError,
    ConversationIdTakenError,
    ConversationStoreError,
)
from shared.py.wide_events import spawn_logged_task

_JITTER = random.SystemRandom()
#: A quote, a settle's quote, an approval, its work: the longest chain a message reads beside it.
_BESIDE_PASSES = 4
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
    "awaiting_approval": AWAITING_APPROVAL,
    "createdAt": 1,
    "updatedAt": 1,
}


@dataclass(frozen=True)
class _History:
    """A head with the messages a read projected from it, and whether older ones exist."""

    head: Head
    messages: list[ConversationEntry]
    older: bool


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
            user_id,
            {"kind": EntryKind.USER_MESSAGE.value},
            excluding={"is_system_generated": True},
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

    async def mark_background(self, conversation_id: str, *, user_id: str) -> bool:
        """Stamp a background run's conversation with source BACKGROUND, only when it has no source.

        Never overwrites a real channel. False when the conversation does not exist yet.
        """
        return (
            await self._apply_raw_update_unfetched(
                {"conversation_id": conversation_id, "source": {"$exists": False}},
                {"$set": {"source": ConversationSource.BACKGROUND.value}},
                scope=user_id,
                doc_id=conversation_id,
                extra_filter={"user_id": user_id},
            )
            > 0
        )

    # ---- the entry log: append, flush, read ----

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
        once = {seq: entry for seq, entry in outbox.items() if entry.revision is None}
        # pragma: no mutate start — $unset ignores the value
        drained = {f"{OUTBOX_FIELD}.{seq}": "" for seq in once}
        # pragma: no mutate end
        with store_errors("flush"):  # pragma: no mutate — error label only
            await self._insert_entries(list(once.values()))
            for seq, entry in outbox.items():
                if entry.revision is not None:
                    await self._place_revision(entry)
                    # An amend staged after this read keeps its newer revision for the next flush.
                    await self._raw_collection().update_one(
                        {**head, f"{OUTBOX_FIELD}.{seq}.{REVISION_FIELD}": entry.revision},
                        {"$unset": {f"{OUTBOX_FIELD}.{seq}": ""}},  # pragma: no mutate
                    )
            if drained:
                unset = await self._raw_collection().update_one(head, {"$unset": drained})
                gone = not unset.matched_count
            else:
                gone = not await self._count(head)
            if gone:
                # The conversation was deleted while this flush ran: take back what it inserted.
                await self._sibling_collection(CONVERSATION_ENTRIES_COLLECTION).delete_many(
                    {
                        "user_id": user_id,
                        "conversation_id": conversation_id,
                        "seq": {"$in": list(outbox)},
                    }
                )

    async def list_artifacts(
        self, conversation_id: str, *, user_id: str
    ) -> list[ArtifactRegistryEntry]:
        """Return the conversation's artifact registry, or an empty list when it has none."""
        document = await self._find_one({"conversation_id": conversation_id, "user_id": user_id})
        return list(document.artifacts) if document else []

    # ---- targeted / projected reads ----

    async def get(self, doc_id: str, *, user_id: str) -> ConversationDocument | None:
        """Read the conversation with its newest CONVERSATION_READ_LIMIT messages, oldest first."""
        heads = await self._read_heads({"conversation_id": doc_id, "user_id": user_id})
        if not heads:
            return None
        [history] = await self._histories(heads, EntryWindow(), limit=CONVERSATION_READ_LIMIT)
        return self._with_history(history)

    async def read_messages_before(
        self, conversation_id: str, *, user_id: str, before_seq: int, limit: int
    ) -> ConversationMessagesPage | None:
        """Read the newest limit messages before before_seq, oldest first; None for a missing conversation."""
        heads = await self._read_heads({"conversation_id": conversation_id, "user_id": user_id})
        if not heads:
            return None
        window = EntryWindow(before_seq=before_seq)
        [history] = await self._histories(heads, window, limit=limit)
        return ConversationMessagesPage(messages=history.messages, has_more=history.older)

    async def get_message(
        self, conversation_id: str, message_id: str, *, user_id: str
    ) -> ConversationEntry | None:
        """Read one message by its message id (a reply's is its reply id), without the rest of the conversation."""
        heads = await self._read_heads({"conversation_id": conversation_id, "user_id": user_id})
        if not heads:
            return None
        window = EntryWindow(ids=[message_id], reply_ids=[message_id])
        [history] = await self._histories(heads, window)
        return history.messages[0] if history.messages else None

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

    async def find_owner_of_message(self, user_id: str, reply_id: str) -> str | None:
        """Return the conversation id owning GAIA's reply with this id."""
        found = await self._first_entry(
            user_id, {"kind": EntryKind.REPLY.value, "reply_id": reply_id}
        )
        return None if found is None else found.conversation_id

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
        """Return the user's most recent conversations, each with its newest messages."""
        heads = await self._read_heads({"user_id": user_id}, sort={"createdAt": -1}, limit=limit)
        window = EntryWindow()
        return [
            self._with_history(history)
            for history in await self._histories(heads, window, limit=CONVERSATION_READ_LIMIT)
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
        """Insert the conversation's head at an empty log; raises ValueError if doc carries messages.

        conversation_id is unique across every user: an id this user already holds raises
        ConversationAlreadyExistsError (a concurrent first send lost the race), one another
        user holds raises ConversationIdTakenError.
        """
        if doc.messages:
            raise ValueError(
                "create() writes only the head; messages are log entries appended to its log"
            )
        head = doc.model_dump(exclude={"id", "messages", "has_older"}, exclude_none=True)
        head[LOG_HEAD_FIELD] = 0
        try:
            await self._raw_collection().insert_one(head)
        except DuplicateKeyError as e:
            await self._raise_held(doc, e)
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
        except (DuplicateKeyError, ConversationAlreadyExistsError):
            return False
        return True

    async def _raise_held(self, doc: ConversationDocument, error: DuplicateKeyError) -> None:
        """Say who already holds doc's conversation id; re-raise when another unique key refused it."""
        with store_errors("create"):  # pragma: no mutate — error label only
            holder = await self._raw_collection().find_one(
                {"conversation_id": doc.conversation_id}, {"_id": 0, "user_id": 1}
            )
        meta: dict[str, object] = {"conversation_id": doc.conversation_id}
        if holder is None:
            raise error
        if holder["user_id"] != doc.user_id:
            raise ConversationIdTakenError(
                message=f"conversation id {doc.conversation_id} belongs to another user",
                meta=meta,
            ) from error
        raise ConversationAlreadyExistsError(
            message=f"conversation {doc.conversation_id} already exists", meta=meta
        ) from error

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
        """Batch-fetch conversations updated since each item's last-seen timestamp, with their newest messages.

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
        window = EntryWindow()
        return [
            self._with_history(history)
            for history in await self._histories(heads, window, limit=CONVERSATION_READ_LIMIT)
        ]

    # ---- search / pinned ----

    async def list_pinned_messages(self, user_id: str) -> list[ConversationMessageHit]:
        """Every pinned message across the user's conversations."""
        pinned = {"pinned": True, "kind": {"$in": sorted(PINNABLE_KINDS)}}
        return await self._hits(user_id, await self._find_entries(user_id, pinned))

    async def search(self, user_id: str, *, pattern: str) -> ConversationSearchResults:
        """Regex search across message responses and conversation descriptions.

        pattern is treated as a literal — the caller passes an escaped query.
        """
        regex = {"$regex": pattern, "$options": "i"}
        # A tracked todo's chat is reached from its todo, never from search.
        todo_chat = {"todo_id": {"$type": "string"}}
        texts = {"text": regex, "kind": {"$in": sorted(TEXT_KINDS)}}
        found = await self._find_entries(user_id, texts, excluding=todo_chat)
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
            messages=await self._hits(user_id, found), conversations=described
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
        """Read heads without their embedded arrays."""
        pipeline: list[Mapping[str, object]] = [{"$match": dict(match)}]
        if sort:
            pipeline.append({"$sort": dict(sort)})
        if limit:
            pipeline.append({"$limit": limit})
        pipeline += [AWAITING_APPROVAL_STAGE, DROP_EMBEDDED_STAGE]
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

    async def _place_revision(self, entry: StoredEntry) -> None:
        """Write an amendable entry's document, unless the collection already holds this revision or a newer one."""
        collection = self._sibling_collection(CONVERSATION_ENTRIES_COLLECTION)
        try:
            await collection.insert_one(entry.document())
        except DuplicateKeyError as exc:
            # Only this entry's own older revision is replaced: another entry at its seq is a conflict.
            older = {**at_its_seq(entry), "id": entry.id, REVISION_FIELD: {"$lt": entry.revision}}
            if (await collection.replace_one(older, entry.document())).matched_count:
                return
            # The projection only trims the read: the key model ignores every other field.
            stored = await collection.find_one(
                at_its_seq(entry), _ENTRY_KEY_FIELDS
            )  # pragma: no mutate
            if not is_same_entry(stored, entry):
                raise ConversationStoreError(
                    message="an outbox entry conflicts with a stored entry", why=str(exc)
                ) from exc

    async def _histories(
        self, heads: Sequence[Head], window: EntryWindow, *, limit: int | None = None
    ) -> list[_History]:
        """Each head's messages in window: the newest limit of them, and whether older ones exist."""
        if limit is None:
            windows = await self._union_for(heads, replace(window, kinds=MESSAGE_KINDS))
            return list(
                await asyncio.gather(
                    *(self._history(head, entries, older=False) for head, entries in windows)
                )
            )
        return list(await asyncio.gather(*(self._newest(head, window, limit) for head in heads)))

    async def _newest(self, head: Head, window: EntryWindow, limit: int) -> _History:
        """Read back one chunk at a time until limit messages show: finished work a reply took shows none."""
        shown: list[ConversationEntry] = []
        before = window.before_seq
        while True:
            chunk = replace(window, kinds=MESSAGE_KINDS, before_seq=before, limit=limit + 1)
            [(_, entries)] = await self._union_for([head], chunk)
            more = len(entries) > limit
            page = entries[-limit:] if more else entries
            shown = (await self._history(head, page, older=False)).messages + shown
            if len(shown) > limit or not more:
                return _History(head, shown[-limit:], len(shown) > limit)
            before = page[0].seq

    async def _history(
        self, head: Head, entries: Sequence[StoredEntry], *, older: bool
    ) -> _History:
        logged = [logged_of(entry) for entry in entries]
        return _History(head, project(logged, await self._related(head, logged)), older)

    async def _related(self, head: Head, window: Sequence[LoggedEntry]) -> list[LoggedEntry]:
        """Read what the window's messages need from outside it: settles, quotes, approvals, answering replies."""

        async def lookup(ids: Sequence[str], reply_ids: Sequence[str]) -> list[LoggedEntry]:
            found = EntryWindow(ids=ids, reply_ids=reply_ids, kinds=RELATED_KINDS)
            [(_, entries)] = await self._union_for([head], found)
            return [logged_of(entry) for entry in entries]

        return await _read_beside(window, lookup)

    async def _hits(self, user_id: str, rows: Sequence[StoredRow]) -> list[ConversationMessageHit]:
        """Project cross-conversation rows one message apiece, with their settles and quotes."""
        beside: list[StoredRow] = []

        async def lookup(ids: Sequence[str], reply_ids: Sequence[str]) -> list[LoggedEntry]:
            found = await self._related_rows(user_id, ids, reply_ids)
            beside.extend(found)
            return [row.logged for row in found]

        await _read_beside([row.logged for row in rows], lookup)
        related: dict[str, list[LoggedEntry]] = {}
        for row in [*rows, *beside]:
            related.setdefault(row.conversation_id, []).append(row.logged)
        return [
            ConversationMessageHit(conversation_id=row.conversation_id, message=message)
            for row in rows
            for message in project([row.logged], related.get(row.conversation_id, []))
        ]

    async def _related_rows(
        self, user_id: str, ids: Sequence[str], reply_ids: Sequence[str]
    ) -> list[StoredRow]:
        named = [{"id": {"$in": list(ids)}}, {"reply_id": {"$in": list(reply_ids)}}]
        return await self._find_entries(
            user_id, {"kind": {"$in": sorted(RELATED_KINDS)}, "$or": named}
        )

    async def _union_for(
        self, heads: Sequence[Head], window: EntryWindow
    ) -> list[tuple[Head, list[StoredEntry]]]:
        """Union each head's outbox with its collection entries, up to the log_head the head read saw."""
        if not heads:
            return []
        # Log entries share the seq space, so only a read per head can bound its newest limit messages.
        batches = [[head] for head in heads] if window.limit else [list(heads)]
        reads = await asyncio.gather(*(self._stored_rows(batch, window) for batch in batches))
        rows = [row for read in reads for row in read]
        stored: dict[tuple[str, str], dict[int, StoredEntry]] = {}
        for entry in map(StoredEntry.model_validate, rows):
            committed_at(entry)
            stored.setdefault((entry.user_id, entry.conversation_id), {})[entry.seq] = entry
        result: list[tuple[Head, list[StoredEntry]]] = []
        for head in heads:
            union = dict(stored.get((head.user_id, head.conversation_id), {}))
            for seq, entry in head.outbox.items():
                if window.admits(entry, head.log_head):
                    union[seq] = newest(union.get(seq), entry)
            result.append((head, window.take(union)))
        return result

    async def _stored_rows(
        self, heads: Sequence[Head], window: EntryWindow
    ) -> list[dict[str, object]]:
        """Read the collection's entries in window for heads, newest first."""
        clauses = [
            {
                "user_id": head.user_id,
                "conversation_id": head.conversation_id,
                "seq": window.seq_range(head.log_head),
                **window.clauses(),
            }
            for head in heads
        ]
        cursor = (
            self._sibling_collection(CONVERSATION_ENTRIES_COLLECTION)
            .find({"$or": clauses})
            .sort(_NEWEST_FIRST)
        )
        # pragma: no mutate start — the limit only spares reading rows take() drops
        if window.limit:
            cursor = cursor.limit(window.limit)
        # pragma: no mutate end
        with store_errors("entry read"):  # pragma: no mutate — error label only
            return await cursor.to_list(length=None)

    async def _find_entries(
        self,
        user_id: str,
        match: Mapping[str, object],
        *,
        excluding: Mapping[str, object] | None = None,
        limit: int = 0,
    ) -> list[StoredRow]:
        """Log entries matching match across the user's conversations, outboxes first, then the collection.

        excluding names the heads whose entries never count; limit bounds the collection
        read for callers that need only whether one exists. Only entries under a live head
        count.
        """
        with store_errors("entry search"):  # pragma: no mutate — error label only
            pending = await (
                self._raw_collection()
                .aggregate(outbox_entries_matching(user_id, match, excluding=excluding))
                .to_list(length=None)
            )
            # An entry still in an outbox is newer than any stored copy of it, matching or not.
            revised = await (
                self._raw_collection()
                .aggregate(
                    [
                        *outbox_entries_matching(user_id, {}, excluding=excluding),
                        {"$project": {"_id": 0, "conversation_id": 1, "seq": 1}},
                    ]
                )
                .to_list(length=None)
            )
            stored = stored_entries_matching(
                user_id,
                match,
                excluding=excluding,
                heads_collection=self._raw_collection().name,
                limit=limit,
            )
            rows = await (
                self._sibling_collection(CONVERSATION_ENTRIES_COLLECTION)
                .aggregate(stored)
                .to_list(length=None)
            )
        staged = {(str(row["conversation_id"]), int(str(row["seq"]))) for row in revised}
        found: dict[tuple[str, int], StoredRow] = {}
        for raw in pending:
            row = stored_row(raw)
            found[(row.conversation_id, row.logged.seq)] = row
        for raw in rows:
            key = (str(raw["conversation_id"]), int(str(raw["seq"])))
            if key not in found and key not in staged:
                found[key] = stored_row(raw)
        return sorted(found.values(), key=lambda row: (row.logged.at, row.logged.seq))

    async def _first_entry(
        self,
        user_id: str,
        match: Mapping[str, object],
        *,
        excluding: Mapping[str, object] | None = None,
    ) -> StoredRow | None:
        """Return one log entry matching match across the user's conversations, or None."""
        # pragma: no mutate start — limit only bounds a read whose callers ask whether one exists
        found = await self._find_entries(user_id, match, excluding=excluding, limit=1)
        # pragma: no mutate end
        return found[0] if found else None

    async def _delete_conversations(self, match: Mapping[str, object], user_id: str) -> list[str]:
        """Delete the user's conversations matching match and their entries, returning their ids."""
        query = {"user_id": user_id, **match}
        ids = await self._distinct("conversation_id", query)
        if not ids:
            return []
        with store_errors("delete"):  # pragma: no mutate — error label only
            # Entries first: a delete that dies between the two leaves the head, which the user can
            # delete again, never entries a later head under the same id would inherit.
            await self._sibling_collection(CONVERSATION_ENTRIES_COLLECTION).delete_many(
                {"user_id": user_id, "conversation_id": {"$in": ids}}
            )
            # Conversations are uncached (cache_policy None): there is no cache entry to evict.
            await self._raw_collection().delete_many(query)
        return ids

    def _with_history(self, history: _History) -> ConversationDocument:
        doc = self._to_model(history.head.fields)
        doc.messages = history.messages
        doc.has_older = history.older
        return doc

    def _listed(self) -> dict[str, object]:
        # Bot conversations live on their platform and a tracked todo's chat on its
        # todo: neither is listed. {todo_id: None} matches a null AND a missing field.
        return {"source": {"$nin": _BOT_SOURCE_VALUES}, "todo_id": None}

    def _active_filter(self, user_id: str) -> dict[str, object]:
        # Background runs stay out of the sidebar unless their work awaits the user's approval
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
                        {f"{STATE_FIELD}.work.pending_approvals.0": {"$exists": True}},
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


async def _read_beside(
    window: Sequence[LoggedEntry],
    lookup: Callable[[Sequence[str], Sequence[str]], Awaitable[list[LoggedEntry]]],
) -> list[LoggedEntry]:
    """Look up what the window needs, pass by pass, as each answer names more; never the same id twice."""
    related: list[LoggedEntry] = []
    asked: set[str] = set()
    for _ in range(_BESIDE_PASSES):
        ids, reply_ids = (
            [name for name in names if name not in asked]
            for names in needed_beside(window, related)
        )
        if not ids and not reply_ids:
            break
        asked |= {*ids, *reply_ids}
        related += await lookup(ids, reply_ids)
    return related


def _backoff() -> float:
    """Return how long a writer that lost the conditional write waits before rereading the head."""
    # Any short wait is correct, so its bounds are not behaviour a test can pin.
    return _JITTER.uniform(0, CONVERSATION_APPEND_JITTER_SECONDS)  # pragma: no mutate


def _todo_binding(todo_id: str) -> dict[str, object]:
    # $type keeps the query inside the binding index's partial filter; a bare equality is not, and scans.
    return {"todo_id": {"$eq": todo_id, "$type": "string"}}


def _todo_chats(user_id: str, todo_ids: Sequence[str]) -> dict[str, object]:
    return {"user_id": user_id, "todo_id": {"$in": list(todo_ids), "$type": "string"}}
