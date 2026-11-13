"""Rewrites each conversation's old message shape as conversation log entries, and verifies it.

Sources: the head's embedded messages array (production's shape) and message-shaped entries
an earlier build of this stack copied into conversation_entries. A user message becomes an
imported UserMessage, a bot message an imported Reply, each at its position; a bot message's
ReplySettled is appended at the tail with a fresh seq, so no seq is ever renumbered. An
emoji_ack folds into a chat-model reaction on the user message it answered. Re-runs merge by
entry id and set only the fields whose source changed; the head write is conditional on the
log_head and the array's whole-array fingerprint as read, so a racing write reports RACED.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
import hashlib
import json

from bson import ObjectId
from pydantic import ValidationError

from app.constants.chat import (
    BOT_MESSAGE_TYPE,
    CONVERSATION_ENTRIES_COLLECTION,
    USER_MESSAGE_TYPE,
    ConversationSource,
)
from app.db.repositories.conversation_entries import (
    LOG_HEAD_FIELD,
    MIGRATED_FINGERPRINT_FIELD,
    MIGRATION_FIELDS_FIELD,
    STATE_FIELD,
    EntryWindow,
    log_document,
    logged_of,
    store_errors,
    unmigrated,
)
from app.db.repositories.conversation_history import PINNABLE_KINDS, TEXT_KINDS
from app.db.repositories.conversation_log import EMPTY_LOG_STATE
from app.db.repositories.conversations import ConversationRepository
from app.models.chat_models import ConversationSyncItem, ReactionBy
from app.models.conversation_log_models import (
    ConversationState,
    Entry,
    FailureReason,
    LoggedEntry,
    Reaction,
    Reply,
    ReplyOutcome,
    ReplySettled,
    Transition,
    UserMessage,
)
from app.models.conversation_models import (
    ConversationEntry,
    EmbeddedHead,
    HeadRefRow,
    LegacyMessage,
    MessageShape,
    NotKeptFields,
    StoredEntry,
    _ConversationIdRow,
)
from app.services.conversation.reducer import reduce

#: A server-side hash of the whole embedded array: any append, trim or in-place edit changes it.
EMBEDDED_FINGERPRINT: dict[str, object] = {"$toHashedIndexKey": {"$ifNull": ["$messages", []]}}
#: Heads whose embedded array the log does not match: never migrated, or written since.
UNMIGRATED_HEADS: dict[str, object] = {
    "messages.0": {"$exists": True},
    "$or": [
        {MIGRATED_FINGERPRINT_FIELD: {"$exists": False}},
        {"$expr": {"$ne": [EMBEDDED_FINGERPRINT, f"${MIGRATED_FINGERPRINT_FIELD}"]}},
    ],
}
#: The startup check's indexed form: an embedded array no pass ever marked.
NEVER_MIGRATED_HEADS: dict[str, object] = {
    "messages.0": {"$exists": True},
    MIGRATED_FINGERPRINT_FIELD: {"$exists": False},
}
#: Message-shaped entries carry the old type field (user or bot); no log entry has one.
MESSAGE_SHAPED: dict[str, object] = {"type": {"$exists": True}}
_ACK_KIND = "emoji_ack"
#: The old message fields the log keeps nowhere; a pass counts the messages that carry one.
NOT_KEPT_FIELDS = tuple(NotKeptFields.model_fields)
#: What verify compares of each message a client reads.
_SHOWN_FIELDS = frozenset(
    {
        "type",
        "response",
        "message_id",
        "date",
        "fileIds",
        "fileData",
        "selectedTool",
        "toolCategory",
        "selectedWorkflow",
        "selectedCalendarEvent",
        "todo_run_wake",
        "tool_data",
        "follow_up_actions",
        "image_data",
        "replyToMessage",
        "error",
        "stopped",
        "in_progress",
        "pinned",
        "reaction",
        "platform_message_id",
        "first_contact",
    }
)
_HEAD_REF_STAGE: dict[str, object] = {
    "$project": {"_id": 0, "head_id": {"$toString": "$_id"}, "conversation_id": 1, "user_id": 1}
}
_BY_HEAD_ID: dict[str, object] = {"$sort": {"_id": 1}}
_ID_FIELD = "message_id"
_FOUND = "_found"
_UNSET_EMBEDDED: dict[str, object] = {"messages": "", MIGRATED_FINGERPRINT_FIELD: ""}


class MigrationAction(StrEnum):
    """What a pass did, or would do, to one conversation."""

    COPIED = "copied"
    MERGED = "merged"
    UNCHANGED = "unchanged"
    RACED = "raced"
    REFUSED = "refused"


@dataclass
class MigrationOutcome:
    """One conversation's result: the action and the counts behind it."""

    conversation_id: str
    action: MigrationAction
    written: int = 0
    rewritten: int = 0
    identified: int = 0
    folded: int = 0
    not_kept: int = 0
    reason: str = ""


@dataclass
class VerifyReport:
    """One conversation's verify result; fingerprint is the embedded array's, which a drop requires unchanged."""

    conversation_id: str
    messages: int = 0
    fingerprint: int | None = None
    mismatches: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.mismatches


@dataclass(frozen=True)
class HeadRef:
    """The head a pass works on: its _id (the resume cursor) and identity."""

    head_id: str
    conversation_id: str
    user_id: str


@dataclass(frozen=True)
class _Element:
    """One old message as the source holds it; seq is set when a message-shaped entry already sits there."""

    fields: dict[str, object]
    seq: int | None = None

    @property
    def id(self) -> str:
        return str(self.fields[_ID_FIELD])

    @property
    def is_user(self) -> bool:
        return MessageShape.model_validate(self.fields).type == USER_MESSAGE_TYPE


@dataclass(frozen=True)
class _Planned:
    """A log entry the source yields: where it sits (None appends it) and when it was written (None keeps the stored time)."""

    entry: Entry
    seq: int | None
    at: datetime | None
    settles_after: str | None = None


@dataclass
class _Plan:
    """A conversation's writes: entries to insert, rewrite in place or update, and the head after them."""

    inserts: list[dict[str, object]] = field(default_factory=list)
    replaces: list[tuple[int, dict[str, object]]] = field(default_factory=list)
    updates: list[tuple[str, dict[str, object]]] = field(default_factory=list)
    log: dict[int, LoggedEntry] = field(default_factory=dict)
    folded: int = 0
    not_kept: int = 0
    state: ConversationState = EMPTY_LOG_STATE

    @property
    def writes(self) -> int:
        return len(self.inserts) + len(self.replaces) + len(self.updates)

    def add(
        self, ref: HeadRef, logged: LoggedEntry, prior: StoredEntry | None, *, in_place: int | None
    ) -> None:
        """Place one entry: update what a pass wrote before, rewrite a message-shaped entry, or insert."""
        # Mongo keeps milliseconds: hash what a later read returns.
        at = logged.at.replace(microsecond=logged.at.microsecond // 1000 * 1000)
        logged = logged.model_copy(update={"at": at})
        self.log[logged.seq] = logged
        document = log_document(ref.conversation_id, ref.user_id, logged)
        document = {**document, MIGRATION_FIELDS_FIELD: field_hashes(document)}
        if prior is not None:
            if update := _changed(prior, document):
                self.updates.append((logged.entry.id, update))
        elif in_place is not None:
            self.replaces.append((logged.seq, document))
        else:
            self.inserts.append(document)


class MigrationRefused(Exception):
    """The source cannot become a valid log: an element that does not parse, or a fold that is not idle."""


def field_hashes(document: Mapping[str, object]) -> dict[str, str]:
    """Hash each field of an entry document canonically, so a later pass can tell which changed."""
    return {
        key: hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()
        for key, value in document.items()
        if key != MIGRATION_FIELDS_FIELD
    }


def minted_ids(elements: Sequence[LegacyMessage]) -> list[str | None]:
    """Return a fresh id for each element with none or one an earlier element holds, None for the rest."""
    seen: set[str] = set()
    minted: list[str | None] = []
    for element in elements:
        if element.message_id and element.message_id not in seen:
            seen.add(element.message_id)
            minted.append(None)
        else:
            minted.append(str(ObjectId()))
    return minted


def entry_at(date: object) -> datetime | None:
    """Return when an old message was written: its ISO date (a naive one read as UTC); None when it has none."""
    if not isinstance(date, str):
        return None
    try:
        parsed = datetime.fromisoformat(date)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _ack_target(element: _Element, users: set[str]) -> tuple[str, str] | None:
    """Return (target id, emoji) of an emoji_ack whose emoji and target both exist."""
    shape = MessageShape.model_validate(element.fields)
    if shape.kind != _ACK_KIND:
        return None
    emoji = (shape.response or "").strip()
    target = shape.reacts_to_message_id
    return (target, emoji) if emoji and target in users else None


def _settle_outcome(message: ConversationEntry) -> tuple[ReplyOutcome, FailureReason | None]:
    if message.error:
        known = {reason.value for reason in FailureReason}
        reason = message.error if message.error in known else FailureReason.MODEL_ERROR
        return ReplyOutcome.FAILED, FailureReason(reason)
    if message.stopped:
        return ReplyOutcome.STOPPED, None
    return ReplyOutcome.ANSWERED, None


def _planned(
    elements: Sequence[_Element], surface: ConversationSource
) -> tuple[list[_Planned], int]:
    """Turn the source into the log entries it holds, in order; return them and how many acks folded."""
    users = {element.id for element in elements if element.is_user}
    reactions: dict[str, str] = {}
    for element in elements:
        if (folded := _ack_target(element, users)) is not None:
            reactions[folded[0]] = folded[1]
    planned: list[_Planned] = []
    last_user: str | None = None
    for element in elements:
        try:
            planned += _element_entries(element, surface, users, reactions, last_user)
        except ValidationError as exc:
            raise MigrationRefused(f"message {element.id} cannot be a log entry: {exc}") from exc
        last_user = element.id if element.is_user else last_user
    return planned, len(reactions)


def _element_entries(
    element: _Element,
    surface: ConversationSource,
    users: set[str],
    reactions: Mapping[str, str],
    last_user: str | None,
) -> list[_Planned]:
    """Return the entries one old message becomes: none for a folded ack, a reply's settle after it."""
    message = ConversationEntry.model_validate({**element.fields, "seq": 0})
    at = entry_at(MessageShape.model_validate(element.fields).date)
    if element.is_user:
        return [_Planned(_user_message(message, surface, reactions), element.seq, at)]
    folded_ack = _ack_target(element, users) is not None
    if folded_ack and not message.tool_data:
        return []
    reply = _reply(message, users, blank=folded_ack)
    if message.in_progress:
        return [_Planned(reply, element.seq, at)]
    settle = _Planned(_settle(message, reply, last_user), None, at, last_user)
    return [_Planned(reply, element.seq, at), settle]


def _user_message(
    message: ConversationEntry, surface: ConversationSource, reactions: Mapping[str, str]
) -> UserMessage:
    mid = str(message.message_id)
    folded = reactions.get(mid)
    reaction = (
        Reaction(emoji=folded, by=ReactionBy.CHAT_MODEL)
        if folded
        else Reaction(emoji=message.reaction.emoji, by=message.reaction.by)
        if message.reaction
        else None
    )
    return UserMessage(
        id=mid,
        text=message.response,
        surface=surface,
        platform_message_id=message.platform_message_id,
        file_ids=tuple(message.fileIds or ()),
        files=tuple(message.fileData or ()),
        selected_tool=message.selectedTool,
        tool_category=message.toolCategory,
        selected_workflow=message.selectedWorkflow,
        selected_calendar_event=message.selectedCalendarEvent,
        reply_to_message=message.replyToMessage,
        reaction=reaction,
        first_contact=bool(message.first_contact),
        pinned=bool(message.pinned),
        todo_run_wake=message.todo_run_wake,
        imported=True,
    )


def _reply(message: ConversationEntry, users: set[str], *, blank: bool) -> Reply:
    mid = str(message.message_id)
    quoted = message.replyToMessage.id if message.replyToMessage else None
    return Reply(
        id=mid,
        reply_id=mid,
        attempt_id=f"imported:{mid}",
        text="" if blank else message.response,
        tool_data=tuple(message.tool_data or ()),
        follow_up_actions=tuple(message.follow_up_actions or ()),
        image=message.image_data,
        quote_target=quoted if quoted in users else None,
        pinned=bool(message.pinned),
        imported=True,
    )


def _settle(message: ConversationEntry, reply: Reply, answered: str | None) -> ReplySettled:
    outcome, failure = _settle_outcome(message)
    return ReplySettled(
        id=f"{reply.reply_id}:settled",
        reply_id=reply.reply_id,
        outcome=outcome,
        answers=() if answered is None else (answered,),
        through=0,
        quote_target=reply.quote_target,
        failure=failure,
        imported=True,
    )


def _sources(
    head: EmbeddedHead, stored: Sequence[StoredEntry], minted: Sequence[str | None] | None
) -> tuple[list[_Element], dict[str, StoredEntry], list[StoredEntry]]:
    """Return the old messages in order, the log entries already written by id, and the message-shaped entries.

    Entries past log_head are a raced or dead pass's inserts, which the write removes.
    """
    counted = [row for row in stored if row.seq <= (head.log_head or 0)]
    shaped = [row for row in counted if "type" in row.message_fields()]
    shaped_ids = {row.id for row in shaped}
    existing = {row.id: row for row in counted if row.id not in shaped_ids}
    elements = [_Element({**row.message_fields(), _ID_FIELD: row.id}, row.seq) for row in shaped]
    for n, legacy in enumerate(head.messages):
        fields = legacy.stored()
        if minted is not None and minted[n] is not None:
            fields[_ID_FIELD] = minted[n]
        if MessageShape.model_validate(fields).message_id not in shaped_ids:
            elements.append(_Element(fields))
    return elements, existing, shaped


def _fold(log: Mapping[int, LoggedEntry]) -> ConversationState:
    """Fold the whole log from empty and require it idle: imported history is already answered."""
    state = EMPTY_LOG_STATE
    for seq in sorted(log):
        result = reduce(state, log[seq])
        if not isinstance(result, Transition):
            raise MigrationRefused(f"the log refuses seq {seq}: {result.reason}")
        state = result.state
    idle = (
        state.open_reply is None
        and not state.unsettled_waking
        and not state.work
        and not state.finished_work
        and not state.unsettled_fires
    )
    if not idle:
        raise MigrationRefused(f"the written log is not idle: {state.model_dump(mode='json')}")
    return state


def _changed(existing: StoredEntry, document: Mapping[str, object]) -> dict[str, object]:
    """Return the update that sets only the fields whose source changed since the last pass wrote them."""
    written = existing.migration_fields or field_hashes(existing.document())
    now = field_hashes(document)
    changed = {key: document[key] for key, digest in now.items() if written.get(key) != digest}
    removed = {key: "" for key in written if key not in now}
    if not changed and not removed:
        return {}
    update: dict[str, object] = {"$set": {**changed, MIGRATION_FIELDS_FIELD: now}}
    if removed:
        update["$unset"] = removed
    return update


def _normalized(payload: Mapping[str, object], *, dated: bool) -> dict[str, object]:
    """Return a message as verify compares it: shown fields only, empty values dropped, dates to the ms."""
    shown: dict[str, object] = {}
    for key, value in payload.items():
        if key not in _SHOWN_FIELDS or value in (None, [], False, {}):
            continue
        if key == "date":
            if not dated or (at := entry_at(value)) is None:
                continue
            value = (
                at.astimezone(UTC).replace(microsecond=at.microsecond // 1000 * 1000).isoformat()
            )
        shown[key] = value
    return shown


def expected_messages(elements: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    """Return what a client reads of the old array once migrated, derived from the array alone.

    An emoji_ack with a target and an emoji is its target's chat-model reaction (kept, emptied,
    when it carries cards); a failure reads as its reason, model_error when the old text names
    none; a bot quote of a user message reads that message's text.
    """
    parsed = [(e, ConversationEntry.model_validate({**e, "seq": 0})) for e in elements]
    users = {m.message_id: m for _, m in parsed if m.type == USER_MESSAGE_TYPE}
    reactions: dict[str, str] = {}
    folded: set[str] = set()
    for raw, m in parsed:
        shape = MessageShape.model_validate(raw)
        target, emoji = shape.reacts_to_message_id, str(m.response).strip()
        if shape.kind == _ACK_KIND and emoji and target in users:
            reactions[str(target)] = emoji
            folded.add(str(m.message_id))
    expected: list[dict[str, object]] = []
    for raw, m in parsed:
        payload = m.model_dump(mode="json")
        dated = entry_at(MessageShape.model_validate(raw).date) is not None
        if m.type == USER_MESSAGE_TYPE:
            if m.message_id in reactions:
                payload["reaction"] = {"emoji": reactions[str(m.message_id)], "by": "chat_model"}
            payload.update(error=None, stopped=None, in_progress=None)
            expected.append(_normalized(payload, dated=dated))
            continue
        if m.message_id in folded:
            if not m.tool_data:
                continue
            payload["response"] = ""
        quoted = users.get(m.replyToMessage.id) if m.replyToMessage else None
        payload["replyToMessage"] = (
            None
            if quoted is None
            else {"id": quoted.message_id, "content": quoted.response, "role": "user"}
        )
        if m.in_progress:
            payload.update(error=None, stopped=None)
        elif m.error:
            known = {reason.value for reason in FailureReason}
            payload.update(error=m.error if m.error in known else FailureReason.MODEL_ERROR.value)
            payload.update(stopped=None)
        payload["type"] = BOT_MESSAGE_TYPE
        expected.append(_normalized(payload, dated=dated))
    return expected


def _of(ref: HeadRef) -> dict[str, str]:
    return {"user_id": ref.user_id, "conversation_id": ref.conversation_id}


def _with_ids(minted: Sequence[str | None]) -> dict[str, object]:
    """Write each minted id into its element in place, leaving every other element as it is."""
    return {
        "$map": {
            "input": {"$range": [0, {"$size": "$messages"}]},
            "as": "i",
            "in": {
                "$let": {
                    "vars": {
                        "element": {"$arrayElemAt": ["$messages", "$$i"]},
                        "minted": {"$arrayElemAt": [{"$literal": list(minted)}, "$$i"]},
                    },
                    "in": {
                        "$cond": [
                            {"$eq": ["$$minted", None]},
                            "$$element",
                            {"$mergeObjects": ["$$element", {_ID_FIELD: "$$minted"}]},
                        ]
                    },
                }
            },
        }
    }


class ConversationEntriesMigration(ConversationRepository):
    """The entries migration's reads and writes of the conversations heads and their entries."""

    async def heads_to_migrate(self, *, after_head_id: str | None, batch: int) -> list[HeadRef]:
        """Return the next batch of heads whose embedded array the log does not match yet (any in-place edit shows)."""
        return await self._scan(dict(UNMIGRATED_HEADS), after_head_id=after_head_id, batch=batch)

    async def heads_with_embedded(self, *, after_head_id: str | None, batch: int) -> list[HeadRef]:
        """Return the next batch of heads still holding an embedded array, in _id order."""
        match: dict[str, object] = {"messages.0": {"$exists": True}}
        return await self._scan(match, after_head_id=after_head_id, batch=batch)

    async def heads_with_message_entries(
        self, *, after_head_id: str | None, batch: int
    ) -> list[HeadRef]:
        """Return the next batch of heads whose stored entries still include message-shaped ones."""
        entries = self._sibling_collection(CONVERSATION_ENTRIES_COLLECTION).name
        match: dict[str, object] = (
            {} if after_head_id is None else {"_id": {"$gt": ObjectId(after_head_id)}}
        )
        pipeline: list[Mapping[str, object]] = [
            {"$match": match},
            _BY_HEAD_ID,
            {
                "$lookup": {
                    "from": entries,
                    "localField": "conversation_id",
                    "foreignField": "conversation_id",
                    "let": {"owner": "$user_id"},
                    "pipeline": [
                        {"$match": {**MESSAGE_SHAPED, "$expr": {"$eq": ["$user_id", "$$owner"]}}},
                        {"$limit": 1},
                        {"$project": {"_id": 1}},
                        # pragma: no mutate end
                    ],
                    "as": _FOUND,
                }
            },
            {"$match": {f"{_FOUND}.0": {"$exists": True}}},
            {"$limit": batch},
            _HEAD_REF_STAGE,
        ]
        with store_errors("migration scan"):  # pragma: no mutate — error label only
            rows = await self._aggregate(pipeline, HeadRefRow)
        return [HeadRef(row.head_id, row.conversation_id, row.user_id) for row in rows]

    async def first_unmigrated(self) -> str | None:
        """Name one conversation the new build cannot serve: an array no pass marked, or message-shaped entries."""
        with store_errors("migration check"):  # pragma: no mutate — error label only
            head = await self._raw_collection().find_one(
                NEVER_MIGRATED_HEADS, {"_id": 0, "conversation_id": 1}
            )
            if head is not None:
                return _ConversationIdRow.model_validate(head).conversation_id
            entry = await self._sibling_collection(CONVERSATION_ENTRIES_COLLECTION).find_one(
                MESSAGE_SHAPED, {"_id": 0, "conversation_id": 1}
            )
        return None if entry is None else _ConversationIdRow.model_validate(entry).conversation_id

    async def migrate(self, ref: HeadRef, *, apply: bool) -> MigrationOutcome:
        """Rewrite one conversation's old messages as log entries (report only unless apply)."""
        await self.flush_outbox(ref.conversation_id, user_id=ref.user_id)
        head = await self._head(ref)
        if head is None:
            return MigrationOutcome(
                ref.conversation_id, MigrationAction.UNCHANGED, reason="deleted"
            )
        minted = minted_ids(head.messages)
        identified = sum(entry_id is not None for entry_id in minted)
        if identified and apply:
            if not await self._identify(ref, head.fingerprint, minted):
                return MigrationOutcome(ref.conversation_id, MigrationAction.RACED)
            head = await self._head(ref)
            if head is None:
                return MigrationOutcome(ref.conversation_id, MigrationAction.RACED)
        stored = await self._stored(ref)
        try:
            plan = self._plan(ref, head, stored, minted=None if apply else minted)
        except MigrationRefused as exc:
            return MigrationOutcome(ref.conversation_id, MigrationAction.REFUSED, reason=str(exc))
        action = MigrationAction.COPIED if head.log_head is None else MigrationAction.MERGED
        marked = head.migrated_fingerprint == head.fingerprint or not head.messages
        if not plan.writes and marked and head.log_head == max(plan.log, default=0):
            action = MigrationAction.UNCHANGED
        outcome = MigrationOutcome(
            ref.conversation_id,
            action,
            written=len(plan.inserts) + len(plan.replaces),
            rewritten=len(plan.updates),
            identified=identified,
            folded=plan.folded,
            not_kept=plan.not_kept,
        )
        if (
            apply
            and action is not MigrationAction.UNCHANGED
            and not await self._write(ref, head, plan)
        ):
            outcome.action = MigrationAction.RACED
        return outcome

    async def verify(self, ref: HeadRef) -> VerifyReport:
        """Check that what clients read back (history, sync, search, pinned) is what the old array showed."""
        await self.flush_outbox(ref.conversation_id, user_id=ref.user_id)
        report = VerifyReport(ref.conversation_id)
        head = await self._head(ref)
        if head is None:
            report.mismatches.append("deleted since the scan")
            return report
        stored = [row for row in await self._stored(ref) if row.seq <= (head.log_head or 0)]
        if any("type" in row.message_fields() for row in stored):
            report.mismatches.append("message-shaped entries remain: run --apply")
        if head.messages and head.migrated_fingerprint != head.fingerprint:
            report.mismatches.append("written since its last pass: run --apply")
        report.fingerprint = head.fingerprint if head.messages else None
        if report.mismatches:
            return report
        log = {row.seq: logged_of(row) for row in stored}
        try:
            state = _fold(log)
        except MigrationRefused as exc:
            report.mismatches.append(str(exc))
            return report
        if head.log_head != max(log, default=0) or head.state != state:
            report.mismatches.append("the head's log_head or state is not the fold of its entries")
        if head.messages:
            await self._compare_reads(ref, [m.stored() for m in head.messages], report)
        return report

    async def drop_embedded(self, ref: HeadRef, *, verified: int) -> bool:
        """Unset the embedded array, only while it is exactly the array a passing verify fingerprinted."""
        with store_errors("drop embedded"):  # pragma: no mutate — error label only
            result = await self._raw_collection().update_one(
                {
                    "_id": ObjectId(ref.head_id),
                    MIGRATED_FINGERPRINT_FIELD: verified,
                    "$expr": {"$eq": [EMBEDDED_FINGERPRINT, verified]},
                },
                {"$unset": _UNSET_EMBEDDED},
            )
        return result.modified_count > 0

    async def _compare_reads(
        self, ref: HeadRef, elements: Sequence[Mapping[str, object]], report: VerifyReport
    ) -> None:
        expected = expected_messages(elements)
        shapes = [MessageShape.model_validate(e) for e in elements]
        dated = {str(shape.message_id) for shape in shapes if entry_at(shape.date) is not None}
        report.messages = len(expected)

        def shown(messages: Sequence[ConversationEntry]) -> list[dict[str, object]]:
            return [
                _normalized(m.model_dump(mode="json"), dated=m.message_id in dated)
                for m in messages
            ]

        heads = await self._read_heads(_of(ref))
        [history] = await self._histories(heads, EntryWindow(), limit=None)
        if shown(history.messages) != expected:
            report.mismatches.append(_difference("history", shown(history.messages), expected))
        synced = await self.find_updated_since(
            ref.user_id, [ConversationSyncItem(conversation_id=ref.conversation_id)]
        )
        tail = shown(synced[0].messages) if synced else []
        if tail != expected[len(expected) - len(tail) :] or (not tail and expected):
            report.mismatches.append(_difference("sync", tail, expected[-len(tail) :]))
        for name, match, wanted in (
            ("search", {"kind": {"$in": sorted(TEXT_KINDS)}, "text": {"$ne": ""}}, "response"),
            ("pinned", {"kind": {"$in": sorted(PINNABLE_KINDS)}, "pinned": True}, "pinned"),
        ):
            rows = await self._find_entries(ref.user_id, {**_of(ref), **match})
            hits = shown([hit.message for hit in await self._hits(ref.user_id, rows)])
            want = [m for m in expected if m.get(wanted)]
            if sorted(hits, key=_by_id) != sorted(want, key=_by_id):
                report.mismatches.append(_difference(name, hits, want))

    def _plan(
        self,
        ref: HeadRef,
        head: EmbeddedHead,
        stored: Sequence[StoredEntry],
        *,
        minted: Sequence[str | None] | None,
    ) -> _Plan:
        """Plan the writes that turn the sources into log entries, then fold the result and require it idle.

        minted names the ids a dry run would write back, so its plan matches the applied one.
        """
        elements, existing, shaped = _sources(head, stored, minted)
        planned, folded = _planned(elements, _surface(head.source))
        plan = _Plan(folded=folded)
        plan.not_kept = sum(NotKeptFields.model_validate(e.fields).carried() for e in elements)
        plan.log = {row.seq: logged_of(row) for row in existing.values()}
        next_seq = head.log_head or 0
        seq_of: dict[str, int] = {}
        for item in sorted(planned, key=lambda p: isinstance(p.entry, ReplySettled)):
            entry = item.entry
            if isinstance(entry, ReplySettled):
                through = seq_of.get(item.settles_after or "", 0)
                entry = entry.model_copy(update={"through": through})
            prior = existing.get(entry.id)
            seq = prior.seq if prior else item.seq
            if seq is None:
                next_seq += 1
                seq = next_seq
            seq_of[entry.id] = seq
            at = item.at or (prior.at if prior and prior.at else None) or datetime.now(UTC)
            plan.add(ref, LoggedEntry(seq=seq, at=at, entry=entry), prior, in_place=item.seq)
        placed = set(seq_of.values())
        for row in shaped:
            if row.seq not in placed:
                # A folded ack already holding a seq stays as an empty imported reply, never a gap.
                blank = Reply(
                    id=row.id, reply_id=row.id, attempt_id=f"imported:{row.id}", imported=True
                )
                at = row.at or datetime.now(UTC)
                plan.add(ref, LoggedEntry(seq=row.seq, at=at, entry=blank), None, in_place=row.seq)
        if sorted(plan.log) != list(range(1, len(plan.log) + 1)):
            raise MigrationRefused("the log would have a gap in its seqs")
        plan.state = _fold(plan.log)
        return plan

    async def _write(self, ref: HeadRef, head: EmbeddedHead, plan: _Plan) -> bool:
        """Write the plan's entries, then the head, only while it is as read; a raced pass removes its inserts."""
        entries = self._sibling_collection(CONVERSATION_ENTRIES_COLLECTION)
        read_head = head.log_head or 0
        expected: dict[str, object] = {
            "_id": ObjectId(ref.head_id),
            LOG_HEAD_FIELD: head.log_head if head.log_head is not None else {"$exists": False},
            "$expr": {"$eq": [EMBEDDED_FINGERPRINT, head.fingerprint]},
        }
        marks: dict[str, object] = {
            LOG_HEAD_FIELD: max(plan.log, default=0),
            STATE_FIELD: plan.state.model_dump(mode="json"),
        }
        if head.messages:
            marks[MIGRATED_FINGERPRINT_FIELD] = head.fingerprint
        with store_errors("migration write"):  # pragma: no mutate — error label only
            await entries.delete_many({**_of(ref), "seq": {"$gt": read_head}})
            for seq, document in plan.replaces:
                await entries.replace_one({**_of(ref), "seq": seq}, document)
            for entry_id, update in plan.updates:
                await entries.update_one({**_of(ref), "id": entry_id}, update)
            if plan.inserts:
                await entries.insert_many(plan.inserts)
            result = await self._raw_collection().update_one(
                expected,
                {
                    "$set": marks,
                    **({"$currentDate": {"updatedAt": True}} if plan.writes else {}),
                },
            )
            if not result.matched_count:
                await entries.delete_many({**_of(ref), "seq": {"$gt": read_head}})
        return result.matched_count > 0

    async def _scan(
        self, match: dict[str, object], *, after_head_id: str | None, batch: int
    ) -> list[HeadRef]:
        if after_head_id is not None:
            match["_id"] = {"$gt": ObjectId(after_head_id)}
        pipeline: list[Mapping[str, object]] = [
            {"$match": match},
            _BY_HEAD_ID,
            {"$limit": batch},
            _HEAD_REF_STAGE,
        ]
        with store_errors("migration scan"):  # pragma: no mutate — error label only
            rows = await self._aggregate(pipeline, HeadRefRow)
        return [HeadRef(row.head_id, row.conversation_id, row.user_id) for row in rows]

    async def _head(self, ref: HeadRef) -> EmbeddedHead | None:
        pipeline: list[Mapping[str, object]] = [
            {"$match": {"_id": ObjectId(ref.head_id)}},
            {"$addFields": {"_fingerprint": EMBEDDED_FINGERPRINT}},
        ]
        with store_errors("migration read"):  # pragma: no mutate — error label only
            raws = await self._raw_collection().aggregate(pipeline).to_list(length=None)
        return EmbeddedHead.model_validate(raws[0]) if raws else None

    async def _stored(self, ref: HeadRef) -> list[StoredEntry]:
        with store_errors("migration read"):  # pragma: no mutate — error label only
            rows = (
                await self._sibling_collection(CONVERSATION_ENTRIES_COLLECTION)
                .find(_of(ref))
                .sort([("seq", 1)])
                .to_list(None)
            )
        return [StoredEntry.model_validate(row) for row in rows]

    async def _identify(self, ref: HeadRef, fingerprint: int, minted: Sequence[str | None]) -> bool:
        """Write the minted ids into the array, only while it is still the array they were minted for."""
        with store_errors("migration identify"):  # pragma: no mutate — error label only
            result = await self._raw_collection().update_one(
                {
                    "_id": ObjectId(ref.head_id),
                    "$expr": {"$eq": [EMBEDDED_FINGERPRINT, fingerprint]},
                },
                [{"$set": {"messages": _with_ids(minted)}}],
            )
        return result.modified_count > 0


def _surface(source: str | None) -> ConversationSource:
    try:
        return ConversationSource(source) if source else ConversationSource.WEB
    except ValueError:
        return ConversationSource.WEB


def _by_id(message: Mapping[str, object]) -> str:
    return str(message.get(_ID_FIELD))


def _difference(read: str, actual: Sequence[object], expected: Sequence[object]) -> str:
    for n, (got, want) in enumerate(zip(actual, expected, strict=False)):
        if got != want:
            return f"{read} differs at message {n}: read {got}, expected {want}"
    return f"{read} reads {len(actual)} messages, expected {len(expected)}"


async def refuse_unmigrated_conversations() -> None:
    """Refuse to boot while any conversation still needs the entries migration."""
    conversation_id = await conversation_entries_migration.first_unmigrated()
    if conversation_id is not None:
        raise unmigrated(f"conversation {conversation_id}")


conversation_entries_migration = ConversationEntriesMigration()
