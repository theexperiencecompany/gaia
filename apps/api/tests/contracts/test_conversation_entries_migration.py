"""The entries migration against real Mongo: copy, re-run, second pass, verify, drop and rollback."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
import uuid

from bson import ObjectId
import pytest

from app.db.repositories.conversation_entries_migration import (
    ConversationEntriesMigration,
    HeadRef,
    MigrationAction,
)
from app.db.repositories.conversations import ConversationRepository
from app.models.chat_models import MessageModel, MessageReaction, ReactionBy
from app.utils.errors import UnmigratedConversationError

pytestmark = pytest.mark.usefixtures("entries_collection")

USER = "u-migrate"


@pytest.fixture
def migration(raw_collection: Any) -> ConversationEntriesMigration:
    return ConversationEntriesMigration()


def _message(n: int, role: str = "user", **fields: object) -> dict[str, object]:
    return {
        "type": role,
        "response": f"message {n}",
        "message_id": f"m{n}",
        "date": datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
        **fields,
    }


async def _legacy(
    raw_collection: Any, messages: list[dict[str, object]], **fields: object
) -> HeadRef:
    """Insert a conversation the way the old build stored it: its messages embedded in the head."""
    conversation_id = f"c-{uuid.uuid4().hex}"
    result = await raw_collection.insert_one(
        {
            "conversation_id": conversation_id,
            "user_id": USER,
            "description": "legacy",
            "createdAt": datetime.now(UTC).isoformat(),
            "updatedAt": datetime.now(UTC),
            "messages": messages,
            **fields,
        }
    )
    return HeadRef(str(result.inserted_id), conversation_id, USER)


async def _read_ids(ref: HeadRef) -> list[str]:
    doc = await ConversationRepository().get(ref.conversation_id, user_id=ref.user_id)
    assert doc is not None
    return [str(m.message_id) for m in doc.messages]


async def test_every_shape_of_history_is_copied_in_order_and_verifies(
    migration: ConversationEntriesMigration, raw_collection: Any
) -> None:
    big_card = {"tool_name": "search_results", "data": {"blob": "x" * 2_000_000}}
    fixtures = {
        "one": [_message(1)],
        "large tool_data": [_message(1, "bot", tool_data=[big_card])],
        "pinned": [_message(1), _message(2, "bot", pinned=True), _message(3)],
        "over the old cap": [_message(n) for n in range(1, 702)],
    }
    refs = {name: await _legacy(raw_collection, messages) for name, messages in fixtures.items()}

    for name, ref in refs.items():
        dry = await migration.migrate(ref, apply=False)
        assert (dry.action, dry.copied) == (MigrationAction.COPIED, len(fixtures[name]))
        with pytest.raises(UnmigratedConversationError, match="migrate_conversation_entries"):
            await _read_ids(ref)
        done = await migration.migrate(ref, apply=True)
        assert done.action is MigrationAction.COPIED

    for name, ref in refs.items():
        expected = [str(m["message_id"]) for m in fixtures[name]]
        assert await _read_ids(ref) == expected, name
        report = await migration.verify(ref)
        assert report.ok, report.mismatches
        assert report.entries == report.embedded == len(expected)

    pinned = await ConversationRepository().list_pinned_messages(USER)
    assert [(h.conversation_id, h.message.message_id) for h in pinned] == [
        (refs["pinned"].conversation_id, "m2")
    ]
    large = await ConversationRepository().get_message(
        refs["large tool_data"].conversation_id, "m1", user_id=USER
    )
    assert large is not None and large.tool_data == [big_card]


async def test_a_rerun_skips_what_it_already_migrated(
    migration: ConversationEntriesMigration, raw_collection: Any, entries_collection: Any
) -> None:
    ref = await _legacy(raw_collection, [_message(1), _message(2)])
    await migration.migrate(ref, apply=True)

    again = await migration.migrate(ref, apply=True)

    assert again.action is MigrationAction.UNCHANGED
    assert await entries_collection.count_documents({}) == 2


async def test_an_empty_conversation_is_never_a_candidate_and_reads_empty(
    migration: ConversationEntriesMigration, raw_collection: Any
) -> None:
    ref = await _legacy(raw_collection, [])

    assert await migration.heads_with_embedded(after_head_id=None, since=None, batch=10) == []
    assert await _read_ids(ref) == []


async def test_the_second_pass_merges_what_the_old_build_wrote_after_the_first(
    migration: ConversationEntriesMigration, raw_collection: Any
) -> None:
    ref = await _legacy(raw_collection, [_message(1), _message(2)])
    await migration.migrate(ref, apply=True)
    first_pass = datetime.now(UTC)
    # The old build, still serving: settles m2's text in place and appends m3 (trimming m1 off).
    await raw_collection.update_one(
        {"_id": ObjectId(ref.head_id)},
        {
            "$set": {
                "messages": [_message(2, response="settled"), _message(3)],
                "updatedAt": datetime.now(UTC),
            }
        },
    )
    with pytest.raises(UnmigratedConversationError, match="migrate_conversation_entries"):
        await _read_ids(ref)
    assert not (await migration.verify(ref)).ok

    [candidate] = await migration.heads_with_embedded(
        after_head_id=None, since=first_pass, batch=10
    )
    merged = await migration.migrate(candidate, apply=True)

    assert (merged.action, merged.copied, merged.rewritten) == (MigrationAction.MERGED, 1, 1)
    assert await _read_ids(ref) == ["m1", "m2", "m3"]
    settled = await ConversationRepository().get_message(ref.conversation_id, "m2", user_id=USER)
    assert settled is not None and settled.response == "settled"
    report = await migration.verify(ref)
    assert report.ok, report.mismatches
    assert (report.embedded, report.entries) == (2, 3)


async def test_legacy_elements_without_ids_get_stable_ids_and_repeated_ids_are_refused(
    migration: ConversationEntriesMigration, raw_collection: Any
) -> None:
    unnamed = await _legacy(raw_collection, [{"type": "user", "response": "old"}, _message(2)])
    repeated = await _legacy(raw_collection, [_message(1), _message(1)])

    assert (await migration.migrate(unnamed, apply=True)).action is MigrationAction.COPIED
    refused = await migration.migrate(repeated, apply=True)

    assert await _read_ids(unnamed) == ["legacy-1", "m2"]
    assert (await migration.verify(unnamed)).ok
    assert refused.action is MigrationAction.REFUSED and "m1" in refused.reason
    assert not (await migration.verify(repeated)).ok


async def test_drop_needs_a_passing_verify_and_rebuild_restores_the_array(
    migration: ConversationEntriesMigration, raw_collection: Any, entries_collection: Any
) -> None:
    elements = [_message(1), _message(2, "bot", pinned=True)]
    ref = await _legacy(raw_collection, elements)
    unmigrated = await _legacy(raw_collection, [_message(9)])
    await migration.migrate(ref, apply=True)

    assert not await migration.drop_embedded(unmigrated)
    assert await migration.drop_embedded(ref)
    head = await raw_collection.find_one({"_id": ObjectId(ref.head_id)})
    assert "messages" not in head
    await ConversationRepository().append_messages(
        ref.conversation_id,
        user_id=USER,
        messages=[MessageModel(type="user", response="after", message_id="m3")],
    )

    [dropped] = await migration.heads_without_embedded(after_head_id=None, batch=10)
    assert await migration.rebuild_embedded(dropped, apply=True) == 3

    head = await raw_collection.find_one({"_id": ObjectId(ref.head_id)})
    assert [m.get("message_id") for m in head["messages"]] == ["m1", "m2", "m3"]
    assert head["messages"][:2] == elements
    assert "log_head" not in head
    assert await entries_collection.count_documents({"conversation_id": ref.conversation_id}) == 0


async def _old_hits(raw_collection: Any, match: dict[str, object]) -> set[tuple[str, str]]:
    """Run the pre-migration query shape: unwind each embedded array and match its messages."""
    rows = await raw_collection.aggregate(
        [
            {"$match": {"user_id": USER}},
            {"$unwind": "$messages"},
            {"$match": {f"messages.{k}": v for k, v in match.items()}},
        ]
    ).to_list(None)
    return {(row["conversation_id"], row["messages"]["message_id"]) for row in rows}


async def test_cross_conversation_reads_match_the_embedded_queries_they_replace(
    migration: ConversationEntriesMigration, raw_collection: Any
) -> None:
    refs = [
        await _legacy(raw_collection, [_message(1), _message(2, "bot", pinned=True)]),
        await _legacy(raw_collection, [_message(3, "bot", response="needle here")]),
        await _legacy(raw_collection, [_message(4, "bot", pinned=True, response="a Needle")]),
    ]
    old_pinned = await _old_hits(raw_collection, {"pinned": True})
    old_search = await _old_hits(
        raw_collection, {"response": {"$regex": "needle", "$options": "i"}}
    )
    old_owner = await _old_hits(raw_collection, {"message_id": "m3", "type": "bot"})
    for ref in refs:
        await migration.migrate(ref, apply=True)
    repo = ConversationRepository()

    pins = await repo.list_pinned_messages(USER)
    found = await repo.search(USER, pattern="needle")

    assert {(h.conversation_id, h.message.message_id) for h in pins} == old_pinned
    assert len(old_pinned) == 2
    assert {(h.conversation_id, h.message.message_id) for h in found.messages} == old_search
    assert len(old_search) == 2
    assert {(str(await repo.find_owner_of_message(USER, "m3")), "m3")} == old_owner
    assert await repo.has_sent_message(USER) is True


CARD = {"tool_name": "calendar_events", "data": {"events": []}}
THUMBS_UP = MessageReaction(emoji="\U0001f44d", by=ReactionBy.CHAT_MODEL)


def _ack(n: int, target: str, **fields: object) -> dict[str, object]:
    return _message(
        n, "bot", response="\U0001f44d", kind="emoji_ack", reacts_to_message_id=target, **fields
    )


async def _stored(ref: HeadRef, message_id: str) -> MessageModel | None:
    return await ConversationRepository().get_message(
        ref.conversation_id, message_id, user_id=ref.user_id
    )


async def test_an_ack_without_cards_becomes_the_reaction_on_its_message_and_is_removed(
    migration: ConversationEntriesMigration, raw_collection: Any
) -> None:
    ref = await _legacy(raw_collection, [_message(1), _ack(2, "m1"), _message(3)])

    done = await migration.migrate(ref, apply=True)

    assert done.folded == 1
    assert await _read_ids(ref) == ["m1", "m3"]
    target = await _stored(ref, "m1")
    assert target is not None and target.reaction == THUMBS_UP
    assert (await migration.verify(ref)).ok


async def test_an_ack_with_cards_stays_as_a_cards_only_message(
    migration: ConversationEntriesMigration, raw_collection: Any
) -> None:
    ref = await _legacy(raw_collection, [_message(1), _ack(2, "m1", tool_data=[CARD])])

    await migration.migrate(ref, apply=True)

    assert await _read_ids(ref) == ["m1", "m2"]
    cards = await _stored(ref, "m2")
    assert cards is not None
    assert (cards.response, cards.tool_data) == ("", [CARD])
    target = await _stored(ref, "m1")
    assert target is not None and target.reaction == THUMBS_UP
    assert (await migration.verify(ref)).ok


async def test_an_ack_whose_message_is_gone_is_kept_as_a_plain_text_message(
    migration: ConversationEntriesMigration, raw_collection: Any, entries_collection: Any
) -> None:
    ref = await _legacy(raw_collection, [_message(1), _ack(2, "trimmed-off")])

    await migration.migrate(ref, apply=True)

    assert await _read_ids(ref) == ["m1", "m2"]
    kept = await entries_collection.find_one({"conversation_id": ref.conversation_id, "id": "m2"})
    assert kept["response"] == "\U0001f44d"
    assert "kind" not in kept and "reacts_to_message_id" not in kept
    target = await _stored(ref, "m1")
    assert target is not None and target.reaction is None
    assert (await migration.verify(ref)).ok


async def test_folding_is_a_dry_run_unless_applied_and_a_rerun_changes_nothing(
    migration: ConversationEntriesMigration, raw_collection: Any, entries_collection: Any
) -> None:
    ref = await _legacy(raw_collection, [_message(1), _ack(2, "m1")])

    dry = await migration.migrate(ref, apply=False)
    assert dry.folded == 1
    assert await entries_collection.count_documents({"conversation_id": ref.conversation_id}) == 0

    await migration.migrate(ref, apply=True)
    again = await migration.migrate(ref, apply=True)

    assert (again.action, again.copied, again.folded) == (MigrationAction.UNCHANGED, 0, 0)
    assert await _read_ids(ref) == ["m1"]


async def test_an_ack_the_old_build_wrote_after_the_first_pass_is_folded_by_the_second(
    migration: ConversationEntriesMigration, raw_collection: Any
) -> None:
    ref = await _legacy(raw_collection, [_message(1)])
    await migration.migrate(ref, apply=True)
    await raw_collection.update_one(
        {"_id": ObjectId(ref.head_id)},
        {"$set": {"messages": [_message(1), _ack(2, "m1")], "updatedAt": datetime.now(UTC)}},
    )

    merged = await migration.migrate(ref, apply=True)

    assert merged.folded == 1
    assert await _read_ids(ref) == ["m1"]
    target = await _stored(ref, "m1")
    assert target is not None and target.reaction == THUMBS_UP
    assert (await migration.verify(ref)).ok


async def test_verify_fails_while_an_ack_is_still_a_message(
    migration: ConversationEntriesMigration, raw_collection: Any, entries_collection: Any
) -> None:
    ref = await _legacy(raw_collection, [_message(1), _message(2, "bot")])
    await migration.migrate(ref, apply=True)
    # What a pass of the build before folding left behind: the ack copied as an ordinary entry.
    await entries_collection.update_one(
        {"conversation_id": ref.conversation_id, "id": "m2"},
        {"$set": {"kind": "emoji_ack", "reacts_to_message_id": "m1", "response": "x"}},
    )

    report = await migration.verify(ref)

    assert not report.ok
    assert any("m2" in mismatch for mismatch in report.mismatches)
