"""A stored entry reads back as a row carrying its owner, conversation and commit time."""

from datetime import UTC, datetime

import pytest

from app.constants.chat import ConversationSource
from app.db.repositories.conversation_entries import stored_row
from app.models.conversation_log_models import UserMessage
from app.utils.errors import ConversationStoreError


def _stored(at: datetime | None) -> dict[str, object]:
    message = UserMessage(id="m1", text="hi", surface=ConversationSource.WEB)
    return {**message.model_dump(), "conversation_id": "c1", "user_id": "u1", "seq": 4, "at": at}


def test_a_stored_row_carries_its_commit_time() -> None:
    at = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)

    row = stored_row(_stored(at))

    assert (row.conversation_id, row.logged.seq, row.logged.at) == ("c1", 4, at)
    assert row.logged.entry == UserMessage(id="m1", text="hi", surface=ConversationSource.WEB)


def test_a_stored_row_without_a_commit_time_is_corrupt() -> None:
    with pytest.raises(ConversationStoreError):
        stored_row(_stored(None))
