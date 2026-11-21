"""Give every conversation head the source its replies are written for.

Web chats were stored without a source before this stack, and a tracked todo's chat was
created without one; the running app now requires it. A head is read as its own kind: a todo's
chat runs in the background, a workflow's runs are GAIA's own, and anything else is an app chat.
"""

from __future__ import annotations

from app.constants.chat import ConversationSource
from app.db.repositories.conversation_entries import store_errors
from app.db.repositories.conversation_migration_guard import (
    SOURCELESS_HEADS,
    ConversationMigrationGuard,
)
from app.models.chat_models import SystemPurpose

#: In order: the first rule a sourceless head matches names its source; the last matches every head.
_RULES: tuple[tuple[dict[str, object], ConversationSource], ...] = (
    ({"todo_id": {"$type": "string"}}, ConversationSource.BACKGROUND),
    (
        {
            "$or": [
                {"metadata.workflow_id": {"$exists": True}},
                {"system_purpose": SystemPurpose.WORKFLOW_EXECUTION.value},
            ]
        },
        ConversationSource.WORKFLOW_SYSTEM,
    ),
    ({}, ConversationSource.WEB),
)


class ConversationSourceBackfill(ConversationMigrationGuard):
    """Sets the source of every head that has none this build knows."""

    async def backfill(self, *, apply: bool) -> dict[ConversationSource, int]:
        """Return how many heads each source was (or, on a dry run, would be) given."""
        heads = self._raw_collection()
        given: dict[ConversationSource, int] = {}
        with store_errors("source backfill"):  # pragma: no mutate — error label only
            for index, (rule, source) in enumerate(_RULES):
                unmatched_earlier = [{"$nor": [earlier]} for earlier, _ in _RULES[:index]]
                match = {"$and": [SOURCELESS_HEADS, rule, *unmatched_earlier]}
                if apply:
                    result = await heads.update_many(match, {"$set": {"source": source.value}})
                    given[source] = result.modified_count
                else:
                    given[source] = await heads.count_documents(match)
        return given

    async def count_sourceless(self) -> int:
        """How many heads still have no source this build knows."""
        with store_errors("source backfill"):  # pragma: no mutate — error label only
            return await self._raw_collection().count_documents(SOURCELESS_HEADS)


conversation_source_backfill = ConversationSourceBackfill()
