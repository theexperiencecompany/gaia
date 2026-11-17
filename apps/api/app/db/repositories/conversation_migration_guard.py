"""The boot check that refuses to serve while any conversation holds a shape the build cannot read.

The running app reads only the conversation log. Five marks say a conversation is not readable
yet: an embedded messages array no migration pass marked, a message-shaped entry, a head with no
source this build knows, an entry still holding a field this stack renamed, and a conversation the
last migration pass or verify failed on. Every query is index-backed (see indexes.py), so the
check stays a few indexed lookups however large the data grows.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.constants.chat import (
    CONVERSATION_ENTRIES_COLLECTION,
    CONVERSATION_ENTRIES_MIGRATION_SCRIPT,
    CONVERSATION_MIGRATION_FAILURES_COLLECTION,
    ENTRY_RENAMES_MIGRATION_SCRIPT,
    ConversationSource,
)
from app.db.repositories.conversation_entries import store_errors
from app.db.repositories.conversations import ConversationRepository
from app.models.conversation_models import _ConversationIdRow
from app.utils.errors import UnmigratedConversationError

#: The fingerprint of the embedded array as the migration last rewrote it, so any later old-build write shows.
MIGRATED_FINGERPRINT_FIELD = "migrated_fingerprint"
#: An embedded array no migration pass ever marked.
NEVER_MIGRATED_HEADS: dict[str, object] = {
    "messages.0": {"$exists": True},
    MIGRATED_FINGERPRINT_FIELD: {"$exists": False},
}
#: A head with no source, or one this build does not know: its replies would have no prompt to pick.
SOURCELESS_HEADS: dict[str, object] = {"source": {"$nin": [s.value for s in ConversationSource]}}
#: Message-shaped entries carry the old type field (user or bot); no log entry has one.
MESSAGE_SHAPED: dict[str, object] = {"type": {"$exists": True}}
#: Fields an earlier build of this stack stored on entries and the entry models now forbid.
RENAMED_ENTRY_FIELDS: tuple[str, ...] = ("summary", "decision", "heard_text", "run.reservation")
RENAMED_ENTRY_SHAPED: dict[str, object] = {
    "$or": [{name: {"$exists": True}} for name in RENAMED_ENTRY_FIELDS]
}
#: The guard reads only ids: the row model ignores every other key, so the projection only trims the read.
_ID_ONLY = {"_id": 0, "conversation_id": 1}  # pragma: no mutate — projection


def unmigrated(conversation_id: str, *, what: str, script: str) -> UnmigratedConversationError:
    """Build the boot refusal for data still in an old shape, naming the command that rewrites it."""
    return UnmigratedConversationError(
        message=(
            f"conversation {conversation_id} still holds {what}: run "
            f"python -m {script} --apply, then --verify"
        ),
    )


class ConversationMigrationGuard(ConversationRepository):
    """Reads the marks of a conversation the log cannot serve yet."""

    async def first_unmigrated(self) -> str | None:
        """Name one conversation the new build cannot serve: an array no pass marked, or message-shaped entries."""
        with store_errors("migration check"):  # pragma: no mutate — error label only
            # pragma: no mutate start — the projection only trims the read
            head = await self._raw_collection().find_one(NEVER_MIGRATED_HEADS, _ID_ONLY)
            # pragma: no mutate end
            if head is not None:
                return _ConversationIdRow.model_validate(head).conversation_id
            entries = self._sibling_collection(CONVERSATION_ENTRIES_COLLECTION)
            # pragma: no mutate start — the projection only trims the read
            entry = await entries.find_one(MESSAGE_SHAPED, _ID_ONLY)
            # pragma: no mutate end
        return None if entry is None else _ConversationIdRow.model_validate(entry).conversation_id

    async def first_sourceless(self) -> str | None:
        """Name one conversation whose head has no source this build knows."""
        with store_errors("migration check"):  # pragma: no mutate — error label only
            # pragma: no mutate start — the projection only trims the read
            head = await self._raw_collection().find_one(SOURCELESS_HEADS, _ID_ONLY)
            # pragma: no mutate end
        return None if head is None else _ConversationIdRow.model_validate(head).conversation_id

    async def first_failed(self) -> str | None:
        """Name one conversation the entries migration's last pass or verify failed on."""
        failures = self._sibling_collection(CONVERSATION_MIGRATION_FAILURES_COLLECTION)
        with store_errors("migration check"):  # pragma: no mutate — error label only
            # pragma: no mutate start — the projection only trims the read
            failure = await failures.find_one({}, _ID_ONLY)
            # pragma: no mutate end
        return (
            None if failure is None else _ConversationIdRow.model_validate(failure).conversation_id
        )

    async def first_renamed(self) -> str | None:
        """Name one conversation holding an entry with a field this stack renamed."""
        entries = self._sibling_collection(CONVERSATION_ENTRIES_COLLECTION)
        with store_errors("migration check"):  # pragma: no mutate — error label only
            # pragma: no mutate start — the projection only trims the read
            entry = await entries.find_one(RENAMED_ENTRY_SHAPED, _ID_ONLY)
            # pragma: no mutate end
        return None if entry is None else _ConversationIdRow.model_validate(entry).conversation_id


@dataclass(frozen=True)
class Refusal:
    """One conversation the build cannot serve yet, what it still holds and the command that fixes it."""

    conversation_id: str
    what: str
    script: str

    def error(self) -> UnmigratedConversationError:
        return unmigrated(self.conversation_id, what=self.what, script=self.script)


async def first_refusal() -> Refusal | None:
    """Name one conversation the build cannot serve: the one check the boot and the pre-boot migration share."""
    guard = ConversationMigrationGuard()
    entries = CONVERSATION_ENTRIES_MIGRATION_SCRIPT
    checks = (
        (guard.first_failed, "a failed migration pass or verify", entries),
        (guard.first_unmigrated, "messages in the old shape", entries),
        (guard.first_sourceless, "no source", entries),
        (guard.first_renamed, "log entries with renamed fields", ENTRY_RENAMES_MIGRATION_SCRIPT),
    )
    for first, what, script in checks:
        if conversation_id := await first():
            return Refusal(conversation_id, what, script)
    return None


async def refuse_unmigrated_conversations() -> None:
    """Refuse to boot while any conversation needs the entries migration (its messages or its source) or the entry renames."""
    if refusal := await first_refusal():
        raise refusal.error()
