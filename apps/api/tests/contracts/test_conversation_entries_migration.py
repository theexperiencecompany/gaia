"""The entries migration against real Mongo: old shapes to log entries, re-runs, races, verify, drop, boot check."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
import uuid

from bson import ObjectId
import pytest

from app.db.mongodb.indexes import UNMIGRATED_HEAD_KEYS, UNMIGRATED_HEAD_OPTIONS
from app.db.repositories.conversation_entries_legacy import ConversationEntry
from app.db.repositories.conversation_entries_migration import (
    ConversationEntriesMigration,
    HeadRef,
    MigrationAction,
    expected_messages,
)
from app.db.repositories.conversation_entries_oracle import legacy_messages
from app.db.repositories.conversation_migration_guard import (
    MESSAGE_SHAPED,
    NEVER_MIGRATED_HEADS,
    refuse_unmigrated_conversations,
)
from app.db.repositories.conversations import ConversationRepository
from app.models.conversation_log_models import LoggedEntry
from app.models.conversation_models import LogPage
from app.scripts import migrate_conversation_entries as script
from app.utils.errors import UnmigratedConversationError

pytestmark = pytest.mark.usefixtures("entries_collection")

USER = "u-migrate"
_DATE = datetime(2026, 1, 1, 9, 30, 15, 123456, tzinfo=UTC).isoformat()
_CARD = {"tool_name": "search_results", "data": {"query": "q", "results": []}}


@pytest.fixture
def migration(raw_collection: Any) -> ConversationEntriesMigration:
    return ConversationEntriesMigration()


def _message(n: int, role: str = "user", **fields: object) -> dict[str, object]:
    return {
        "type": role,
        "response": f"message {n}",
        "message_id": f"m{n}",
        "date": _DATE,
        **fields,
    }


def _every_shape() -> list[dict[str, object]]:
    """One old chat holding every shape the old build wrote."""
    file = {"fileId": "f1", "url": "https://x/f1", "filename": "a.pdf", "type": "application/pdf"}
    return [
        _message(1, fileIds=["f1"], fileData=[file], pinned=True),
        _message(2, "bot", tool_data=[_CARD], follow_up_actions=["more"], pinned=True),
        _message(3, reaction={"emoji": "\U0001f525", "by": "jev"}),
        _message(4, "bot", stopped=True),
        _message(5, replyToMessage={"id": "m2", "content": "message 2", "role": "assistant"}),
        _message(
            6,
            "bot",
            error="the model is overloaded",
            replyToMessage={"id": "m5", "content": "stale", "role": "user"},
        ),
        {
            "type": "bot",
            "kind": "emoji_ack",
            "response": "\U0001f44d",
            "reacts_to_message_id": "m1",
        },
        {
            "type": "bot",
            "kind": "emoji_ack",
            "response": "\U0001f389",
            "reacts_to_message_id": "m3",
            "tool_data": [_CARD],
            "message_id": "ack-cards",
        },
        {"type": "bot", "kind": "emoji_ack", "response": "ok", "reacts_to_message_id": "gone"},
        {"type": "user", "response": "no id"},
        _message(7, "user", message_id="m1"),
        _message(8, "bot", in_progress=True),
    ]


async def _legacy(raw_collection: Any, messages: list[dict[str, object]]) -> HeadRef:
    """Insert a conversation the way production stores it: its messages embedded in the head."""
    conversation_id = f"c-{uuid.uuid4().hex}"
    result = await raw_collection.insert_one(
        {
            "conversation_id": conversation_id,
            "user_id": USER,
            "description": "legacy",
            "createdAt": datetime.now(UTC).isoformat(),
            "updatedAt": datetime(2026, 1, 1, tzinfo=UTC),
            "messages": messages,
        }
    )
    return HeadRef(str(result.inserted_id), conversation_id, USER)


async def _entries(entries_collection: Any, ref: HeadRef) -> list[dict[str, Any]]:
    match = {"user_id": ref.user_id, "conversation_id": ref.conversation_id}
    return await entries_collection.find(match, {"_id": 0}).sort("seq", 1).to_list(None)


async def _head(raw_collection: Any, ref: HeadRef) -> dict[str, Any]:
    return await raw_collection.find_one({"_id": ObjectId(ref.head_id)})


async def _history(ref: HeadRef) -> list[tuple[str, str | None, str]]:
    doc = await ConversationRepository().get(ref.conversation_id, user_id=ref.user_id)
    assert doc is not None
    return [(m.type, m.message_id, m.response) for m in shown_messages(doc)]


async def test_every_old_shape_becomes_log_entries_that_read_back_as_the_old_array(
    migration: ConversationEntriesMigration, raw_collection: Any, entries_collection: Any
) -> None:
    ref = await _legacy(raw_collection, _every_shape())

    outcome = await migration.migrate(ref, apply=True)

    assert (outcome.action, outcome.identified, outcome.folded) == (MigrationAction.COPIED, 4, 2), (
        outcome.reason
    )
    head = await _head(raw_collection, ref)
    array = head["messages"]
    minted = [array[9]["message_id"], array[10]["message_id"]]
    assert all(ObjectId.is_valid(m) for m in minted) and minted[1] != "m1"
    entries = await _entries(entries_collection, ref)
    kinds = [(e["seq"], e["kind"], e["id"]) for e in entries]
    assert kinds == [
        (1, "user_message", "m1"),
        (2, "reply", "m2"),
        (3, "user_message", "m3"),
        (4, "reply", "m4"),
        (5, "user_message", "m5"),
        (6, "reply", "m6"),
        (7, "reply", "ack-cards"),
        (8, "reply", array[8]["message_id"]),
        (9, "user_message", minted[0]),
        (10, "user_message", minted[1]),
        (11, "reply", "m8"),
        (12, "reply_settled", "m2:settled"),
        (13, "reply_settled", "m4:settled"),
        (14, "reply_settled", "m6:settled"),
        (15, "reply_settled", "ack-cards:settled"),
        (16, "reply_settled", f"{array[8]['message_id']}:settled"),
        (17, "reply_settled", "m8:settled"),
    ]
    by_id = {e["id"]: e for e in entries}
    assert by_id["m1"]["reaction"] == {"emoji": "\U0001f44d", "by": "chat_model"}
    assert by_id["m3"]["reaction"] == {"emoji": "\U0001f389", "by": "chat_model"}
    assert by_id["ack-cards"]["text"] == "" and by_id["ack-cards"]["tool_data"]
    assert (by_id["m2:settled"]["answers"], by_id["m2:settled"]["through"]) == (["m1"], 1)
    assert by_id["m4:settled"]["outcome"] == "stopped"
    assert by_id["m6:settled"]["failure"] == "model_error"
    assert (by_id["m8:settled"]["outcome"], by_id["m8:settled"]["failure"]) == (
        "failed",
        "server_restart",
    )
    assert by_id["m8:settled"]["imported"] is True
    assert by_id["m1"]["at"] == datetime.fromisoformat(_DATE).replace(microsecond=123000)
    assert head["log_head"] == 17 and head["state"]["comms"] == "idle"
    assert head["state"]["unsettled_waking"] == [] and head["state"]["open_reply"] is None
    assert head["updatedAt"] > datetime(2026, 1, 1, tzinfo=UTC)

    report = await migration.verify(ref)
    assert report.ok, report.mismatches
    assert report.messages == len(expected_messages(array)) == 11
    doc = await ConversationRepository().get(ref.conversation_id, user_id=ref.user_id)
    assert doc is not None
    shown = {m.message_id: m for m in shown_messages(doc)}
    assert shown["m6"].error == "model_error" and shown["m4"].stopped is True
    assert (
        shown["m6"].replyToMessage is not None and shown["m6"].replyToMessage.content == "message 5"
    )
    assert shown["m8"].in_progress is None and shown["m8"].error == "server_restart"
    assert shown["m1"].fileIds == ["f1"] and shown["m1"].pinned and shown["m2"].pinned
    pinned = await ConversationRepository().list_pinned_messages(USER)
    assert {hit.item.id for hit in pinned} == {"m1", "m2"}
    found = await ConversationRepository().search(USER, pattern="message 5")
    assert [hit.item.id for hit in found.messages] == ["m5"]


async def test_a_rerun_finds_nothing_to_do_and_changes_nothing(
    migration: ConversationEntriesMigration, raw_collection: Any, entries_collection: Any
) -> None:
    ref = await _legacy(raw_collection, _every_shape())
    await migration.migrate(ref, apply=True)
    before = (await _entries(entries_collection, ref), await _head(raw_collection, ref))

    assert await migration.heads_to_migrate(after_head_id=None, batch=10) == []
    outcome = await migration.migrate(ref, apply=True)

    assert outcome.action is MigrationAction.UNCHANGED
    assert (await _entries(entries_collection, ref), await _head(raw_collection, ref)) == before


async def test_an_old_build_write_after_a_pass_is_caught_and_only_its_fields_rewritten(
    migration: ConversationEntriesMigration, raw_collection: Any, entries_collection: Any
) -> None:
    ref = await _legacy(raw_collection, [_message(1), _message(2, "bot")])
    await migration.migrate(ref, apply=True)
    entry_of = {"user_id": USER, "conversation_id": ref.conversation_id}
    # A field the old array never changes, edited by the new build since the pass.
    await entries_collection.update_one({**entry_of, "id": "m2"}, {"$set": {"heard_through": 3}})
    # The old build edits a message in place: no append, no updatedAt.
    await raw_collection.update_one(
        {"_id": ObjectId(ref.head_id)}, {"$set": {"messages.1.response": "edited"}}
    )

    assert [
        h.conversation_id for h in await migration.heads_to_migrate(after_head_id=None, batch=10)
    ] == [ref.conversation_id]
    outcome = await migration.migrate(ref, apply=True)

    assert (outcome.action, outcome.rewritten, outcome.written) == (MigrationAction.MERGED, 1, 0)
    reply = await entries_collection.find_one({**entry_of, "id": "m2"})
    assert (reply["text"], reply["heard_through"], reply["seq"]) == ("edited", 3, 2)
    assert await _history(ref) == [("user", "m1", "message 1"), ("bot", "m2", "edited")]


async def test_messages_the_old_build_appends_later_land_after_the_tail_settles(
    migration: ConversationEntriesMigration, raw_collection: Any, entries_collection: Any
) -> None:
    ref = await _legacy(raw_collection, [_message(1), _message(2, "bot")])
    await migration.migrate(ref, apply=True)
    await raw_collection.update_one(
        {"_id": ObjectId(ref.head_id)},
        {"$push": {"messages": {"$each": [_message(3), _message(4, "bot")]}}},
    )

    outcome = await migration.migrate(ref, apply=True)

    assert (outcome.action, outcome.written) == (MigrationAction.MERGED, 3)
    seqs = [(e["seq"], e["id"]) for e in await _entries(entries_collection, ref)]
    assert seqs == [
        (1, "m1"),
        (2, "m2"),
        (3, "m2:settled"),
        (4, "m3"),
        (5, "m4"),
        (6, "m4:settled"),
    ]
    settle = (await _entries(entries_collection, ref))[-1]
    assert (settle["answers"], settle["through"]) == (["m3"], 4)
    assert (await migration.verify(ref)).ok


async def test_a_write_landing_mid_migration_is_raced_and_never_lost(
    migration: ConversationEntriesMigration,
    raw_collection: Any,
    entries_collection: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = await _legacy(raw_collection, [_message(1), _message(2, "bot")])
    read_entries = migration._stored

    async def old_build_writes_meanwhile(target: HeadRef) -> Any:
        rows = await read_entries(target)
        await raw_collection.update_one(
            {"_id": ObjectId(ref.head_id)}, {"$push": {"messages": _message(3)}}
        )
        return rows

    monkeypatch.setattr(migration, "_stored", old_build_writes_meanwhile)
    raced = await migration.migrate(ref, apply=True)
    monkeypatch.setattr(migration, "_stored", read_entries)

    assert raced.action is MigrationAction.RACED
    assert await _entries(entries_collection, ref) == []
    assert "log_head" not in await _head(raw_collection, ref)
    assert (await migration.migrate(ref, apply=True)).action is MigrationAction.COPIED
    assert [e["id"] for e in await _entries(entries_collection, ref)] == [
        "m1",
        "m2",
        "m3",
        "m2:settled",
    ]
    assert (await migration.verify(ref)).ok


async def test_verify_detects_a_corrupted_entry_and_a_write_since_the_pass(
    migration: ConversationEntriesMigration, raw_collection: Any, entries_collection: Any
) -> None:
    ref = await _legacy(raw_collection, [_message(1), _message(2, "bot", pinned=True)])
    await migration.migrate(ref, apply=True)
    entry_of = {"user_id": USER, "conversation_id": ref.conversation_id}

    await entries_collection.update_one({**entry_of, "id": "m1"}, {"$set": {"text": "tampered"}})
    report = await migration.verify(ref)
    assert not report.ok and report.mismatches[0].startswith("history differs at message 0")

    await entries_collection.update_one({**entry_of, "id": "m1"}, {"$set": {"text": "message 1"}})
    await entries_collection.update_one({**entry_of, "id": "m2"}, {"$set": {"pinned": False}})
    report = await migration.verify(ref)
    assert any(m.startswith("pinned") for m in report.mismatches)

    await entries_collection.update_one({**entry_of, "id": "m2"}, {"$set": {"pinned": True}})
    assert (await migration.verify(ref)).ok
    await raw_collection.update_one(
        {"_id": ObjectId(ref.head_id)}, {"$set": {"messages.0.response": "later"}}
    )
    assert (await migration.verify(ref)).mismatches == ["written since its last pass: run --apply"]


async def test_a_failed_or_stopped_reply_with_no_text_reads_back_in_the_arrays_order(
    migration: ConversationEntriesMigration, raw_collection: Any
) -> None:
    later = datetime(2026, 1, 1, 9, 31, tzinfo=UTC).isoformat()
    ref = await _legacy(
        raw_collection,
        [
            _message(1),
            _message(2, "bot"),
            _message(3),
            _message(4, "bot", response="", error="No tool output found", date=later),
            _message(5, "bot"),
            _message(6),
            _message(7, "bot", response="", stopped=True),
        ],
    )
    await migration.migrate(ref, apply=True)

    report = await migration.verify(ref)

    assert report.ok, report.mismatches
    assert [m for _, m, _ in await _history(ref)] == ["m1", "m2", "m3", "m4", "m5", "m6", "m7"]


async def test_a_generated_image_reads_back_as_stored_and_verify_catches_its_loss(
    migration: ConversationEntriesMigration, raw_collection: Any, entries_collection: Any
) -> None:
    image = {"url": "https://x/cat.png", "prompt": "a cat", "improved_prompt": "a cat, lit"}
    ref = await _legacy(
        raw_collection,
        [
            _message(1),
            _message(2, "bot", response="", image_data=image),
            _message(3, "bot", image_data=image),
        ],
    )

    await migration.migrate(ref, apply=True)

    doc = await ConversationRepository().get(ref.conversation_id, user_id=ref.user_id)
    assert doc is not None
    shown = {m.message_id: m for m in shown_messages(doc)}
    assert shown["m2"].image_data is not None
    assert shown["m2"].image_data.model_dump() == image
    assert shown["m3"].image_data is not None and shown["m3"].response == "message 3"
    assert (await migration.verify(ref)).ok
    entry_of = {"user_id": USER, "conversation_id": ref.conversation_id, "id": "m3"}
    await entries_collection.update_one(entry_of, {"$unset": {"image": ""}})
    report = await migration.verify(ref)
    assert not report.ok and report.mismatches[0].startswith("history differs at message 2")


async def _cli(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, list[str]]:
    code = await script._run(script._parser().parse_args(argv))
    return code, capsys.readouterr().out.splitlines()


async def test_cli_applies_then_verifies_and_keeps_every_old_array(
    raw_collection: Any,
    entries_collection: Any,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ref = await _legacy(raw_collection, [_message(1), _message(2, "bot")])

    code, out = await _cli(capsys)
    assert code == 0 and out[-1] == "Dry run only. Re-run with --apply to write."
    assert await _entries(entries_collection, ref) == []
    assert (await _cli(capsys, "--apply"))[0] == 0
    entry_of = {"user_id": USER, "conversation_id": ref.conversation_id}
    await entries_collection.update_one({**entry_of, "id": "m1"}, {"$set": {"text": "x"}})
    assert (await _cli(capsys, "--verify"))[0] == 1

    await entries_collection.update_one({**entry_of, "id": "m1"}, {"$set": {"text": "message 1"}})
    assert (await _cli(capsys, "--verify"))[0] == 0
    head = await _head(raw_collection, ref)
    assert [m["message_id"] for m in head["messages"]] == ["m1", "m2"]
    assert await _history(ref) == [("user", "m1", "message 1"), ("bot", "m2", "message 2")]


async def test_message_shaped_entries_are_rewritten_in_place_with_settles_at_the_tail(
    migration: ConversationEntriesMigration, raw_collection: Any, entries_collection: Any
) -> None:
    conversation_id = f"c-{uuid.uuid4().hex}"
    result = await raw_collection.insert_one(
        {"conversation_id": conversation_id, "user_id": USER, "log_head": 4}
    )
    ref = HeadRef(str(result.inserted_id), conversation_id, USER)
    at = datetime(2026, 2, 1, tzinfo=UTC)
    old: list[dict[str, object]] = [
        _message(1),
        _message(2, "bot"),
        {
            "type": "bot",
            "kind": "emoji_ack",
            "response": "\U0001f44d",
            "reacts_to_message_id": "m1",
        },
        _message(3),
    ]
    await entries_collection.insert_many(
        [
            {
                **{k: v for k, v in fields.items() if k != "message_id"},
                "id": fields.get("message_id", "ack"),
                "seq": seq,
                "at": at,
                "user_id": USER,
                "conversation_id": conversation_id,
            }
            for seq, fields in enumerate(old, 1)
        ]
    )
    assert [
        h.conversation_id
        for h in await migration.heads_with_message_entries(after_head_id=None, batch=5)
    ] == [conversation_id]
    with pytest.raises(UnmigratedConversationError, match="migrate_conversation_entries --apply"):
        await refuse_unmigrated_conversations()

    outcome = await migration.migrate(ref, apply=True)

    assert outcome.action is MigrationAction.MERGED
    entries = await _entries(entries_collection, ref)
    assert [(e["seq"], e["kind"], e["id"]) for e in entries] == [
        (1, "user_message", "m1"),
        (2, "reply", "m2"),
        (3, "reply", "ack"),
        (4, "user_message", "m3"),
        (5, "reply_settled", "m2:settled"),
    ]
    assert not any("type" in e for e in entries)
    assert entries[0]["reaction"] == {"emoji": "\U0001f44d", "by": "chat_model"}
    assert await _history(ref) == [
        ("user", "m1", "message 1"),
        ("bot", "m2", "message 2"),
        ("user", "m3", "message 3"),
    ]
    assert (await _head(raw_collection, ref))["log_head"] == 5
    assert (await migration.verify(ref)).ok
    await refuse_unmigrated_conversations()


async def test_the_boot_check_refuses_an_unmarked_array_cheaply_and_passes_once_migrated(
    migration: ConversationEntriesMigration, raw_collection: Any, entries_collection: Any
) -> None:
    await refuse_unmigrated_conversations()
    await raw_collection.insert_one({"conversation_id": "empty", "user_id": USER, "messages": []})
    await refuse_unmigrated_conversations()
    ref = await _legacy(raw_collection, [_message(1)])

    with pytest.raises(UnmigratedConversationError, match=ref.conversation_id):
        await refuse_unmigrated_conversations()
    await migration.migrate(ref, apply=True)
    await refuse_unmigrated_conversations()

    await raw_collection.create_index(UNMIGRATED_HEAD_KEYS, **UNMIGRATED_HEAD_OPTIONS)
    plans = [
        await raw_collection.find(NEVER_MIGRATED_HEADS).explain(),
        await entries_collection.find(MESSAGE_SHAPED).explain(),
    ]
    assert all("IXSCAN" in str(plan["queryPlanner"]["winningPlan"]) for plan in plans)


async def test_a_dry_run_writes_nothing_and_reports_what_it_would_do(
    migration: ConversationEntriesMigration, raw_collection: Any, entries_collection: Any
) -> None:
    ref = await _legacy(raw_collection, _every_shape())
    before = await _head(raw_collection, ref)

    outcome = await migration.migrate(ref, apply=False)

    assert (outcome.action, outcome.written, outcome.identified) == (MigrationAction.COPIED, 17, 4)
    assert await _head(raw_collection, ref) == before
    assert await _entries(entries_collection, ref) == []


async def test_a_message_that_cannot_become_an_entry_refuses_its_conversation_and_fails_the_run(
    raw_collection: Any, entries_collection: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    ref = await _legacy(raw_collection, [_message(1, selectedTool="not an identifier!")])

    code, out = await _cli(capsys, "--apply")

    assert code == 1 and any(line.startswith("  [refused]") for line in out)
    assert await _entries(entries_collection, ref) == []
    assert "log_head" not in await _head(raw_collection, ref)


_Scan = Callable[[str | None], Awaitable[list[HeadRef]]]


async def test_scans_walk_every_head_in_id_order_one_batch_at_a_time(
    migration: ConversationEntriesMigration, raw_collection: Any
) -> None:
    refs = [await _legacy(raw_collection, [_message(n)]) for n in range(5)]
    seen: list[str] = []
    after: str | None = None
    while batch := await migration.heads_to_migrate(after_head_id=after, batch=2):
        assert len(batch) <= 2
        seen += [ref.conversation_id for ref in batch]
        after = batch[-1].head_id
    assert seen == [ref.conversation_id for ref in refs]


def shown_messages(page: LogPage) -> list[ConversationEntry]:
    """Read a migrated page back in the old array's message shape, as verify does."""
    return legacy_messages([LoggedEntry(seq=f.seq, at=f.at, entry=f.entry) for f in page.entries])
