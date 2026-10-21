"""The id contract for messages written into a thread outside the normal graph path."""

from __future__ import annotations

from uuid import UUID

from langchain_core.messages import AIMessage, HumanMessage

from app.agents.core.thread_writes import with_message_ids


def test_id_less_messages_get_a_distinct_uuid_in_place() -> None:
    messages = [HumanMessage("one"), AIMessage("two")]

    returned = with_message_ids(messages)

    assert returned is messages
    ids = [message.id for message in messages]
    assert all(isinstance(message_id, str) for message_id in ids)
    # Parsing rejects None and "None" alike, and the set rules out one id
    # reused for both — either would make a later RemoveMessage ambiguous.
    assert all(UUID(message_id) for message_id in ids)
    assert len(set(ids)) == 2


def test_a_message_that_already_has_an_id_keeps_it() -> None:
    message = HumanMessage("kept", id="existing-id")

    with_message_ids([message])

    assert message.id == "existing-id"
