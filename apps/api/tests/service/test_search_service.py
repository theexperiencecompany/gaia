"""
Service tests for ``search_messages`` against real MongoDB.

BEHAVIOR SPEC
=============
UNIT: app/services/search_service.py :: search_messages(query, user_id)
EXPECTED: Keyword-search a user's conversations (messages + descriptions) and
          notes. Return ``{"messages", "conversations", "notes"}`` where each
          matched message/note carries a ``snippet`` context window, legacy
          message tool fields are converted to the unified ``tool_data`` array,
          and ONLY the calling user's data is ever returned. Emit a structured
          wide-event log before and after the search; on any failure raise
          HTTPException(500, "Failed to perform search: ...").
MECHANISM: conversations_collection.aggregate($match user_id -> $facet messages
           ($unwind, $regex/$options "i" match on messages.response) +
           conversations ($regex/$options "i" match on description)); a separate
           notes_collection.aggregate($match user_id + $regex/$options "i" on
           plaintext); snippets via get_context_window(..., chars_before=30);
           convert_legacy_tool_data per message; serialize_document per note.

MUST-CATCH (each maps to >=1 test + >=1 killed mutant):
  - case-INSENSITIVE matching: seed mixed-case text, query lowercase, still
    matches  [kills $options "i" removal + $regex removal]
  - $match {user_id} scoping: a second user's matching data is never returned
    [kills $match user_id mutant / cross-user isolation]
  - the EXACT snippet string for a known long response  [kills chars_before
    30->31 const mutation]
  - legacy tool field on a message is converted into tool_data  [kills the
    convert_legacy_tool_data wiring]
  - the return dict has EXACTLY keys {messages, conversations, notes} with the
    right counts  [kills return-key + $project + facet-key mutants]
  - structured log fields (query, query_length, search_type, sources,
    result_count, user_id, service) are emitted  [kills logging-string +
    result_count arithmetic mutants]
  - on aggregate failure -> HTTPException 500 with detail starting
    "Failed to perform search:"  [kills error-string + status mutants]

EQUIVALENT MUTANTS (allowed survivors, justified):
  - L20 module docstring str->'' : not observable through behavior.
  - L131 duration_ms = int((monotonic - start) * 1000) operand mutations
    (Sub->Add, Mult->Div, 1000->1001): the value is wall-clock dependent and
    is only ever written to the log; it cannot be asserted deterministically
    without making the test time-sensitive (banned by the rubric). The
    *presence* of duration_ms is asserted; its exact value is genuinely
    untestable, so these three are behaviour-preserving for any deterministic
    oracle.
  - $project include-flag bumps 1->2 (conversation_id/description/note_id/
    plaintext in the message, conversation, and notes facets): MongoDB
    $project treats any truthy value identically to 1, so 1->2 selects the
    exact same fields with the exact same values (verified byte-identical
    against real Mongo). Behaviour-preserving.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import patch
import uuid

from bson import ObjectId
from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorClient
import pytest

from app.services.search_service import search_messages

# ---------------------------------------------------------------------------
# Constants — the exact query and the known-long response whose snippet we pin.
# ---------------------------------------------------------------------------

QUERY = "photosynthesis"  # lowercase; seeded text is mixed-case on purpose.

LONG_RESPONSE = (
    "The morning briefing covered many topics and then explained "
    "Photosynthesis is how plants convert light into chemical energy "
    "for survival."
)
# get_context_window(LONG_RESPONSE, "photosynthesis", chars_before=30, chars_after=30).
# Pinned exactly so the chars_before 30->31 mutation (one extra leading char)
# is killed.
EXPECTED_SNIPPET = (
    "...any topics and then explained Photosynthesis is how plants convert light i..."
)

NOTE_PLAINTEXT = (
    "Today I wrote down a long study reminder that I should revise "
    "PhotoSynthesis chapter before the upcoming biology exam next week."
)
# get_context_window(NOTE_PLAINTEXT, "photosynthesis", chars_before=30, chars_after=30),
# match index 62 so the 30-char leading window is well clear of the start.
# Pinned exactly so the chars_before 30->31 mutation (one extra leading char)
# is killed for the NOTE snippet too.
EXPECTED_NOTE_SNIPPET = (
    "...reminder that I should revise PhotoSynthesis chapter before the upcoming b..."
)


class _LogRecorder:
    """Boundary double for the wide-event ``log`` singleton.

    Records every ``set()`` call (both the per-call payload and the merged
    view) and every ``error()`` message so the structured-logging contract can
    be asserted as real emitted behaviour. ``calls`` preserves each individual
    ``set()`` so the FIRST (pre-search) log payload can be asserted in
    isolation — the second ``set()`` re-emits the same ``search`` dict, so a
    merged-only view would mask mutations to the first call. Only the logging
    side effect is intercepted — ``search_messages`` itself and all DB
    collaborators run for real.
    """

    def __init__(self) -> None:
        self.fields: dict[str, Any] = {}
        self.calls: list[dict[str, Any]] = []
        self.errors: list[str] = []

    def set(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)
        self.fields.update(kwargs)

    def error(self, message: str, **_: Any) -> None:
        self.errors.append(message)


# ---------------------------------------------------------------------------
# Fixtures — real Mongo collections wired into the service module singletons.
# ---------------------------------------------------------------------------


@pytest.fixture
async def search_env(mongodb_url: str, monkeypatch) -> AsyncIterator[dict[str, Any]]:
    """Seed two isolated users in real Mongo and patch the service singletons.

    A fresh Motor client per test avoids event-loop cross-contamination
    (asyncio_default_fixture_loop_scope is "function"). Unique uuid4 user IDs
    guarantee parallel xdist workers never collide; all seeded docs are removed
    on teardown so the dev DB is left clean.
    """
    client: AsyncIOMotorClient = AsyncIOMotorClient(mongodb_url)
    db = client["gaia_test"]
    conversations = db["conversations"]
    notes = db["notes"]

    user_id = f"search-user-{uuid.uuid4()}"
    other_user_id = f"search-other-{uuid.uuid4()}"

    conv_match_id = f"conv-{uuid.uuid4()}"
    conv_desc_id = f"conv-{uuid.uuid4()}"
    conv_legacy_id = f"conv-{uuid.uuid4()}"
    conv_long_id = f"conv-{uuid.uuid4()}"
    note_match_id = f"note-{uuid.uuid4()}"
    other_conv_id = f"conv-{uuid.uuid4()}"
    other_note_id = f"note-{uuid.uuid4()}"

    seeded_user_ids = [user_id, other_user_id]

    # --- Target user data ------------------------------------------------
    # 1) A conversation whose message.response matches (mixed case "PhotoSynthesis").
    await conversations.insert_one(
        {
            "user_id": user_id,
            "conversation_id": conv_match_id,
            "description": "unrelated description",
            "messages": [
                {
                    "type": "bot",
                    "response": "All about PhotoSynthesis in simple terms.",
                },
                {
                    "type": "bot",
                    "response": "This one mentions nothing relevant at all.",
                },
            ],
        }
    )
    # 2) A conversation whose DESCRIPTION matches (mixed case).
    await conversations.insert_one(
        {
            "user_id": user_id,
            "conversation_id": conv_desc_id,
            "description": "A deep dive into PHOTOSYNTHESIS and plant biology.",
            "messages": [],
        }
    )
    # 3) A conversation message carrying a LEGACY tool field (weather_data) that
    #    convert_legacy_tool_data must fold into a tool_data array.
    await conversations.insert_one(
        {
            "user_id": user_id,
            "conversation_id": conv_legacy_id,
            "description": "unrelated",
            "messages": [
                {
                    "type": "bot",
                    "response": "Here is the photosynthesis report you asked for.",
                    "weather_data": {"temp": 21, "city": "Pune"},
                }
            ],
        }
    )
    # 4) A conversation with a KNOWN LONG response for the exact-snippet assertion.
    await conversations.insert_one(
        {
            "user_id": user_id,
            "conversation_id": conv_long_id,
            "description": "unrelated",
            "messages": [{"type": "bot", "response": LONG_RESPONSE}],
        }
    )
    # 5) A note whose plaintext matches (mixed case). The match sits well past
    #    30 chars in so the chars_before snippet window is observable. An
    #    explicit _id lets the test pin the serialized id value.
    note_oid = ObjectId()
    await notes.insert_one(
        {
            "_id": note_oid,
            "user_id": user_id,
            "note_id": note_match_id,
            "plaintext": NOTE_PLAINTEXT,
        }
    )

    # --- Other user data (must NEVER surface for the target user) --------
    await conversations.insert_one(
        {
            "user_id": other_user_id,
            "conversation_id": other_conv_id,
            "description": "Other user's PHOTOSYNTHESIS notes and message.",
            "messages": [{"type": "bot", "response": "Secret photosynthesis data for other user."}],
        }
    )
    await notes.insert_one(
        {
            "user_id": other_user_id,
            "note_id": other_note_id,
            "plaintext": "Other user private photosynthesis note.",
        }
    )

    monkeypatch.setattr("app.services.search_service.conversations_collection", conversations)
    monkeypatch.setattr("app.services.search_service.notes_collection", notes)

    recorder = _LogRecorder()
    monkeypatch.setattr("app.services.search_service.log", recorder)

    try:
        yield {
            "user_id": user_id,
            "other_user_id": other_user_id,
            "conversations": conversations,
            "notes": notes,
            "recorder": recorder,
            "conv_match_id": conv_match_id,
            "conv_desc_id": conv_desc_id,
            "conv_long_id": conv_long_id,
            "note_match_id": note_match_id,
            "note_oid": note_oid,
        }
    finally:
        await conversations.delete_many({"user_id": {"$in": seeded_user_ids}})
        await notes.delete_many({"user_id": {"$in": seeded_user_ids}})
        client.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.service
class TestSearchMessagesReal:
    async def test_returns_exact_keys_and_counts(self, search_env):
        """Exactly {messages, conversations, notes} with the right counts.

        Target user has: 2 message matches (conv_match + conv_legacy + conv_long
        -> 3 messages whose response contains the query), 1 description match,
        1 note match. Kills return-key, facet-key, and $project mutants.
        """
        result = await search_messages(QUERY, search_env["user_id"])

        assert set(result.keys()) == {"messages", "conversations", "notes"}

        # message matches: conv_match (1 of 2 messages), conv_legacy (1), conv_long (1)
        assert len(result["messages"]) == 3
        assert len(result["conversations"]) == 1
        assert len(result["notes"]) == 1

        # The conversation match is the description-matching one, not the others.
        conv = result["conversations"][0]
        assert conv["conversation_id"] == search_env["conv_desc_id"]
        assert conv["description"].lower().count("photosynthesis") == 1

        # Projection shape contract. The message facet projects away _id
        # (kills the messages $project "_id": 0 -> 1 mutant) and exposes exactly
        # conversation_id + message. The conversation facet projects away _id
        # (kills the conversations $project "_id": 0 -> 1 mutant) and — because
        # the seeded docs have no "conversations" field — never includes a
        # "conversation" key (kills the "$conversations" str -> '' mutant, which
        # would inject conversation="" into every row).
        for msg in result["messages"]:
            assert "_id" not in msg
            # conversation_id + message from the projection, plus the snippet
            # the service adds afterwards.
            assert set(msg.keys()) == {"conversation_id", "message", "snippet"}
        assert "_id" not in conv
        assert "conversation" not in conv
        assert set(conv.keys()) == {"conversation_id", "description"}

    async def test_case_insensitive_matching(self, search_env):
        """Lowercase query matches mixed-case stored text across all three sources.

        Kills the $options "i" removal and $regex-field mutants: without
        case-insensitive regex matching on the right fields, none of these
        mixed-case documents would match a lowercase query.
        """
        result = await search_messages(QUERY, search_env["user_id"])

        message_responses = [m["message"]["response"] for m in result["messages"]]
        assert any("PhotoSynthesis" in r for r in message_responses)

        assert result["conversations"][0]["description"] == (
            "A deep dive into PHOTOSYNTHESIS and plant biology."
        )

        assert len(result["notes"]) == 1
        assert "PhotoSynthesis" in result["notes"][0]["plaintext"]

    async def test_cross_user_isolation(self, search_env):
        """The other user's matching data is never returned.

        Kills the $match {user_id} mutant on both the conversations aggregate
        and the notes aggregate: dropping the user filter would surface the
        other user's documents.
        """
        result = await search_messages(QUERY, search_env["user_id"])

        all_message_text = " ".join(m["message"]["response"] for m in result["messages"])
        all_conv_text = " ".join(c["description"] for c in result["conversations"])
        all_note_text = " ".join(n["plaintext"] for n in result["notes"])

        assert "other user" not in all_message_text.lower()
        assert "other user" not in all_conv_text.lower()
        assert "other user" not in all_note_text.lower()

        # And the inverse: searching as the other user yields only their data.
        other_result = await search_messages(QUERY, search_env["other_user_id"])
        assert len(other_result["conversations"]) == 1
        assert "Other user" in other_result["conversations"][0]["description"]
        assert len(other_result["notes"]) == 1
        assert len(other_result["messages"]) == 1

    async def test_exact_snippet_for_known_long_response(self, search_env):
        """The snippet for the known long response equals the pinned value.

        Kills the chars_before 30->31 const mutation on the MESSAGE snippet:
        a one-char change shifts the leading context window and breaks the
        exact-string match.
        """
        result = await search_messages(QUERY, search_env["user_id"])

        long_msg = next(
            m for m in result["messages"] if m["conversation_id"] == search_env["conv_long_id"]
        )
        assert long_msg["snippet"] == EXPECTED_SNIPPET

    async def test_note_snippet_exact_and_serialized_id(self, search_env):
        """Note is serialized (_id -> id) and carries the exact snippet.

        Kills the chars_before 30->31 const mutation on the NOTE snippet, the
        serialize_document wiring, and the notes $project {"$toString": "$_id"}
        field-path mutant (which would surface id="" instead of the real id).
        """
        result = await search_messages(QUERY, search_env["user_id"])

        note = result["notes"][0]
        assert "_id" not in note
        # id must be the real ObjectId string — not "" (the $_id->'' mutant).
        assert note["id"] == str(search_env["note_oid"])
        assert note["note_id"] == search_env["note_match_id"]
        assert note["snippet"] == EXPECTED_NOTE_SNIPPET

    async def test_legacy_tool_field_converted(self, search_env):
        """A legacy weather_data field becomes a unified tool_data entry.

        Kills the convert_legacy_tool_data wiring: without it the message would
        retain the raw weather_data field and have no tool_data array.
        """
        result = await search_messages(QUERY, search_env["user_id"])

        legacy_messages = [
            m
            for m in result["messages"]
            if "tool_data" in m["message"]
            and any(e["tool_name"] == "weather_data" for e in m["message"]["tool_data"])
        ]
        assert len(legacy_messages) == 1
        converted = legacy_messages[0]["message"]
        assert "weather_data" not in converted  # legacy field removed
        entry = next(e for e in converted["tool_data"] if e["tool_name"] == "weather_data")
        assert entry["data"] == {"temp": 21, "city": "Pune"}

    async def test_emits_structured_log_fields(self, search_env):
        """The wide-event log carries the search contract fields.

        Kills the logging-string mutants in BOTH log.set calls and the
        result_count arithmetic mutant. The first (pre-search) log.set and the
        second (post-search) log.set re-emit the same ``search`` dict, so the
        first call's string mutations are only observable when each call is
        asserted independently — the merged view alone would mask them.
        """
        recorder: _LogRecorder = search_env["recorder"]

        await search_messages(QUERY, search_env["user_id"])

        # Two set() calls: pre-search context, then post-search results.
        assert len(recorder.calls) == 2
        first, second = recorder.calls

        # First call: identifying context + base search descriptor.
        assert first["user_id"] == search_env["user_id"]
        assert first["service"] == "search_service"
        assert first["search"]["query"] == QUERY
        assert first["search"]["query_length"] == len(QUERY)
        assert first["search"]["search_type"] == "keyword"
        assert first["search"]["sources"] == ["messages", "conversations", "notes"]

        # Second call: same descriptor plus the computed counts/duration.
        second_search = second["search"]
        assert second_search["query"] == QUERY
        assert second_search["query_length"] == len(QUERY)
        assert second_search["search_type"] == "keyword"
        assert second_search["sources"] == ["messages", "conversations", "notes"]
        # 3 messages + 1 conversation + 1 note = 5 (kills result_count Add->Sub).
        assert second_search["result_count"] == 5
        assert "duration_ms" in second_search

    async def test_no_match_returns_empty_lists(self, search_env):
        """A query that matches nothing yields empty lists for all sources."""
        result = await search_messages("zzqqxxnomatch", search_env["user_id"])

        assert result["messages"] == []
        assert result["conversations"] == []
        assert result["notes"] == []

    async def test_aggregate_failure_raises_http_500(self, search_env):
        """A failing conversations.aggregate becomes HTTPException(500).

        Kills the error-string and status-code mutants. We patch only the I/O
        boundary (the collection's aggregate) to raise.
        """
        recorder: _LogRecorder = search_env["recorder"]

        with patch.object(
            search_env["conversations"],
            "aggregate",
            side_effect=RuntimeError("mongo exploded"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await search_messages(QUERY, search_env["user_id"])

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail.startswith("Failed to perform search:")
        assert "mongo exploded" in exc_info.value.detail
        # The failure was logged via log.error.
        assert any("Error in search_messages" in e for e in recorder.errors)
