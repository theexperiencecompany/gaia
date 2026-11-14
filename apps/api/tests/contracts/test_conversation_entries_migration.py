"""The entries migration against real Mongo: copy, re-run, second pass, verify, drop and rollback."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
import uuid

from bson import ObjectId
import pytest

from app.db.repositories.conversation_entries_migration import (
    ConversationEntriesMigration,
    HeadRef,
    MigrationAction,
    MigrationOutcome,
    VerifyReport,
    _changed_fields,
    conversation_entries_migration,
    entry_at,
    field_hashes,
)
from app.db.repositories.conversations import ConversationRepository
from app.models.chat_models import MessageModel, MessageReaction, ReactionBy
from app.models.conversation_models import LegacyMessage, StoredEntry
from app.scripts import migrate_conversation_entries as script
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
    """Read every entry's id, oldest first, past the window a whole-conversation get returns."""
    assert await ConversationRepository().exists(ref.conversation_id, user_id=ref.user_id)
    entries = await ConversationRepository()._read_entries(ref.conversation_id, user_id=ref.user_id)
    return [str(entry.message_id) for entry in entries]


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

    assert await migration.heads_to_migrate(after_head_id=None, batch=10) == []
    assert await _read_ids(ref) == []


async def test_the_second_pass_merges_what_the_old_build_wrote_after_the_first(
    migration: ConversationEntriesMigration, raw_collection: Any
) -> None:
    ref = await _legacy(raw_collection, [_message(1), _message(2)])
    await migration.migrate(ref, apply=True)
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
    assert (await migration.verify(ref)).mismatches == [
        "written by the old build since its last pass: run --apply",
        "m2 differs from its entry",
        "m3 has no entry",
    ]

    [candidate] = await migration.heads_to_migrate(after_head_id=None, batch=10)
    merged = await migration.migrate(candidate, apply=True)

    assert (merged.action, merged.copied, merged.rewritten) == (MigrationAction.MERGED, 1, 1)
    assert await _read_ids(ref) == ["m1", "m2", "m3"]
    settled = await ConversationRepository().get_message(ref.conversation_id, "m2", user_id=USER)
    assert settled is not None and settled.response == "settled"
    report = await migration.verify(ref)
    assert report.ok, report.mismatches
    assert (report.embedded, report.entries) == (2, 3)


async def test_the_second_pass_merges_old_build_writes_into_a_conversation_the_new_build_created(
    migration: ConversationEntriesMigration, raw_collection: Any
) -> None:
    ref = await _legacy(raw_collection, [], log_head=0)
    await raw_collection.update_one(
        {"_id": ObjectId(ref.head_id)},
        {"$push": {"messages": {"$each": [_message(1), _message(2)]}}},
    )

    merged = await migration.migrate(ref, apply=True)

    assert (merged.action, merged.copied) == (MigrationAction.MERGED, 2)
    assert await _read_ids(ref) == ["m1", "m2"]


async def test_drop_needs_the_fingerprint_a_passing_verify_took_and_appends_then_read_on(
    migration: ConversationEntriesMigration, raw_collection: Any, entries_collection: Any
) -> None:
    elements = [_message(1), _message(2, "bot", pinned=True)]
    ref = await _legacy(raw_collection, elements)
    unmigrated = await _legacy(raw_collection, [_message(9)])
    kept = await _legacy(raw_collection, [_message(8)])
    await migration.migrate(ref, apply=True)
    await migration.migrate(kept, apply=True)

    assert (await migration.verify(unmigrated)).fingerprint is None
    verified = (await migration.verify(ref)).fingerprint
    assert verified is not None
    assert not await migration.drop_embedded(ref, verified=verified + 1)
    assert await migration.drop_embedded(ref, verified=verified)
    head = await raw_collection.find_one({"_id": ObjectId(ref.head_id)})
    assert "messages" not in head
    await ConversationRepository().append_messages(
        ref.conversation_id,
        user_id=USER,
        messages=[MessageModel(type="user", response="after", message_id="m3")],
    )

    assert await _read_ids(ref) == ["m1", "m2", "m3"]
    assert "messages" in await raw_collection.find_one(_head(kept))


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


async def test_a_first_pass_that_died_before_marking_is_redone_from_the_array_as_it_is_now(
    migration: ConversationEntriesMigration, raw_collection: Any, entries_collection: Any
) -> None:
    ref = await _legacy(raw_collection, [_message(1), _message(2)])
    await migration.migrate(ref, apply=True)
    # The pass died after writing entries and before marking; the old build then trimmed m1 and appended m3.
    await raw_collection.update_one(
        {"_id": ObjectId(ref.head_id)},
        {
            "$unset": {"log_head": "", "migrated_fingerprint": ""},
            "$set": {"messages": [_message(2), _message(3)]},
        },
    )

    redone = await migration.migrate(ref, apply=True)

    assert (redone.action, redone.copied) == (MigrationAction.COPIED, 2)
    assert await _read_ids(ref) == ["m2", "m3"]
    assert await entries_collection.count_documents({"conversation_id": ref.conversation_id}) == 2
    assert (await migration.verify(ref)).ok


def _after_the_read(
    monkeypatch: pytest.MonkeyPatch,
    migration: ConversationEntriesMigration,
    write: Callable[[], Awaitable[object]],
    read: str = "_embedded_head",
) -> None:
    """Let write land right after the pass's next read (its head by default), which still returns what it saw."""
    real = getattr(migration, read)

    async def read_then_write(ref: HeadRef) -> object:
        monkeypatch.setattr(migration, read, real)
        seen = await real(ref)
        await write()
        return seen

    monkeypatch.setattr(migration, read, read_then_write)


def _head(ref: HeadRef) -> dict[str, object]:
    return {"_id": ObjectId(ref.head_id)}


async def _move_to_outbox(
    raw_collection: Any, entries_collection: Any, ref: HeadRef, id_: str
) -> None:
    """Put a copied entry back where a commit that has not flushed yet leaves it: the head's outbox."""
    entry = await entries_collection.find_one_and_delete(
        {"conversation_id": ref.conversation_id, "id": id_}, projection={"_id": 0}
    )
    await raw_collection.update_one(_head(ref), {"$set": {f"outbox.{entry['seq']}": entry}})


def test_an_element_hashes_the_same_whatever_its_key_order_and_a_date_hashes_as_its_text() -> None:
    at = datetime(2026, 1, 1, tzinfo=UTC)

    assert field_hashes({"a": 1, "b": at}) == field_hashes({"b": at, "a": 1})
    assert field_hashes({"a": 1, "b": at}) == field_hashes({"a": 1, "b": str(at)})
    assert field_hashes({"a": 1}) != field_hashes({"a": 2})
    assert field_hashes({"a": {"x": 1, "y": 2}}) == field_hashes({"a": {"y": 2, "x": 1}})
    assert set(field_hashes({"a": 1, "message_id": "m"})) == {"a"}


def test_a_legacy_element_is_stored_with_only_the_fields_it_holds() -> None:
    element = LegacyMessage.model_validate({"type": "bot", "response": "hi"})

    assert element.stored() == {"type": "bot", "response": "hi"}


def test_an_entry_is_dated_by_its_element_and_a_naive_or_missing_date_reads_as_utc() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    assert entry_at("2026-01-02T03:04:05+05:30") == datetime(2026, 1, 2, 3, 4, 5, tzinfo=ist)
    naive = entry_at("2026-01-02T03:04:05")
    assert naive.tzinfo is UTC
    assert naive == datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    before = datetime.now(UTC)
    for undated in (None, "not a date", 5):
        stamped = entry_at(undated)
        assert stamped.tzinfo is UTC
        assert before <= stamped <= datetime.now(UTC)


async def test_a_copied_entry_is_its_element_keyed_by_seq_and_id_and_dated_by_it(
    migration: ConversationEntriesMigration, raw_collection: Any, entries_collection: Any
) -> None:
    ref = await _legacy(raw_collection, [_message(1)])

    assert await migration.migrate(ref, apply=True) == MigrationOutcome(
        ref.conversation_id, MigrationAction.COPIED, copied=1
    )

    [entry] = await entries_collection.find({}, {"_id": 0}).to_list(None)
    assert entry == {
        "type": "user",
        "response": "message 1",
        "date": datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
        "conversation_id": ref.conversation_id,
        "user_id": USER,
        "seq": 1,
        "id": "m1",
        "at": datetime(2026, 1, 1, tzinfo=UTC),
        "migration_fields": field_hashes(_message(1)),
    }


async def test_scans_walk_every_head_in_id_order_one_batch_at_a_time(
    migration: ConversationEntriesMigration, raw_collection: Any
) -> None:
    refs = [await _legacy(raw_collection, [_message(n)]) for n in (1, 2, 3)]

    async def walk(scan: Callable[[str | None], Awaitable[list[HeadRef]]]) -> list[HeadRef]:
        seen: list[HeadRef] = []
        after: str | None = None
        while batch := await scan(after):
            assert len(batch) == 1
            seen += batch
            after = batch[-1].head_id
        return seen

    assert (
        await walk(lambda after: migration.heads_with_embedded(after_head_id=after, batch=1))
        == refs
    )
    assert (
        await walk(lambda after: migration.heads_to_migrate(after_head_id=after, batch=1)) == refs
    )
    for ref in refs:
        await migration.migrate(ref, apply=True)
    # Only a head the old build wrote since its pass is a candidate again.
    await raw_collection.update_one(_head(refs[1]), {"$set": {"messages.0.response": "edited"}})
    assert await migration.heads_to_migrate(after_head_id=None, batch=9) == [refs[1]]
    assert (
        await walk(lambda after: migration.heads_with_embedded(after_head_id=after, batch=1))
        == refs
    )


async def test_a_first_pass_racing_an_old_build_write_marks_nothing_and_the_rerun_copies_it(
    monkeypatch: pytest.MonkeyPatch, migration: ConversationEntriesMigration, raw_collection: Any
) -> None:
    ref = await _legacy(raw_collection, [_message(1)])
    _after_the_read(
        monkeypatch,
        migration,
        lambda: raw_collection.update_one(_head(ref), {"$push": {"messages": _message(2)}}),
    )

    assert await migration.migrate(ref, apply=True) == MigrationOutcome(
        ref.conversation_id, MigrationAction.RACED
    )
    head = await raw_collection.find_one(_head(ref))
    assert "log_head" not in head
    assert (await migration.migrate(ref, apply=True)).action is MigrationAction.COPIED
    assert await _read_ids(ref) == ["m1", "m2"]


async def test_verify_names_every_corruption_of_the_copied_entries(
    migration: ConversationEntriesMigration, raw_collection: Any, entries_collection: Any
) -> None:
    ref = await _legacy(raw_collection, [_message(n) for n in range(1, 6)])
    unmigrated = await _legacy(raw_collection, [_message(9)])
    await migration.migrate(ref, apply=True)
    of = {"conversation_id": ref.conversation_id}
    await entries_collection.delete_many({**of, "id": {"$in": ["m1", "m2"]}})
    await entries_collection.update_one({**of, "id": "m3"}, {"$set": {"seq": 99}})
    await entries_collection.update_one(
        {**of, "id": "m4"}, {"$set": {"migration_fields": field_hashes(_message(5))}}
    )

    corrupted = await migration.verify(ref)
    assert (corrupted.embedded, corrupted.entries, corrupted.mismatches) == (
        5,
        3,
        [
            "m1 has no entry",
            "m2 has no entry",
            "m4 differs from its entry",
            "the entries are not in the embedded array's order",
        ],
    )
    assert await migration.verify(unmigrated) == VerifyReport(
        unmigrated.conversation_id,
        embedded=1,
        entries=0,
        mismatches=["not migrated: no log_head"],
    )


async def test_an_entry_still_in_the_outbox_counts_as_copied_for_verify_and_the_second_pass(
    migration: ConversationEntriesMigration, raw_collection: Any, entries_collection: Any
) -> None:
    ref = await _legacy(raw_collection, [_message(1), _message(2)])
    await migration.migrate(ref, apply=True)
    await _move_to_outbox(raw_collection, entries_collection, ref, "m2")

    assert (await migration.verify(ref)).ok

    await _move_to_outbox(raw_collection, entries_collection, ref, "m2")
    await raw_collection.update_one(_head(ref), {"$push": {"messages": _message(3)}})
    assert await migration.migrate(ref, apply=True) == MigrationOutcome(
        ref.conversation_id, MigrationAction.MERGED, copied=1
    )
    assert await entries_collection.count_documents({"conversation_id": ref.conversation_id}) == 3
    assert not (await raw_collection.find_one(_head(ref))).get("outbox")
    assert await _read_ids(ref) == ["m1", "m2", "m3"]


async def test_a_second_pass_remarks_a_head_the_old_build_only_trimmed(
    migration: ConversationEntriesMigration, raw_collection: Any
) -> None:
    ref = await _legacy(raw_collection, [_message(1), _message(2)])
    await migration.migrate(ref, apply=True)
    await raw_collection.update_one(_head(ref), {"$pop": {"messages": 1}})
    merged = MigrationOutcome(ref.conversation_id, MigrationAction.MERGED)

    assert await migration.migrate(ref, apply=False) == merged
    assert await migration.migrate(ref, apply=True) == merged
    assert await migration.migrate(ref, apply=True) == MigrationOutcome(
        ref.conversation_id, MigrationAction.UNCHANGED
    )
    assert (await migration.verify(ref)).ok
    assert await _read_ids(ref) == ["m1", "m2"]


async def test_a_second_pass_the_old_build_writes_under_is_raced_and_the_next_pass_finishes(
    monkeypatch: pytest.MonkeyPatch, migration: ConversationEntriesMigration, raw_collection: Any
) -> None:
    ref = await _legacy(raw_collection, [_message(1)])
    await migration.migrate(ref, apply=True)
    await raw_collection.update_one(_head(ref), {"$push": {"messages": _message(2)}})
    _after_the_read(
        monkeypatch,
        migration,
        lambda: raw_collection.update_one(_head(ref), {"$push": {"messages": _message(3)}}),
    )

    assert await migration.migrate(ref, apply=True) == MigrationOutcome(
        ref.conversation_id, MigrationAction.RACED
    )
    with pytest.raises(UnmigratedConversationError):
        await _read_ids(ref)
    assert await migration.migrate(ref, apply=True) == MigrationOutcome(
        ref.conversation_id, MigrationAction.MERGED, copied=1
    )
    assert await _read_ids(ref) == ["m1", "m2", "m3"]


async def test_a_second_pass_that_loses_the_commit_to_another_pass_is_raced_and_copies_once(
    monkeypatch: pytest.MonkeyPatch, migration: ConversationEntriesMigration, raw_collection: Any
) -> None:
    ref = await _legacy(raw_collection, [_message(1)])
    await migration.migrate(ref, apply=True)
    await raw_collection.update_one(_head(ref), {"$push": {"messages": _message(2)}})
    _after_the_read(
        monkeypatch,
        migration,
        lambda: ConversationEntriesMigration().migrate(ref, apply=True),
        read="_stored",
    )

    assert await migration.migrate(ref, apply=True) == MigrationOutcome(
        ref.conversation_id, MigrationAction.RACED
    )
    assert await _read_ids(ref) == ["m1", "m2"]


async def test_drop_refuses_a_head_written_after_its_verify_and_drops_only_once(
    migration: ConversationEntriesMigration, raw_collection: Any
) -> None:
    ref = await _legacy(raw_collection, [_message(1)])
    await migration.migrate(ref, apply=True)
    real_verify = migration.verify

    async def verified_then_written(verified: HeadRef) -> VerifyReport:
        report = await real_verify(verified)
        await raw_collection.update_one(_head(ref), {"$push": {"messages": _message(2)}})
        return report

    report = await verified_then_written(ref)
    assert report.ok and report.fingerprint is not None
    assert not await migration.drop_embedded(ref, verified=report.fingerprint)

    head = await raw_collection.find_one(_head(ref))
    assert [m["message_id"] for m in head["messages"]] == ["m1", "m2"]
    await migration.migrate(ref, apply=True)
    again = await real_verify(ref)
    assert again.fingerprint is not None
    assert await migration.drop_embedded(ref, verified=again.fingerprint)
    assert not await migration.drop_embedded(ref, verified=again.fingerprint)


async def _cli(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, list[str]]:
    code = await script._run(script._parser().parse_args(list(argv)))
    return code, capsys.readouterr().out.splitlines()


async def test_the_script_runs_dry_copy_verify_rerun_and_drop_a_batch_at_a_time(
    monkeypatch: pytest.MonkeyPatch, raw_collection: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(script, "_BATCH", 1)
    one = await _legacy(raw_collection, [_message(1)])
    two = await _legacy(raw_collection, [_message(2), _message(3)])
    scanned = [
        f"... 1 conversations scanned (resume after _id {one.head_id})",
        f"... 2 conversations scanned (resume after _id {two.head_id})",
    ]
    copies = [
        f"  [copied] {one.conversation_id}: 1 copied, 0 rewritten, 0 given an id",
        scanned[0],
        f"  [copied] {two.conversation_id}: 2 copied, 0 rewritten, 0 given an id",
        scanned[1],
        "Summary: 2 copied; 3 entries; 0 elements given an id; 0 emoji_ack messages folded into reactions",
    ]
    dry = "Dry run only. Re-run with --apply to write."

    assert await _cli(capsys) == (0, [*copies, dry])
    assert await _cli(capsys, "--apply") == (0, copies)
    assert await _cli(capsys, "--verify") == (
        0,
        [*scanned, "Verified 2 conversations: 0 with mismatches."],
    )
    assert await _cli(capsys, "--apply") == (
        0,
        ["Summary: nothing to migrate; 0 emoji_ack messages folded into reactions"],
    )
    verified = [*scanned, "Verified 2 conversations: 0 with mismatches."]
    assert await _cli(capsys, "--drop-embedded") == (
        0,
        [*verified, "2 embedded arrays would drop. Dry run only. Re-run with --apply."],
    )
    assert await _cli(capsys, "--drop-embedded", "--apply") == (
        0,
        [*verified, "2 embedded arrays dropped; 0 refused."],
    )
    assert await _read_ids(one) == ["m1"]
    assert await _read_ids(two) == ["m2", "m3"]


async def test_the_script_exits_nonzero_on_a_raced_pass(
    monkeypatch: pytest.MonkeyPatch, raw_collection: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    ref = await _legacy(raw_collection, [_message(1)])
    _after_the_read(
        monkeypatch,
        conversation_entries_migration,
        lambda: raw_collection.update_one(_head(ref), {"$push": {"messages": _message(2)}}),
    )

    assert await _cli(capsys, "--apply") == (
        1,
        [
            f"  [raced] {ref.conversation_id}: written meanwhile, re-run",
            f"... 1 conversations scanned (resume after _id {ref.head_id})",
            "Summary: 1 raced; 0 entries; 0 elements given an id; 0 emoji_ack messages folded into reactions",
        ],
    )


async def test_a_rerun_visits_only_the_head_written_since_and_verify_reports_entries_beyond_it(
    raw_collection: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    untouched = await _legacy(raw_collection, [_message(1)])
    trimmed = await _legacy(raw_collection, [_message(2), _message(3)])
    await _cli(capsys, "--apply")
    await raw_collection.update_one(_head(trimmed), {"$pop": {"messages": -1}})
    scanned = f"... 1 conversations scanned (resume after _id {trimmed.head_id})"

    assert await _cli(capsys, "--apply") == (
        0,
        [
            f"  [merged] {trimmed.conversation_id}: 0 copied, 0 rewritten, 0 given an id",
            scanned,
            "Summary: 1 merged; 0 entries; 0 elements given an id; 0 emoji_ack messages folded into reactions",
        ],
    )
    assert await _cli(capsys, "--verify") == (
        0,
        [
            f"  {trimmed.conversation_id}: 1 entries beyond the embedded array "
            "(trimmed by the old cap, or appended since)",
            f"... 2 conversations scanned (resume after _id {trimmed.head_id})",
            "Verified 2 conversations: 0 with mismatches.",
        ],
    )
    assert await _read_ids(untouched) == ["m1"]


async def test_the_entrypoint_parses_every_mode_and_exits_with_the_runs_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = []

    async def run(args: Any) -> int:
        seen.append(args)
        return 3

    monkeypatch.setattr(script, "_run", run)
    with pytest.raises(SystemExit) as exited:
        await asyncio.to_thread(script.main, ["--verify"])

    assert exited.value.code == 3
    [args] = seen
    assert (args.verify, args.drop_embedded, args.apply) == (True, False, False)
    flags = script._parser().parse_args(["--drop-embedded", "--apply"])
    assert (flags.verify, flags.drop_embedded, flags.apply) == (False, True, True)
    with pytest.raises(SystemExit):
        script._parser().parse_args(["--verify", "--drop-embedded"])
    help_text = " ".join(script._parser().format_help().split())
    for phrase in (
        "Write (otherwise dry run).",
        "Compare entries with each embedded array.",
        "Verify every conversation, then unset the arrays if all pass.",
        "2. Fence: stop the old build, so nothing writes an embedded array.",
        "Rollback before step 5: redeploy the old build.",
    ):
        assert phrase in help_text


async def test_a_conversation_whose_elements_all_lack_ids_migrates_and_reads(
    migration: ConversationEntriesMigration, raw_collection: Any
) -> None:
    unnamed: list[dict[str, object]] = [
        {"type": "user", "response": "a"},
        {"type": "bot", "response": "b"},
    ]
    ref = await _legacy(raw_collection, unnamed)

    assert (await migration.migrate(ref, apply=True)).action is MigrationAction.COPIED

    head = await raw_collection.find_one(_head(ref))
    assert await _read_ids(ref) == [m["message_id"] for m in head["messages"]]
    assert (await migration.verify(ref)).ok
    assert (await migration.migrate(ref, apply=True)).action is MigrationAction.UNCHANGED


async def test_a_conversation_deleted_after_the_scan_is_skipped_and_never_verifies(
    migration: ConversationEntriesMigration, raw_collection: Any, entries_collection: Any
) -> None:
    ref = await _legacy(raw_collection, [_message(1)])
    await raw_collection.delete_one(_head(ref))

    assert await migration.migrate(ref, apply=True) == MigrationOutcome(
        ref.conversation_id, MigrationAction.UNCHANGED, reason="deleted since the scan"
    )
    assert await entries_collection.count_documents({}) == 0
    assert (await migration.verify(ref)).mismatches == ["not migrated: no log_head"]


def _unnamed(text: str) -> dict[str, object]:
    return {"type": "user", "response": text, "date": "2026-01-01T00:00:00+00:00"}


async def _responses(ref: HeadRef) -> list[tuple[str, str]]:
    doc = await ConversationRepository().get(ref.conversation_id, user_id=ref.user_id)
    assert doc is not None
    return [(str(m.message_id), m.response) for m in doc.messages]


async def test_elements_without_an_id_or_with_a_repeated_one_get_unique_ids_written_back(
    raw_collection: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    one = await _legacy(raw_collection, [_unnamed("a"), _message(2)])
    two = await _legacy(raw_collection, [_unnamed("b")])
    repeated = await _legacy(raw_collection, [_message(1), _message(1, response="again")])

    code, _ = await _cli(capsys, "--apply")

    assert code == 0
    [(minted_one, a), (m2, _)] = await _responses(one)
    [(minted_two, b)] = await _responses(two)
    [(m1, _), (minted_repeat, again)] = await _responses(repeated)
    assert (a, m2, b, m1, again) == ("a", "m2", "b", "m1", "again")
    minted = {minted_one, minted_two, minted_repeat}
    assert len(minted) == 3 and all(ObjectId.is_valid(i) for i in minted)
    head = await raw_collection.find_one(_head(one))
    assert [m["message_id"] for m in head["messages"]] == [minted_one, "m2"]


async def test_an_old_build_trim_never_shifts_an_unnamed_elements_content_onto_another(
    raw_collection: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    ref = await _legacy(raw_collection, [_unnamed("a"), _unnamed("b"), _unnamed("c")])
    await _cli(capsys, "--apply")
    # The old build, still serving a capped thread: pushes d and trims a off the front.
    await raw_collection.update_one(
        _head(ref), {"$push": {"messages": {"$each": [_message(4)], "$slice": -3}}}
    )

    code, _ = await _cli(capsys, "--apply")

    assert code == 0
    assert [text for _, text in await _responses(ref)] == ["a", "b", "c", "message 4"]
    assert (await _cli(capsys, "--verify"))[0] == 0


async def test_an_in_place_edit_by_the_old_build_is_refused_by_reads_and_merged_by_a_rerun(
    raw_collection: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    ref = await _legacy(raw_collection, [_message(1), _message(2)])
    await _cli(capsys, "--apply")
    # The old build settles a card in place and, as it does, leaves updatedAt alone.
    await raw_collection.update_one(_head(ref), {"$set": {"messages.0.response": "settled"}})

    with pytest.raises(UnmigratedConversationError):
        await _read_ids(ref)
    assert (await _cli(capsys, "--verify"))[0] == 1
    code, _ = await _cli(capsys, "--apply")

    assert code == 0
    assert await _responses(ref) == [("m1", "settled"), ("m2", "message 2")]


async def test_a_rerun_takes_only_the_fields_the_old_build_changed_and_keeps_new_build_edits(
    raw_collection: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    ref = await _legacy(raw_collection, [_message(1, "bot")])
    await _cli(capsys, "--apply")
    repo = ConversationRepository()
    assert await repo.set_message_pinned(
        ref.conversation_id, user_id=USER, message_id="m1", pinned=True
    )
    await raw_collection.update_one(_head(ref), {"$set": {"messages.0.response": "settled"}})

    await _cli(capsys, "--apply")

    merged = await repo.get_message(ref.conversation_id, "m1", user_id=USER)
    assert merged is not None
    assert (merged.response, merged.pinned) == ("settled", True)


async def test_a_message_the_old_build_wrote_later_keeps_its_own_date(
    raw_collection: Any, entries_collection: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    ref = await _legacy(raw_collection, [_message(1)])
    await _cli(capsys, "--apply")
    written = datetime(2026, 3, 4, 5, 6, tzinfo=UTC)
    await raw_collection.update_one(
        _head(ref), {"$push": {"messages": _message(2, date=written.isoformat())}}
    )

    await _cli(capsys, "--apply")

    entry = await entries_collection.find_one({"conversation_id": ref.conversation_id, "id": "m2"})
    assert entry is not None and entry["at"] == written


async def test_drop_drops_nothing_unless_every_conversation_verifies(
    raw_collection: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    good = await _legacy(raw_collection, [_message(1)])
    await _cli(capsys, "--apply")
    await _legacy(raw_collection, [_message(2)])

    code, out = await _cli(capsys, "--drop-embedded", "--apply")

    assert code == 1
    assert "messages" in await raw_collection.find_one(_head(good))
    assert any("not migrated" in line for line in out)
    assert "Nothing dropped: every conversation must verify first. Run --apply, then retry." in out


async def test_drop_refuses_an_in_place_edit_made_after_its_verify(
    monkeypatch: pytest.MonkeyPatch, raw_collection: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    ref = await _legacy(raw_collection, [_message(1)])
    await _cli(capsys, "--apply")
    real_verify = conversation_entries_migration.verify

    async def verified_then_edited(verified: HeadRef) -> VerifyReport:
        report = await real_verify(verified)
        await raw_collection.update_one(_head(ref), {"$set": {"messages.0.response": "late"}})
        return report

    monkeypatch.setattr(conversation_entries_migration, "verify", verified_then_edited)

    code, _ = await _cli(capsys, "--drop-embedded", "--apply")

    assert code == 1
    head = await raw_collection.find_one(_head(ref))
    assert head["messages"][0]["response"] == "late"


def test_there_is_no_rebuild_into_the_embedded_array() -> None:
    with pytest.raises(SystemExit):
        script._parser().parse_args(["--rebuild-embedded"])


CARD = {"tool_name": "calendar_events", "data": {"events": []}}
THUMBS_UP = MessageReaction(emoji="\U0001f44d", by=ReactionBy.CHAT_MODEL)


def _ack(n: int, target: str, response: str = "\U0001f44d", **fields: object) -> dict[str, object]:
    return _message(
        n, "bot", response=response, kind="emoji_ack", reacts_to_message_id=target, **fields
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


async def test_a_blank_ack_reacts_with_nothing_and_is_kept_as_a_plain_message(
    migration: ConversationEntriesMigration, raw_collection: Any
) -> None:
    ref = await _legacy(raw_collection, [_message(1), _ack(2, "m1", response=" ")])

    await migration.migrate(ref, apply=True)

    assert await _read_ids(ref) == ["m1", "m2"]
    target = await _stored(ref, "m1")
    assert target is not None and target.reaction is None


async def test_the_script_counts_every_ack_it_folds(
    raw_collection: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    for _ in range(2):
        await _legacy(raw_collection, [_message(1), _ack(2, "m1")])

    code, lines = await _cli(capsys, "--apply")

    assert code == 0
    assert lines[-1] == (
        "Summary: 2 copied; 4 entries; 0 elements given an id; "
        "2 emoji_ack messages folded into reactions"
    )


async def test_folding_is_a_dry_run_unless_applied_and_a_rerun_changes_nothing(
    migration: ConversationEntriesMigration, raw_collection: Any, entries_collection: Any
) -> None:
    ref = await _legacy(raw_collection, [_message(1), _ack(2, "m1")])

    dry = await migration.migrate(ref, apply=False)
    assert (dry.conversation_id, dry.action, dry.folded) == (
        ref.conversation_id,
        MigrationAction.COPIED,
        1,
    )
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


async def _new_build_chat(
    raw_collection: Any, entries_collection: Any, *, pending: bool = True
) -> HeadRef:
    """Insert a chat only the entries build wrote: no embedded array, one ack stored, one in the outbox."""
    conversation_id = f"c-{uuid.uuid4().hex}"
    long_ago = datetime(2026, 1, 1, tzinfo=UTC)
    entry = {"conversation_id": conversation_id, "user_id": USER, "at": long_ago}
    ack = {**entry, **_ack(2, "m1"), "seq": 2, "id": "m2"}
    ack.pop("message_id")
    pending_ack = {**entry, **_ack(4, "m3"), "seq": 4, "id": "m4"}
    pending_ack.pop("message_id")
    result = await raw_collection.insert_one(
        {
            "conversation_id": conversation_id,
            "user_id": USER,
            "createdAt": long_ago.isoformat(),
            "updatedAt": long_ago,
            "log_head": 4,
            "outbox": {"4": pending_ack} if pending else {},
        }
    )
    await entries_collection.insert_many(
        [
            {**entry, "type": "user", "response": "hi", "seq": 1, "id": "m1"},
            ack,
            {**entry, "type": "user", "response": "again", "seq": 3, "id": "m3"},
        ]
    )
    return HeadRef(str(result.inserted_id), conversation_id, USER)


async def test_acks_the_entries_build_wrote_are_folded_and_synced_clients_refetch(
    raw_collection: Any, entries_collection: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    ref = await _new_build_chat(raw_collection, entries_collection)

    code, lines = await _cli(capsys, "--apply")

    assert code == 0
    assert lines[-1] == "Summary: nothing to migrate; 2 emoji_ack messages folded into reactions"
    assert await _read_ids(ref) == ["m1", "m3"]
    for target in ("m1", "m3"):
        reacted = await _stored(ref, target)
        assert reacted is not None and reacted.reaction == THUMBS_UP
    head = await raw_collection.find_one(_head(ref))
    assert head["updatedAt"] > datetime(2026, 1, 2, tzinfo=UTC)
    assert (await _cli(capsys, "--apply"))[1][-1] == (
        "Summary: nothing to migrate; 0 emoji_ack messages folded into reactions"
    )


def test_changed_fields_takes_only_the_fields_the_old_build_changed() -> None:
    at = datetime(2026, 1, 1, tzinfo=UTC).isoformat()
    entry = StoredEntry(
        conversation_id="c",
        user_id="u",
        seq=1,
        id="m1",
        migration_fields=field_hashes({"type": "user", "response": "hi", "date": at}),
    )
    edited = {"type": "user", "response": "hi!", "date": at}

    assert _changed_fields(entry, edited) == {
        "$set": {"response": "hi!", "migration_fields": field_hashes(edited)}
    }


def test_changed_fields_unsets_a_removed_field_and_reads_an_absent_log_as_empty() -> None:
    entry = StoredEntry(
        conversation_id="c",
        user_id="u",
        seq=1,
        id="m1",
        migration_fields=field_hashes({"type": "user", "response": "hi", "reaction": "yes"}),
    )
    trimmed = {"type": "user", "response": "hi"}

    assert _changed_fields(entry, trimmed) == {
        "$set": {"migration_fields": field_hashes(trimmed)},
        "$unset": {"reaction": ""},
    }

    bare = StoredEntry(conversation_id="c", user_id="u", seq=2, id="m2")
    assert _changed_fields(bare, trimmed) == {
        "$set": {**trimmed, "migration_fields": field_hashes(trimmed)}
    }


async def test_a_dry_run_reports_how_many_ids_it_would_mint(
    migration: ConversationEntriesMigration, raw_collection: Any
) -> None:
    ref = await _legacy(raw_collection, [_unnamed("a"), _message(2), _unnamed("c")])

    planned = await migration.migrate(ref, apply=False)

    assert planned == MigrationOutcome(
        ref.conversation_id, MigrationAction.COPIED, copied=3, identified=2
    )


async def test_a_raced_identify_reports_the_conversation_as_raced(
    monkeypatch: pytest.MonkeyPatch, migration: ConversationEntriesMigration, raw_collection: Any
) -> None:
    ref = await _legacy(raw_collection, [_unnamed("a")])

    async def refuse(*args: object, **kwargs: object) -> bool:
        return False

    monkeypatch.setattr(migration, "_identify", refuse)

    assert await migration.migrate(ref, apply=True) == MigrationOutcome(
        ref.conversation_id, MigrationAction.RACED
    )


async def test_a_head_deleted_after_identify_reports_the_conversation_as_raced(
    monkeypatch: pytest.MonkeyPatch, migration: ConversationEntriesMigration, raw_collection: Any
) -> None:
    ref = await _legacy(raw_collection, [_unnamed("a")])
    real = migration._embedded_head
    reads = 0

    async def read_then_vanish(r: HeadRef) -> object:
        nonlocal reads
        reads += 1
        return None if reads == 2 else await real(r)

    monkeypatch.setattr(migration, "_embedded_head", read_then_vanish)

    assert await migration.migrate(ref, apply=True) == MigrationOutcome(
        ref.conversation_id, MigrationAction.RACED
    )


async def test_an_identify_racing_an_old_build_write_is_refused_and_keeps_the_write(
    monkeypatch: pytest.MonkeyPatch, migration: ConversationEntriesMigration, raw_collection: Any
) -> None:
    ref = await _legacy(raw_collection, [_unnamed("a")])
    _after_the_read(
        monkeypatch,
        migration,
        lambda: raw_collection.update_one(_head(ref), {"$push": {"messages": _message(2)}}),
    )

    outcome = await migration.migrate(ref, apply=True)

    assert outcome == MigrationOutcome(ref.conversation_id, MigrationAction.RACED)
    head = await raw_collection.find_one(_head(ref))
    assert [m.get("message_id") for m in head["messages"]] == [None, "m2"]


async def test_a_dry_run_reports_what_a_second_pass_would_copy_and_rewrite(
    migration: ConversationEntriesMigration, raw_collection: Any
) -> None:
    ref = await _legacy(raw_collection, [_message(1), _message(2)])
    await migration.migrate(ref, apply=True)
    await raw_collection.update_one(
        _head(ref),
        {"$set": {"messages": [_message(1, response="settled"), _message(2), _message(3)]}},
    )

    planned = await migration.migrate(ref, apply=False)

    assert planned == MigrationOutcome(
        ref.conversation_id, MigrationAction.MERGED, copied=1, rewritten=1
    )


async def test_the_summary_counts_every_id_it_mints_across_conversations(
    raw_collection: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    await _legacy(raw_collection, [_unnamed("a")])
    await _legacy(raw_collection, [_unnamed("b")])

    code, out = await _cli(capsys, "--apply")

    assert code == 0
    assert out[-1] == (
        "Summary: 2 copied; 2 entries; 2 elements given an id; 0 emoji_ack messages folded into reactions"
    )


async def test_the_summary_lists_each_action_once_sorted(
    raw_collection: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    written = await _legacy(raw_collection, [_message(1)])
    await _cli(capsys, "--apply")
    await raw_collection.update_one(_head(written), {"$push": {"messages": _message(2)}})
    await _legacy(raw_collection, [_message(3)])

    code, out = await _cli(capsys, "--apply")

    assert code == 0
    assert out[-1] == (
        "Summary: 1 copied, 1 merged; 2 entries; 0 elements given an id; 0 emoji_ack messages folded into reactions"
    )


async def test_verify_counts_every_failing_conversation(
    raw_collection: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    await _legacy(raw_collection, [_message(1)])
    await _legacy(raw_collection, [_message(2)])

    code, out = await _cli(capsys, "--verify")

    assert code == 1
    assert "Verified 2 conversations: 2 with mismatches." in out


async def test_drop_counts_every_refused_conversation(
    monkeypatch: pytest.MonkeyPatch, raw_collection: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    one = await _legacy(raw_collection, [_message(1)])
    two = await _legacy(raw_collection, [_message(2)])
    await _cli(capsys, "--apply")
    real_verify = conversation_entries_migration.verify

    async def verify_then_edit(ref: HeadRef) -> VerifyReport:
        report = await real_verify(ref)
        await raw_collection.update_one(_head(ref), {"$set": {"messages.0.response": "late"}})
        return report

    monkeypatch.setattr(conversation_entries_migration, "verify", verify_then_edit)

    code, out = await _cli(capsys, "--drop-embedded", "--apply")

    assert code == 1
    assert "0 embedded arrays dropped; 2 refused." in out
    assert any(
        f"  [refused] {one.conversation_id}: written since its verify" in line for line in out
    )
    assert any(
        f"  [refused] {two.conversation_id}: written since its verify" in line for line in out
    )


def test_the_parser_keeps_the_raw_description_layout() -> None:
    assert script._parser().formatter_class is argparse.RawDescriptionHelpFormatter


async def test_heads_with_acks_finds_each_stored_ack_its_owner_wrote_after_the_given_head(
    migration: ConversationEntriesMigration, raw_collection: Any, entries_collection: Any
) -> None:
    skipped = await _new_build_chat(raw_collection, entries_collection, pending=False)
    no_ack = await _legacy(raw_collection, [_message(1), _message(2, "bot")])
    await migration.migrate(no_ack, apply=True)
    foreign = await _legacy(raw_collection, [_message(1)])
    await migration.migrate(foreign, apply=True)
    await entries_collection.insert_one(
        {
            "conversation_id": foreign.conversation_id,
            "user_id": "someone-else",
            **_ack(2, "m1"),
            "seq": 2,
            "id": "m2",
        }
    )
    stored = await _new_build_chat(raw_collection, entries_collection, pending=False)

    assert await migration.heads_with_acks(after_head_id=None, batch=10) == [skipped, stored]
    assert await migration.heads_with_acks(after_head_id=skipped.head_id, batch=10) == [stored]


async def test_a_head_deleted_after_the_scan_folds_nothing(
    migration: ConversationEntriesMigration, raw_collection: Any, entries_collection: Any
) -> None:
    ref = await _new_build_chat(raw_collection, entries_collection, pending=False)
    await raw_collection.delete_one(_head(ref))

    gone = await migration.migrate(ref, apply=True)

    assert (gone.action, gone.reason, gone.folded) == (
        MigrationAction.UNCHANGED,
        "deleted since the scan",
        0,
    )
    assert (
        await entries_collection.count_documents(
            {"conversation_id": ref.conversation_id, "kind": "emoji_ack"}
        )
        == 1
    )


async def test_a_dry_run_after_a_fold_counts_only_the_elements_never_copied(
    migration: ConversationEntriesMigration, raw_collection: Any
) -> None:
    ref = await _legacy(raw_collection, [_message(1), _ack(2, "m1")])
    await migration.migrate(ref, apply=True)
    await raw_collection.update_one(
        _head(ref),
        {
            "$set": {
                "messages": [_message(1), _ack(2, "m1"), _message(3), _message(4)],
                "updatedAt": datetime.now(UTC),
            }
        },
    )

    dry = await migration.migrate(ref, apply=False)

    assert (dry.action, dry.copied, dry.rewritten) == (MigrationAction.MERGED, 2, 0)


async def test_the_script_folds_and_counts_the_acks_of_every_batch(
    monkeypatch: pytest.MonkeyPatch,
    raw_collection: Any,
    entries_collection: Any,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(script, "_BATCH", 1)
    one = await _new_build_chat(raw_collection, entries_collection)
    two = await _new_build_chat(raw_collection, entries_collection)
    scanned_after: list[str | None] = []
    scan = conversation_entries_migration.heads_with_acks

    async def recording_scan(*, after_head_id: str | None, batch: int) -> list[HeadRef]:
        scanned_after.append(after_head_id)
        return await scan(after_head_id=after_head_id, batch=batch)

    monkeypatch.setattr(conversation_entries_migration, "heads_with_acks", recording_scan)

    code, lines = await _cli(capsys, "--apply")

    assert code == 0
    assert lines[-1] == "Summary: nothing to migrate; 4 emoji_ack messages folded into reactions"
    assert scanned_after == [None, one.head_id, two.head_id]
