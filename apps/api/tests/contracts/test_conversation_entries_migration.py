"""The entries migration against real Mongo: copy, re-run, second pass, verify, drop and rollback."""

from __future__ import annotations

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
    element_hash,
    entry_at,
)
from app.db.repositories.conversations import ConversationRepository
from app.models.chat_models import MessageModel
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
        "emoji ack": [_message(1), _message(2, "bot", kind="emoji_ack", reacts_to_message_id="m1")],
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
    assert (await migration.verify(ref)).mismatches == [
        "written by the old build since its last pass: run --since",
        "m2 differs from its entry",
        "m3 has no entry",
    ]

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


async def test_a_first_pass_that_died_before_marking_is_redone_from_the_array_as_it_is_now(
    migration: ConversationEntriesMigration, raw_collection: Any, entries_collection: Any
) -> None:
    ref = await _legacy(raw_collection, [_message(1), _message(2)])
    await migration.migrate(ref, apply=True)
    # The pass died after writing entries and before marking; the old build then trimmed m1 and appended m3.
    await raw_collection.update_one(
        {"_id": ObjectId(ref.head_id)},
        {
            "$unset": {"log_head": "", "migrated_last_id": ""},
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

    assert element_hash({"a": 1, "b": at}) == element_hash({"b": at, "a": 1})
    assert element_hash({"a": 1, "b": at}) == element_hash({"a": 1, "b": str(at)})
    assert element_hash({"a": 1}) != element_hash({"a": 2})


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
        "migration_hash": element_hash(_message(1)),
    }


async def test_scans_walk_every_head_in_id_order_one_batch_at_a_time(
    migration: ConversationEntriesMigration, raw_collection: Any
) -> None:
    refs = [await _legacy(raw_collection, [_message(n)]) for n in (1, 2, 3)]
    later = datetime.now(UTC) + timedelta(seconds=1)
    await raw_collection.update_one(_head(refs[1]), {"$set": {"updatedAt": later}})

    async def walk(scan: Callable[[str | None], Awaitable[list[HeadRef]]]) -> list[HeadRef]:
        seen: list[HeadRef] = []
        after: str | None = None
        while batch := await scan(after):
            assert len(batch) == 1
            seen += batch
            after = batch[-1].head_id
        return seen

    assert (
        await walk(
            lambda after: migration.heads_with_embedded(after_head_id=after, since=None, batch=1)
        )
        == refs
    )
    assert await migration.heads_with_embedded(after_head_id=None, since=later, batch=9) == [
        refs[1]
    ]
    for ref in refs:
        await migration.migrate(ref, apply=True)
        assert await migration.drop_embedded(ref)
    assert (
        await walk(lambda after: migration.heads_without_embedded(after_head_id=after, batch=1))
        == refs
    )


async def test_repeated_ids_are_refused_by_name_and_nothing_is_copied(
    migration: ConversationEntriesMigration, raw_collection: Any, entries_collection: Any
) -> None:
    ref = await _legacy(raw_collection, [_message(2), _message(1), _message(2), _message(1)])

    assert await migration.migrate(ref, apply=True) == MigrationOutcome(
        ref.conversation_id,
        MigrationAction.REFUSED,
        reason="message ids repeat in the embedded array: m1, m2",
    )
    assert await entries_collection.count_documents({}) == 0


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
        {**of, "id": "m4"}, {"$set": {"migration_hash": element_hash(_message(5))}}
    )

    assert await migration.verify(ref) == VerifyReport(
        ref.conversation_id,
        embedded=5,
        entries=3,
        mismatches=[
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
    monkeypatch: pytest.MonkeyPatch, migration: ConversationEntriesMigration, raw_collection: Any
) -> None:
    ref = await _legacy(raw_collection, [_message(1)])
    await migration.migrate(ref, apply=True)
    real_verify = migration.verify

    async def verified_then_written(verified: HeadRef) -> VerifyReport:
        report = await real_verify(verified)
        await raw_collection.update_one(_head(ref), {"$push": {"messages": _message(2)}})
        return report

    monkeypatch.setattr(migration, "verify", verified_then_written)
    assert not await migration.drop_embedded(ref)
    monkeypatch.setattr(migration, "verify", real_verify)

    head = await raw_collection.find_one(_head(ref))
    assert [m["message_id"] for m in head["messages"]] == ["m1", "m2"]
    await migration.migrate(ref, apply=True)
    assert await migration.drop_embedded(ref)
    assert not await migration.drop_embedded(ref)


async def test_rebuild_restores_an_element_without_an_id_and_a_dry_run_writes_nothing(
    migration: ConversationEntriesMigration, raw_collection: Any, entries_collection: Any
) -> None:
    unnamed = {"type": "user", "response": "old"}
    ref = await _legacy(raw_collection, [unnamed, _message(2)])
    await migration.migrate(ref, apply=True)
    assert await migration.drop_embedded(ref)

    assert await migration.rebuild_embedded(ref, apply=False) == 2
    assert "messages" not in await raw_collection.find_one(_head(ref))
    assert await entries_collection.count_documents({}) == 2

    assert await migration.rebuild_embedded(ref, apply=True) == 2
    head = await raw_collection.find_one(_head(ref))
    assert head["messages"] == [unnamed, _message(2)]
    assert not {"log_head", "outbox", "migrated_last_id"} & set(head)


async def _cli(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, list[str]]:
    code = await script._run(script._parser().parse_args(list(argv)))
    return code, capsys.readouterr().out.splitlines()


async def test_the_script_runs_dry_copy_verify_rerun_drop_and_rollback_a_batch_at_a_time(
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
        f"  [copied] {one.conversation_id}: 1 copied, 0 rewritten",
        scanned[0],
        f"  [copied] {two.conversation_id}: 2 copied, 0 rewritten",
        scanned[1],
        "Summary: 2 copied; 3 entries",
    ]
    dry = "Dry run only. Re-run with --apply to write."

    assert await _cli(capsys) == (0, [*copies, dry])
    assert await _cli(capsys, "--apply") == (0, copies)
    assert await _cli(capsys, "--verify") == (
        0,
        [*scanned, "Verified 2 conversations: 0 with mismatches."],
    )
    assert await _cli(capsys, "--apply") == (0, [*scanned, "Summary: 2 unchanged; 0 entries"])
    assert await _cli(capsys, "--drop-embedded") == (
        0,
        [*scanned, "2 embedded arrays would drop; 0 refused.", dry],
    )
    assert await _cli(capsys, "--drop-embedded", "--apply") == (
        0,
        [*scanned, "2 embedded arrays dropped; 0 refused."],
    )
    assert await _cli(capsys, "--rebuild-embedded") == (
        0,
        [*scanned, "2 embedded arrays would rebuild from 3 entries.", dry],
    )
    assert await _cli(capsys, "--rebuild-embedded", "--apply") == (
        0,
        [*scanned, "2 embedded arrays rebuilt from 3 entries."],
    )
    for rebuilt in (one, two):
        with pytest.raises(UnmigratedConversationError):
            await _read_ids(rebuilt)


async def test_the_script_exits_nonzero_on_a_refused_conversation_and_names_it(
    raw_collection: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    ref = await _legacy(raw_collection, [_message(1), _message(1)])
    scanned = f"... 1 conversations scanned (resume after _id {ref.head_id})"

    assert await _cli(capsys, "--apply") == (
        1,
        [
            f"  [refused] {ref.conversation_id} message ids repeat in the embedded array: m1",
            scanned,
            "Summary: 1 refused; 0 entries",
        ],
    )
    assert await _cli(capsys, "--verify") == (
        1,
        [
            f"  MISMATCH {ref.conversation_id}: not migrated: no log_head",
            scanned,
            "Verified 1 conversations: 1 with mismatches.",
        ],
    )
    assert await _cli(capsys, "--drop-embedded") == (
        1,
        [
            scanned,
            "0 embedded arrays would drop; 1 refused.",
            "Dry run only. Re-run with --apply to write.",
        ],
    )
    assert await _cli(capsys, "--drop-embedded", "--apply") == (
        1,
        [
            f"  [refused] {ref.conversation_id}: --verify does not pass",
            scanned,
            "0 embedded arrays dropped; 1 refused.",
        ],
    )


async def test_the_script_exits_nonzero_on_a_raced_pass(
    monkeypatch: pytest.MonkeyPatch, raw_collection: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    ref = await _legacy(raw_collection, [_message(1)])
    _after_the_read(
        monkeypatch,
        script.conversation_entries_migration,
        lambda: raw_collection.update_one(_head(ref), {"$push": {"messages": _message(2)}}),
    )

    assert await _cli(capsys, "--apply") == (
        1,
        [
            f"  [raced] {ref.conversation_id} ",
            f"... 1 conversations scanned (resume after _id {ref.head_id})",
            "Summary: 1 raced; 0 entries",
        ],
    )


async def test_the_second_pass_takes_since_and_verify_reports_entries_beyond_the_array(
    raw_collection: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    untouched = await _legacy(raw_collection, [_message(1)])
    trimmed = await _legacy(raw_collection, [_message(2), _message(3)])
    await _cli(capsys, "--apply")
    since = datetime.now(UTC)
    await raw_collection.update_one(
        _head(trimmed),
        {"$pop": {"messages": -1}, "$set": {"updatedAt": since + timedelta(seconds=1)}},
    )
    scanned = f"... 1 conversations scanned (resume after _id {trimmed.head_id})"

    assert await _cli(capsys, "--apply", "--since", since.isoformat()) == (
        0,
        [scanned, "Summary: 1 unchanged; 0 entries"],
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
        await asyncio.to_thread(script.main, ["--verify", "--since", "2026-11-12T10:00:00+00:00"])

    assert exited.value.code == 3
    [args] = seen
    assert (args.verify, args.drop_embedded, args.rebuild_embedded, args.apply) == (
        True,
        False,
        False,
        False,
    )
    assert args.since == datetime(2026, 11, 12, 10, tzinfo=UTC)
    flags = script._parser().parse_args(["--rebuild-embedded", "--apply"])
    assert (flags.rebuild_embedded, flags.apply, flags.since) == (True, True, None)
    with pytest.raises(SystemExit):
        script._parser().parse_args(["--verify", "--drop-embedded"])
    help_text = " ".join(script._parser().format_help().split())
    for phrase in (
        "Write (otherwise dry run).",
        "Second pass: only conversations whose updatedAt is at or after this ISO datetime.",
        "Compare entries with each embedded array.",
        "Unset each embedded array that --verify passes.",
        "Rollback: rebuild embedded arrays from entries.",
    ):
        assert phrase in help_text


async def test_a_conversation_whose_elements_all_lack_ids_migrates_and_reads(
    migration: ConversationEntriesMigration, raw_collection: Any
) -> None:
    unnamed = [{"type": "user", "response": "a"}, {"type": "bot", "response": "b"}]
    ref = await _legacy(raw_collection, unnamed)

    assert (await migration.migrate(ref, apply=True)).action is MigrationAction.COPIED

    assert await _read_ids(ref) == ["legacy-1", "legacy-2"]
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
    assert not await migration.drop_embedded(ref)
