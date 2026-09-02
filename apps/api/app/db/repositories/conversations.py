"""Repository for the ``conversations`` collection (the chat hot path).

Identity is the business key ``conversation_id`` scoped to ``user_id`` — never
Mongo's incidental ``ObjectId`` ``_id``. Documents embed the full ``messages``
array, so most writes are array mutations expressed through the raw-update seam.

Caching is disabled (``cache_policy = None``): a conversation document carries its
entire message history (up to MongoDB's 16MB limit) and is written on every chat
turn, so an entity/query cache would store megabytes and bump its generation
constantly — a pessimisation, not a win. The generation bumps in the write paths
below still run (harmlessly no-op while the policy is None) so enabling a policy
later needs no call-site changes.

``createdAt`` (ISO string, set at insert) and ``updatedAt`` (BSON date, bumped via
``$currentDate``) are the legacy camelCase timestamp pair; the base's snake_case
auto-stamp does not apply, so each mutating method that must advance the sync
clock bumps ``updatedAt`` explicitly.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime

from bson import ObjectId

from app.db.repositories.base import UserScopedRepository
from app.models.chat_models import (
    BOT_CONVERSATION_SOURCES,
    ConversationSource,
    ConversationSyncItem,
    MessageModel,
    SystemPurpose,
    ToolDataEntry,
)
from app.models.conversation_models import (
    ConversationDocument,
    ConversationMessageHit,
    ConversationSearchResults,
    ConversationSummary,
    ConversationUpdate,
    OnboardingProbe,
    _ConversationIdRow,
    _MessageProjectionRow,
    _OnboardingProbeRow,
    _SourceRow,
    _SystemGeneratedRow,
)

_BOT_SOURCE_VALUES: list[str] = [s.value for s in BOT_CONVERSATION_SOURCES]
_SUMMARY_PROJECTION: dict[str, object] = {
    "_id": 0,
    "conversation_id": 1,
    "user_id": 1,
    "description": 1,
    "starred": 1,
    "is_system_generated": 1,
    "is_onboarding_conversation": 1,
    "system_purpose": 1,
    "is_unread": 1,
    "source": 1,
    "createdAt": 1,
    "updatedAt": 1,
}


class ConversationRepository(UserScopedRepository[ConversationDocument, ConversationUpdate]):
    """The ``conversations`` collection repository (the chat hot path).

    Identity is the business key ``conversation_id``; caching is disabled
    (see the module docstring for why)."""

    collection_name = "conversations"
    document_model = ConversationDocument
    update_model = ConversationUpdate
    uses_object_id = True
    identity_field = "conversation_id"
    cache_policy = None

    # ---- conversation-list reads (projected: no messages) ----

    async def list_starred_summaries(self, user_id: str) -> list[ConversationSummary]:
        """The user's starred conversations (projected summaries, newest first)."""
        return await self._aggregate(
            [
                {"$match": {"user_id": user_id, "starred": True, **self._non_bot()}},
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

        Excludes both the onboarding walkthrough conversation and onboarding
        demo conversations (either marker true = not real usage)."""
        return await self._count(
            {
                "user_id": user_id,
                "is_onboarding_conversation": {"$ne": True},
                "is_onboarding_demo": {"$ne": True},
            }
        )

    async def has_activity_since(self, user_id: str, since: datetime) -> bool:
        """Whether the user touched any conversation at or after ``since``.

        The transport-agnostic usage signal. Every chat turn appends messages,
        which stamps ``updatedAt``, whether it arrived from the web app or a bot
        — unlike ``users.last_active_at``, which only a WorkOS web login bumps.
        ``createdAt`` covers conversations created but never appended to.

        The two are compared differently ON PURPOSE, per this module's timestamp
        contract: ``updatedAt`` is a BSON date, ``createdAt`` an ISO string. Mongo
        does not compare across BSON types, so a date ``$gte`` against
        ``createdAt`` matches NOTHING — silently, which is how it read as "this
        user has no activity". ISO-8601 sorts lexicographically in time order, so
        the string form is a real comparison, not a workaround.
        """
        return (
            await self._count(
                {
                    "user_id": user_id,
                    # A workflow execution appends to its system conversation and
                    # stamps updatedAt, so counting those would let a user's own
                    # automation vouch for them as "active" forever — the
                    # circularity that kept the dormancy sweep from ever pausing
                    # an armed workflow. Only human-touched conversations count.
                    "is_system_generated": {"$ne": True},
                    "$or": [
                        {"updatedAt": {"$gte": since}},
                        {"createdAt": {"$gte": since.isoformat()}},
                    ],
                }
            )
            > 0
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
        """Bind an existing conversation to a workflow (source + metadata). Matches
        the legacy write, which does not advance ``updatedAt``."""
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

    async def mark_onboarding_conversation(self, conversation_id: str, *, user_id: str) -> bool:
        """Flag a freshly seeded conversation as the onboarding demo. Matches the
        legacy write, which does not advance ``updatedAt``."""
        matched = await self._apply_raw_update_unfetched(
            {"conversation_id": conversation_id},
            {"$set": {"is_onboarding_conversation": True}},
            scope=user_id,
            doc_id=conversation_id,
            extra_filter={"user_id": user_id},
        )
        return matched > 0

    # ---- message-array writes ----

    async def append_messages(
        self,
        conversation_id: str,
        *,
        user_id: str,
        messages: list[MessageModel],
        max_messages: int | None = None,
    ) -> list[str] | None:
        """Append messages to a conversation, returning their ids (``None`` if the
        conversation does not exist). ``max_messages`` caps stored history via a
        negative ``$slice`` so per-workflow threads stay under the 16MB limit."""
        docs: list[dict[str, object]] = []
        message_ids: list[str] = []
        for message in messages:
            data = {k: v for k, v in message.model_dump().items() if v is not None}
            existing = data.get("message_id")
            message_id = str(existing) if existing is not None else str(ObjectId())
            data["message_id"] = message_id
            message_ids.append(message_id)
            docs.append(data)

        push_spec: dict[str, object] = {"$each": docs}
        if max_messages is not None:
            push_spec["$slice"] = -max_messages

        matched = await self._apply_raw_update_unfetched(
            {"conversation_id": conversation_id},
            {"$push": {"messages": push_spec}, "$currentDate": {"updatedAt": True}},
            scope=user_id,
            doc_id=conversation_id,
            extra_filter={"user_id": user_id},
        )
        return message_ids if matched > 0 else None

    async def set_message_pinned(
        self, conversation_id: str, *, user_id: str, message_id: str, pinned: bool
    ) -> bool:
        """Set one message's pinned flag (positional update into the messages array)."""
        matched = await self._apply_raw_update_unfetched(
            {"conversation_id": conversation_id, "messages.message_id": message_id},
            {"$set": {"messages.$.pinned": pinned}, "$currentDate": {"updatedAt": True}},
            scope=user_id,
            doc_id=conversation_id,
            extra_filter={"user_id": user_id},
        )
        return matched > 0

    async def update_artifact(
        self, conversation_id: str, *, user_id: str, path: str, fields: Mapping[str, object]
    ) -> bool:
        """Patch the registry entry at ``path``; False when no entry exists yet."""
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
        """Append a registry entry, but only when ``path`` is not already present.

        The ``$ne`` guard is what makes concurrent inserts idempotent: of two
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
    ) -> list[dict[str, object]]:
        """The conversation's artifact registry, or an empty list when it has none."""
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
        """Append tool-data entries onto one message. Does not advance ``updatedAt``
        (matches the legacy executor/artifact writes)."""
        matched = await self._apply_raw_update_unfetched(
            {"conversation_id": conversation_id, "messages.message_id": message_id},
            {"$push": {"messages.$.tool_data": {"$each": entries}}},
            scope=user_id,
            doc_id=conversation_id,
            extra_filter={"user_id": user_id},
        )
        return matched > 0

    async def set_message_response(
        self, conversation_id: str, *, user_id: str, message_id: str, response: str
    ) -> bool:
        """Set a message's response text in place. Does not advance ``updatedAt``
        (matches the legacy delivery write)."""
        matched = await self._apply_raw_update_unfetched(
            {"conversation_id": conversation_id, "messages.message_id": message_id},
            {"$set": {"messages.$.response": response}},
            scope=user_id,
            doc_id=conversation_id,
            extra_filter={"user_id": user_id},
        )
        return matched > 0

    async def set_message_tool_data(
        self, conversation_id: str, *, user_id: str, message_id: str, entries: list[ToolDataEntry]
    ) -> bool:
        """Replace a message's tool_data wholesale. Does not advance ``updatedAt``
        (matches the legacy delivery write)."""
        matched = await self._apply_raw_update_unfetched(
            {"conversation_id": conversation_id, "messages.message_id": message_id},
            {"$set": {"messages.$.tool_data": entries}},
            scope=user_id,
            doc_id=conversation_id,
            extra_filter={"user_id": user_id},
        )
        return matched > 0

    async def set_message_approval_status(
        self, conversation_id: str, *, user_id: str, approval_id: str, status: str
    ) -> bool:
        """Settle a persisted approval_request frame's status wherever it lives in
        the messages array. Returns whether the frame was there to settle. Does not
        advance ``updatedAt``."""
        matched = await self._apply_raw_update_unfetched(
            # The approval belongs in the match, not only in the array filters:
            # those pick which element is written but never narrow `matched`, so
            # filtering on the conversation alone reported success for any
            # approval_id the document never held.
            {
                "conversation_id": conversation_id,
                "messages.tool_data.data.approval_id": approval_id,
            },
            {"$set": {"messages.$[msg].tool_data.$[entry].data.status": status}},
            scope=user_id,
            doc_id=conversation_id,
            extra_filter={"user_id": user_id},
            # Filter BOTH levels: `messages.$[]` would require tool_data on every
            # message (user messages have none) and Mongo rejects the whole update.
            array_filters=[
                {"msg.tool_data": {"$elemMatch": {"data.approval_id": approval_id}}},
                {"entry.data.approval_id": approval_id},
            ],
        )
        return matched > 0

    async def set_message_follow_up_actions(
        self, conversation_id: str, *, user_id: str, message_id: str, actions: list[str]
    ) -> bool:
        """Set a message's follow-up actions. Does not advance ``updatedAt`` (matches
        the legacy delivery write)."""
        matched = await self._apply_raw_update_unfetched(
            {"conversation_id": conversation_id, "messages.message_id": message_id},
            {"$set": {"messages.$.follow_up_actions": actions}},
            scope=user_id,
            doc_id=conversation_id,
            extra_filter={"user_id": user_id},
        )
        return matched > 0

    # ---- targeted / projected reads ----

    async def get_message(
        self, conversation_id: str, message_id: str, *, user_id: str
    ) -> MessageModel | None:
        """Read one embedded message by id via a positional projection, without
        loading the whole array."""
        row = await self._find_one_projected(
            {
                "conversation_id": conversation_id,
                "user_id": user_id,
                "messages.message_id": message_id,
            },
            {"messages.$": 1},
            _MessageProjectionRow,
        )
        if row is None or not row.messages:
            return None
        return row.messages[0]

    async def get_source(self, conversation_id: str, *, user_id: str) -> ConversationSource | None:
        """The conversation's source enum, or None when it doesn't exist."""
        row = await self._find_one_projected(
            {"conversation_id": conversation_id, "user_id": user_id},
            {"_id": 0, "source": 1},
            _SourceRow,
        )
        return None if row is None else ConversationSource.coerce(row.source)

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

        Narrower than ``is_system_generated``: email and reminder runs are
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
        """The conversation id owning a message of ``message_type`` with this id."""
        row = await self._find_one_projected(
            {
                "user_id": user_id,
                "messages": {"$elemMatch": {"message_id": message_id, "type": message_type}},
            },
            {"_id": 0, "conversation_id": 1},
            _ConversationIdRow,
        )
        return None if row is None else row.conversation_id

    async def get_onboarding_probe(self, conversation_id: str) -> OnboardingProbe | None:
        """The onboarding-demo flag and message count for the system-prompt gate."""
        row = await self._find_one_projected(
            {"conversation_id": conversation_id},
            {"is_onboarding_conversation": 1, "messages": 1},
            _OnboardingProbeRow,
        )
        if row is None:
            return None
        return OnboardingProbe(
            is_onboarding_conversation=row.is_onboarding_conversation,
            message_count=len(row.messages),
        )

    async def find_workflow_conversation(
        self, user_id: str, workflow_id: str
    ) -> ConversationDocument | None:
        """The system-generated conversation bound to a workflow execution."""
        return await self._find_one(
            {
                "user_id": user_id,
                "is_system_generated": True,
                "system_purpose": SystemPurpose.WORKFLOW_EXECUTION.value,
                "metadata.workflow_id": workflow_id,
            }
        )

    async def recent_for_user(self, user_id: str, *, limit: int) -> list[ConversationDocument]:
        """The user's most recent conversations."""
        return await self._find({"user_id": user_id}, sort=[("createdAt", -1)], limit=limit)

    async def find_updated_since(
        self, user_id: str, items: list[ConversationSyncItem]
    ) -> list[ConversationDocument]:
        """Batch-fetch the named conversations whose ``updatedAt`` is newer than the
        client's last-seen timestamp (or which have none) — the client-sync read.
        A missing/unparseable timestamp includes the conversation unconditionally."""
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
        return await self._find({"$or": conditions})

    # ---- search / pinned aggregations ----

    async def list_pinned_messages(self, user_id: str) -> list[ConversationMessageHit]:
        """Every pinned message across the user's conversations."""
        return await self._aggregate(
            [
                {"$match": {"user_id": user_id}},
                {"$unwind": "$messages"},
                {"$match": {"messages.pinned": True}},
                {"$project": {"_id": 0, "conversation_id": 1, "message": "$messages"}},
            ],
            ConversationMessageHit,
        )

    async def search(self, user_id: str, *, pattern: str) -> ConversationSearchResults:
        """Regex search across message responses and conversation descriptions.
        ``pattern`` is treated as a literal — the caller passes an escaped query."""
        rows = await self._aggregate(
            [
                {"$match": {"user_id": user_id}},
                {
                    "$facet": {
                        "messages": [
                            {"$unwind": "$messages"},
                            {"$match": {"messages.response": {"$regex": pattern, "$options": "i"}}},
                            {"$project": {"_id": 0, "conversation_id": 1, "message": "$messages"}},
                        ],
                        "conversations": [
                            {"$match": {"description": {"$regex": pattern, "$options": "i"}}},
                            {"$project": {"_id": 0, "conversation_id": 1, "description": 1}},
                        ],
                    }
                },
            ],
            ConversationSearchResults,
        )
        return rows[0] if rows else ConversationSearchResults()

    # ---- bulk deletes / maintenance sweeps ----

    async def delete_all_for_user(self, user_id: str) -> list[str]:
        """Delete every conversation for a user, returning the deleted ids so the
        caller can clean up their (non-user-scoped) checkpoint threads."""
        ids = await self._distinct("conversation_id", {"user_id": user_id})
        await self._delete_many({"user_id": user_id}, scope=user_id)
        return ids

    async def delete_onboarding_demos(self, user_id: str) -> int:
        """Delete the user's onboarding-demo conversations."""
        return await self._delete_many(
            {"user_id": user_id, "is_onboarding_demo": True}, scope=user_id
        )

    async def all_conversation_ids(self) -> list[str]:
        """Every live conversation id across all users — the checkpoint orphan
        sweep's source of truth. Intentionally unscoped (a maintenance sweep)."""
        return await self._distinct("conversation_id")

    async def active_user_ids_since(self, cutoff: datetime) -> list[str]:
        """User ids with a conversation updated since ``cutoff`` — the workspace
        sync sweep's active-user set. Intentionally unscoped (a maintenance sweep)."""
        return await self._distinct("user_id", {"updatedAt": {"$gte": cutoff}})

    # ---- internal helpers ----

    def _non_bot(self) -> dict[str, object]:
        return {"source": {"$nin": _BOT_SOURCE_VALUES}}

    def _active_filter(self, user_id: str) -> dict[str, object]:
        return {
            "user_id": user_id,
            "$or": [{"starred": {"$exists": False}}, {"starred": False}],
            **self._non_bot(),
        }

    async def _set_fields(
        self, conversation_id: str, user_id: str, fields: dict[str, object]
    ) -> bool:
        matched = await self._apply_raw_update_unfetched(
            {"conversation_id": conversation_id},
            {"$set": fields, "$currentDate": {"updatedAt": True}},
            scope=user_id,
            doc_id=conversation_id,
            extra_filter={"user_id": user_id},
        )
        return matched > 0


conversation_repository = ConversationRepository()
