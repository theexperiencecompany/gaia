"""The entries migration against real Mongo: old shapes to log entries, re-runs, races, verify, drop, boot check."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
import uuid

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorCollection
import pytest
from scripts.migrate_approval_vocabulary import rewrite
from scripts.migrate_conversation_entries import __main__ as script
from scripts.migrate_conversation_entries.legacy import ConversationEntry, LegacyMessage
from scripts.migrate_conversation_entries.migration import (
    ConversationEntriesMigration,
    HeadRef,
    MigrationAction,
    expected_messages,
)
from scripts.migrate_conversation_entries.oracle import imported_messages

from app.constants.chat import ConversationSource
from app.db.mongodb.indexes import (
    CONVERSATION_SOURCE_KEYS,
    CONVERSATION_SOURCE_OPTIONS,
    UNMIGRATED_HEAD_KEYS,
    UNMIGRATED_HEAD_OPTIONS,
)
from app.db.repositories.conversation_log import ConversationLogRepository
from app.db.repositories.conversation_migration_guard import (
    MESSAGE_SHAPED,
    SOURCELESS_HEADS,
    UNMIGRATED_HEADS,
    refuse_unmigrated_conversations,
)
from app.db.repositories.conversations import ConversationRepository
from app.models.conversation_log_models import LoggedEntry, UserMessage
from app.models.conversation_models import LogPage
from app.services.conversation.mongo_log_append import LogAppends
from app.services.conversation.reply_files import reply_files
from app.utils.errors import UnmigratedConversationError
from shared.py.conversation_wire import ReplyFile
from tests.contracts.conftest import HeldFlushes
from tests.unit.services.conversation.log_helpers import notice, replied
from tests.unit.services.conversation.runtime_doubles import FakeClock

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


async def _legacy(
    raw_collection: Any, messages: list[dict[str, object]], **head: object
) -> HeadRef:
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
            "source": "web",
            **head,
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


def test_a_legacy_element_is_stored_with_only_the_fields_it_holds() -> None:
    element = LegacyMessage.model_validate({"type": "bot", "response": "hi"})

    assert element.stored() == {"type": "bot", "response": "hi"}


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
    assert report.messages == len(expected_messages(array, datetime.now(UTC))) == 11
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


async def test_a_log_the_new_build_wrote_merges_the_old_builds_later_messages_and_verifies(
    migration: ConversationEntriesMigration,
    raw_collection: Any,
    entries_collection: Any,
    held: HeldFlushes,
) -> None:
    ref = await _legacy(raw_collection, [_message(1), _message(2, "bot", pinned=True)])
    await migration.migrate(ref, apply=True)
    appends = LogAppends(ConversationLogRepository(), FakeClock())
    live = UserMessage(id="live-u", text="live words", surface=ConversationSource.WEB, pinned=True)
    for entry in [live, *replied("live-settled", ["live-u"], 4), notice("live-n")]:
        await appends.append(ref.conversation_id, USER, entry)
    # The live entries are still staged in the head's outbox, as on a running stack.
    held.drop_all()
    # A rollback's old build appends to the array the log already holds.
    await raw_collection.update_one(
        {"_id": ObjectId(ref.head_id)},
        {"$push": {"messages": {"$each": [_message(3), _message(4, "bot", pinned=True)]}}},
    )

    outcome = await migration.migrate(ref, apply=True)

    assert (outcome.action, outcome.written) == (MigrationAction.MERGED, 3)
    ids = [e["id"] for e in await _entries(entries_collection, ref)]
    assert ids == [
        "m1",
        "m2",
        "m2:settled",
        "live-u",
        "live-settled-open",
        "live-settled",
        "live-n",
        "m3",
        "m4",
        "m4:settled",
    ]
    # The live build's own entries stay as the ids above show; the read-back verify checks is the array's.
    assert [m for _, m, _ in await _history(ref)] == ["m1", "m2", "m3", "m4"]
    assert (await migration.verify(ref)).mismatches == []

    entry_of = {"user_id": USER, "conversation_id": ref.conversation_id}
    await entries_collection.update_one({**entry_of, "id": "m3"}, {"$set": {"text": "lost"}})
    report = await migration.verify(ref)
    assert report.mismatches[0].startswith("history differs at message 2")


def _todo_chat() -> list[dict[str, object]]:
    return [
        _message(1, pinned=True),
        _message(2, "bot"),
        _message(3),
        _message(4, "bot", pinned=True),
        _message(5),
        _message(6, "bot", tool_data=[_CARD]),
        _message(7),
        _message(8, "bot"),
    ]


async def _old_build_trims(
    raw_collection: AsyncIOMotorCollection, ref: HeadRef, keep: list[str]
) -> None:
    """Cut the array to the messages a todo chat's append keeps: the pinned ones and the newest."""
    head = await _head(raw_collection, ref)
    kept = [m for m in head["messages"] if m["message_id"] in keep]
    await raw_collection.update_one({"_id": ObjectId(ref.head_id)}, {"$set": {"messages": kept}})


@pytest.mark.regression
async def test_messages_the_old_build_trims_after_a_pass_leave_the_log_and_verify_passes(
    migration: ConversationEntriesMigration,
    raw_collection: AsyncIOMotorCollection,
    entries_collection: AsyncIOMotorCollection,
) -> None:
    ref = await _legacy(raw_collection, _todo_chat())
    await migration.migrate(ref, apply=True)
    await _old_build_trims(raw_collection, ref, ["m1", "m4", "m7", "m8"])
    await raw_collection.update_one(
        {"_id": ObjectId(ref.head_id)},
        {"$push": {"messages": {"$each": [_message(9), _message(10, "bot")]}}},
    )

    outcome = await migration.migrate(ref, apply=True)

    assert outcome.action is MigrationAction.MERGED, outcome.reason
    report = await migration.verify(ref)
    assert report.ok, report.mismatches
    assert [m for _, m, _ in await _history(ref)] == ["m1", "m4", "m7", "m8", "m9", "m10"]
    entries = await _entries(entries_collection, ref)
    assert [e["seq"] for e in entries] == list(range(1, len(entries) + 1))
    by_id = {e["id"]: e for e in entries}
    for gone in ("m2", "m3", "m5", "m6", "m2:settled", "m6:settled"):
        assert (by_id[gone]["kind"], by_id[gone]["text"], by_id[gone].get("tool_data")) == (
            "reply",
            "",
            [],
        )
    for words in ("message 3", "message 6"):
        assert (await ConversationRepository().search(USER, pattern=words)).messages == []
    assert (await migration.migrate(ref, apply=True)).action is MigrationAction.UNCHANGED
    assert await _entries(entries_collection, ref) == entries


_APPROVAL = {"tool_name": "approval_request", "data": {"status": "pending", "tool": "send_email"}}
_EDITS: dict[str, tuple[dict[str, object], list[dict[str, object]] | None]] = {
    "response": ({"messages.$[m].response": "edited"}, None),
    "tool_data": ({"messages.$[m].tool_data": [_CARD, _CARD]}, None),
    "follow_up_actions": ({"messages.$[m].follow_up_actions": ["again"]}, None),
    "pinned": ({"messages.$[m].pinned": True}, None),
    "approval status": (
        {"messages.$[m].tool_data.$[t].data.status": "executed"},
        [{"t.tool_name": "approval_request"}],
    ),
}


@pytest.mark.parametrize("edit", sorted(_EDITS))
async def test_each_in_place_edit_the_old_build_makes_after_a_pass_is_rewritten_and_verifies(
    migration: ConversationEntriesMigration, raw_collection: Any, edit: str
) -> None:
    bot = _message(2, "bot", tool_data=[_APPROVAL], follow_up_actions=["more"])
    ref = await _legacy(raw_collection, [_message(1), bot, _message(3), _message(4, "bot")])
    await migration.migrate(ref, apply=True)
    change, card_filter = _EDITS[edit]
    await raw_collection.update_one(
        {"_id": ObjectId(ref.head_id)},
        {"$set": change},
        array_filters=[{"m.message_id": "m2"}, *(card_filter or [])],
    )

    outcome = await migration.migrate(ref, apply=True)

    assert (outcome.action, outcome.written) == (MigrationAction.MERGED, 0), outcome.reason
    report = await migration.verify(ref)
    assert report.ok, report.mismatches


@pytest.mark.regression
async def test_a_trim_after_the_new_build_wrote_leaves_every_live_entry_as_it_was(
    migration: ConversationEntriesMigration,
    raw_collection: AsyncIOMotorCollection,
    entries_collection: AsyncIOMotorCollection,
    held: HeldFlushes,
) -> None:
    ref = await _legacy(raw_collection, _todo_chat())
    await migration.migrate(ref, apply=True)
    appends = LogAppends(ConversationLogRepository(), FakeClock())
    live = UserMessage(id="live-u", text="live words", surface=ConversationSource.WEB)
    for entry in [live, *replied("live-settled", ["live-u"], 13), notice("live-n")]:
        await appends.append(ref.conversation_id, USER, entry)
    held.drop_all()
    await migration.flush_outbox(ref.conversation_id, user_id=USER)
    live_before = [
        e for e in await _entries(entries_collection, ref) if e["id"].startswith("live-")
    ]
    # A rollback's old build trims the array the log already holds.
    await _old_build_trims(raw_collection, ref, ["m1", "m7", "m8"])

    outcome = await migration.migrate(ref, apply=True)

    assert outcome.action is MigrationAction.MERGED, outcome.reason
    live_after = [e for e in await _entries(entries_collection, ref) if e["id"].startswith("live-")]
    assert live_after == live_before
    report = await migration.verify(ref)
    assert report.ok, report.mismatches


async def test_an_old_message_holding_the_id_of_a_live_entry_refuses_and_leaves_it_whole(
    migration: ConversationEntriesMigration, raw_collection: Any, entries_collection: Any
) -> None:
    ref = await _legacy(raw_collection, [_message(1), _message(2, "bot")])
    await migration.migrate(ref, apply=True)
    await LogAppends(ConversationLogRepository(), FakeClock()).append(
        ref.conversation_id, USER, notice("m3")
    )
    await raw_collection.update_one(
        {"_id": ObjectId(ref.head_id)}, {"$push": {"messages": _message(3)}}
    )
    before = await _entries(entries_collection, ref)

    outcome = await migration.migrate(ref, apply=True)

    assert outcome.action is MigrationAction.REFUSED
    assert "m3" in outcome.reason
    assert await _entries(entries_collection, ref) == before


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
        {"conversation_id": conversation_id, "user_id": USER, "source": "web", "log_head": 4}
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
    with pytest.raises(UnmigratedConversationError) as refused:
        await refuse_unmigrated_conversations()
    assert refused.value.message == (
        f"conversation {conversation_id} still holds messages in the old shape: run "
        "python -m scripts.migrate_conversation_entries --apply, then --verify"
    )

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
    await raw_collection.insert_one(
        {"conversation_id": "empty", "user_id": USER, "source": "web", "messages": []}
    )
    await refuse_unmigrated_conversations()
    ref = await _legacy(raw_collection, [_message(1)])

    with pytest.raises(UnmigratedConversationError, match=ref.conversation_id):
        await refuse_unmigrated_conversations()
    await migration.migrate(ref, apply=True)
    await refuse_unmigrated_conversations()

    await raw_collection.create_index(UNMIGRATED_HEAD_KEYS, **UNMIGRATED_HEAD_OPTIONS)
    plans = [
        await raw_collection.find(UNMIGRATED_HEADS).explain(),
        await entries_collection.find(MESSAGE_SHAPED).explain(),
    ]
    winning = [str(plan["queryPlanner"]["winningPlan"]) for plan in plans]
    assert all("IXSCAN" in w and "COLLSCAN" not in w for w in winning)


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
    """Read a migrated page's imported messages back in the old array's shape, as verify does."""
    return imported_messages([LoggedEntry(seq=f.seq, at=f.at, entry=f.entry) for f in page.entries])


@pytest.mark.parametrize("field", ["summary", "decision", "heard_text", "run.reservation"])
async def test_the_boot_check_names_an_entry_holding_a_renamed_field_and_its_migration(
    entries_collection: Any, field: str
) -> None:
    await entries_collection.insert_one(
        {"user_id": USER, "conversation_id": "c-current", "seq": 1, "id": "e1", "kind": "reply"}
    )
    await refuse_unmigrated_conversations()
    head, _, leaf = field.rpartition(".")
    stored: dict[str, object] = {leaf: "old"}
    renamed = {head: stored} if head else stored
    await entries_collection.insert_one(
        {"user_id": USER, "conversation_id": "c-renamed", "seq": 1, "id": "e2", **renamed}
    )

    with pytest.raises(UnmigratedConversationError) as refused:
        await refuse_unmigrated_conversations()
    assert refused.value.message == (
        "conversation c-renamed still holds log entries with renamed fields: run "
        "python -m scripts.migrate_approval_vocabulary --apply, then --verify"
    )


async def test_every_head_without_a_source_is_given_its_own_kind_and_verify_fails_until_then(
    raw_collection: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    web = await _legacy(raw_collection, [], source=None)
    unknown = await _legacy(raw_collection, [], source="sms")
    todo = await _legacy(raw_collection, [], source=None, todo_id="t1")
    bound = await _legacy(raw_collection, [], source=None, metadata={"workflow_id": "wf1"})
    workflow = await _legacy(raw_collection, [], source=None, system_purpose="workflow_execution")
    telegram = await _legacy(raw_collection, [], source="telegram")

    code, out = await _cli(capsys)
    assert code == 0
    assert "Sources: 1 given background, 2 given workflow_system, 2 given web." in out
    assert (await _head(raw_collection, web))["source"] is None
    code, out = await _cli(capsys, "--verify")
    assert code == 1 and out[-1] == "5 conversations have no source."
    with pytest.raises(UnmigratedConversationError, match="no source"):
        await refuse_unmigrated_conversations()

    assert (await _cli(capsys, "--apply"))[0] == 0
    sources = {
        ref.conversation_id: (await _head(raw_collection, ref)).get("source")
        for ref in (web, unknown, todo, bound, workflow, telegram)
    }
    assert sources == {
        web.conversation_id: "web",
        unknown.conversation_id: "web",
        todo.conversation_id: "background",
        bound.conversation_id: "workflow_system",
        workflow.conversation_id: "workflow_system",
        telegram.conversation_id: "telegram",
    }
    code, out = await _cli(capsys, "--verify")
    assert code == 0 and out[-1] == "0 conversations have no source."
    await refuse_unmigrated_conversations()


async def test_the_boot_check_names_a_sourceless_head_and_its_migration(
    raw_collection: Any,
) -> None:
    sourceless = await _legacy(raw_collection, [], source=None)

    with pytest.raises(UnmigratedConversationError) as refused:
        await refuse_unmigrated_conversations()
    assert refused.value.message == (
        f"conversation {sourceless.conversation_id} still holds no source: run "
        "python -m scripts.migrate_conversation_entries --apply, then --verify"
    )


async def test_the_boot_check_finds_a_sourceless_head_through_an_index(raw_collection: Any) -> None:
    await raw_collection.create_index(CONVERSATION_SOURCE_KEYS, **CONVERSATION_SOURCE_OPTIONS)

    plan = await raw_collection.find(SOURCELESS_HEADS).explain()

    assert "IXSCAN" in str(plan["queryPlanner"]["winningPlan"])


_STARTED = "2025-12-31T08:00:00+00:00"


async def _bson_size(raw_collection: Any, ref: HeadRef) -> int:
    [row] = await raw_collection.aggregate(
        [{"$match": {"_id": ObjectId(ref.head_id)}}, {"$project": {"n": {"$bsonSize": "$$ROOT"}}}]
    ).to_list(None)
    return int(row["n"])


async def _at_the_size_limit(raw_collection: Any, *, spare: int) -> HeadRef:
    """Insert a head of 64 messages whose BSON size is spare bytes under Mongo's 16 MB limit."""
    limit, pairs = 16 * 1024 * 1024, 32
    chunk = limit // (2 * pairs) - 400
    messages = [
        _message(n, "user" if n % 2 else "bot", response="x" * chunk)
        for n in range(1, 2 * pairs + 1)
    ]
    ref = await _legacy(raw_collection, messages)
    short = limit - spare - await _bson_size(raw_collection, ref)
    await raw_collection.update_one(
        {"_id": ObjectId(ref.head_id)}, {"$set": {"messages.0.response": "x" * (chunk + short)}}
    )
    assert await _bson_size(raw_collection, ref) == limit - spare
    return ref


async def test_a_head_too_full_for_the_log_pointer_moves_its_array_aside_and_still_verifies(
    raw_collection: Any, entries_collection: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    full = await _at_the_size_limit(raw_collection, spare=70)
    small = await _legacy(raw_collection, [_message(1), _message(2, "bot")])

    code, out = await _cli(capsys, "--apply")

    assert code == 0, out
    assert any(full.conversation_id in line and "moved to the archive" in line for line in out)
    head = await _head(raw_collection, full)
    assert "messages" not in head and isinstance(head["messages_archived"], int)
    assert head["log_head"] == 96 and await _bson_size(raw_collection, full) < 1024
    assert len(await _entries(entries_collection, small)) == 3
    assert (await _cli(capsys, "--verify"))[0] == 0
    await refuse_unmigrated_conversations()
    code, out = await _cli(capsys, "--apply")
    assert code == 0 and not any(full.conversation_id in line for line in out)

    entry_of = {"user_id": USER, "conversation_id": full.conversation_id}
    await entries_collection.update_one({**entry_of, "id": "m3"}, {"$set": {"text": "lost"}})
    code, out = await _cli(capsys, "--verify")
    assert code == 1 and any(f"MISMATCH {full.conversation_id}: history" in line for line in out)


async def test_an_archived_head_the_catch_up_plans_again_keeps_every_archived_message(
    migration: ConversationEntriesMigration,
    raw_collection: AsyncIOMotorCollection,
    entries_collection: AsyncIOMotorCollection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    full = await _at_the_size_limit(raw_collection, spare=70)
    assert (await migration.migrate(full, apply=True)).relocated
    archived = await _entries(entries_collection, full)
    # A retry of a recorded failure plans the head again with no array on it.
    await migration.mark_failed(full, "verify: 1 mismatches")

    assert await script.catch_up() == 0

    assert await _entries(entries_collection, full) == archived
    # The old build appends to the head whose array the pass moved aside.
    await raw_collection.update_one(
        {"_id": ObjectId(full.head_id)},
        {"$push": {"messages": {"$each": [_message(65), _message(66, "bot")]}}},
    )
    assert await script.catch_up() == 0
    entries = await _entries(entries_collection, full)
    assert entries[: len(archived)] == archived
    assert [e["id"] for e in entries[len(archived) :]] == ["m65", "m66", "m66:settled"]
    assert (await migration.verify(full)).ok
    await refuse_unmigrated_conversations()
    capsys.readouterr()


async def test_a_head_with_room_keeps_its_array_and_is_only_marked(
    migration: ConversationEntriesMigration, raw_collection: Any
) -> None:
    roomy = await _at_the_size_limit(raw_collection, spare=2048)

    outcome = await migration.migrate(roomy, apply=True)

    assert (outcome.action, outcome.relocated) == (MigrationAction.COPIED, False)
    head = await _head(raw_collection, roomy)
    assert len(head["messages"]) == 64 and "messages_archived" not in head
    assert (await migration.verify(roomy)).ok


async def test_a_conversation_whose_write_fails_is_reported_left_whole_and_refused_at_boot(
    raw_collection: Any, entries_collection: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    good = await _legacy(raw_collection, [_message(1), _message(2, "bot")])
    bad = await _legacy(raw_collection, [_message(1), _message(2, "bot")])
    assert (await _cli(capsys, "--apply"))[0] == 0
    for ref in (good, bad):
        await raw_collection.update_one(
            {"_id": ObjectId(ref.head_id)},
            {"$push": {"messages": {"$each": [_message(3), _message(4, "bot")]}}},
        )
    # The server rejects this one conversation's head write, as it rejected the 16 MB head's.
    rejects_bad = {
        "$or": [{"conversation_id": {"$ne": bad.conversation_id}}, {"log_head": {"$lte": 3}}]
    }
    await raw_collection.database.command("collMod", raw_collection.name, validator=rejects_bad)

    code, out = await _cli(capsys, "--apply")

    assert code == 1
    assert any(
        line.startswith(f"  [failed] {bad.conversation_id}: ConversationStoreError") for line in out
    )
    assert len(await _entries(entries_collection, good)) == 6
    assert [e["seq"] for e in await _entries(entries_collection, bad)] == [1, 2, 3]
    with pytest.raises(UnmigratedConversationError) as refused:
        await refuse_unmigrated_conversations()
    assert refused.value.message.startswith(
        f"conversation {bad.conversation_id} still holds a failed migration pass or verify"
    )

    await raw_collection.database.command("collMod", raw_collection.name, validator={})
    assert (await _cli(capsys, "--apply"))[0] == 0
    assert len(await _entries(entries_collection, bad)) == 6
    await refuse_unmigrated_conversations()
    assert (await _cli(capsys, "--verify"))[0] == 0


async def test_a_card_from_a_per_tool_field_is_stamped_with_its_message_time_so_verify_can_pass(
    migration: ConversationEntriesMigration, raw_collection: Any, entries_collection: Any
) -> None:
    undated: dict[str, object] = {
        "type": "bot",
        "response": "sunny",
        "message_id": "m3",
        "weather_data": {"t": 21},
    }
    ref = await _legacy(
        raw_collection,
        [_message(1), _message(2, "bot", search_results={"q": "x"}), undated],
        createdAt=_STARTED,
    )

    await migration.migrate(ref, apply=True)

    by_id = {e["id"]: e for e in await _entries(entries_collection, ref)}
    assert [c["timestamp"] for c in by_id["m2"]["tool_data"]] == [_DATE]
    assert [c["timestamp"] for c in by_id["m3"]["tool_data"]] == [_STARTED]
    report = await migration.verify(ref)
    assert report.ok, report.mismatches


async def test_an_undated_card_in_a_head_with_no_creation_date_takes_the_heads_id_time(
    migration: ConversationEntriesMigration, raw_collection: Any, entries_collection: Any
) -> None:
    undated: dict[str, object] = {
        "type": "bot",
        "response": "sunny",
        "message_id": "m2",
        "weather_data": {"t": 21},
    }
    ref = await _legacy(raw_collection, [_message(1), undated], createdAt=None)

    await migration.migrate(ref, apply=True)

    reply = await entries_collection.find_one({"conversation_id": ref.conversation_id, "id": "m2"})
    [card] = reply["tool_data"]
    assert datetime.fromisoformat(card["timestamp"]) == ObjectId(ref.head_id).generation_time
    assert (await migration.verify(ref)).ok


async def test_the_upload_ids_on_a_bot_message_are_kept_and_verify_compares_them(
    migration: ConversationEntriesMigration, raw_collection: Any, entries_collection: Any
) -> None:
    ref = await _legacy(
        raw_collection, [_message(1, fileIds=["f9"]), _message(2, "bot", fileIds=["f9"])]
    )

    await migration.migrate(ref, apply=True)

    entry_of = {"user_id": USER, "conversation_id": ref.conversation_id}
    assert (await entries_collection.find_one({**entry_of, "id": "m2"}))["file_ids"] == ["f9"]
    assert (await migration.verify(ref)).ok
    await entries_collection.update_one({**entry_of, "id": "m2"}, {"$set": {"file_ids": []}})
    assert (await migration.verify(ref)).mismatches[0].startswith("history differs at message 1")


async def test_an_artifact_card_from_the_first_artifacts_build_reads_as_the_file_it_wrote(
    migration: ConversationEntriesMigration, raw_collection: Any, entries_collection: Any
) -> None:
    path = "/sessions/c1/.user-visible/report.md"
    written = {
        "path": path,
        "filename": "report.md",
        "content_type": "text/markdown",
        "size_bytes": 12,
    }
    card = {"tool_name": "artifact_data", "data": written, "timestamp": _DATE}
    ref = await _legacy(raw_collection, [_message(1), _message(2, "bot", tool_data=[card])])

    await migration.migrate(ref, apply=True)

    reply = await entries_collection.find_one({"conversation_id": ref.conversation_id, "id": "m2"})
    assert reply["tool_data"][0]["data"] == {**written, "event": "upsert"}
    assert reply_files(reply["tool_data"], "page") == (
        ReplyFile(path=path, content_type="text/markdown", opens_at="page"),
    )
    report = await migration.verify(ref)
    assert report.ok, report.mismatches
    assert await _history(ref) == [("user", "m1", "message 1"), ("bot", "m2", "message 2")]


async def test_a_conversation_verify_cannot_read_is_reported_and_the_rest_still_verified(
    raw_collection: Any, entries_collection: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    good = await _legacy(raw_collection, [_message(1), _message(2, "bot")])
    bad = await _legacy(raw_collection, [_message(1), _message(2, "bot")])
    assert (await _cli(capsys, "--apply"))[0] == 0
    await entries_collection.update_one(
        {"conversation_id": bad.conversation_id, "id": "m1"}, {"$set": {"kind": "unknown"}}
    )

    code, out = await _cli(capsys, "--verify")

    assert code == 1
    assert any(line.startswith(f"  MISMATCH {bad.conversation_id}: crashed: ") for line in out)
    assert not any(good.conversation_id in line for line in out)
    assert "Verified 2 conversations: 1 with mismatches." in out


async def test_restoring_an_archived_head_gives_back_the_original_head_and_it_migrates_again(
    raw_collection: Any, entries_collection: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    full = await _at_the_size_limit(raw_collection, spare=70)
    original = await _head(raw_collection, full)
    assert (await _cli(capsys, "--apply"))[0] == 0
    archived = await _head(raw_collection, full)
    assert "messages" not in archived

    code, out = await _cli(capsys, "--restore-archived")
    assert code == 0 and out[-2:] == [
        "Restore: 1 restored.",
        "Dry run only. Re-run with --apply to write.",
    ]
    assert await _head(raw_collection, full) == archived

    assert (await _cli(capsys, "--restore-archived", "--apply"))[0] == 0
    restored = await _head(raw_collection, full)
    assert {k: v for k, v in restored.items() if k != "updatedAt"} == {
        k: v for k, v in original.items() if k != "updatedAt"
    }
    archive = raw_collection.database[f"{raw_collection.name}_conversation_archived_messages"]
    assert await archive.count_documents({}) == 0
    code, out = await _cli(capsys, "--restore-archived", "--apply")
    assert code == 0 and out[0] == "Restore: nothing archived."
    assert await _head(raw_collection, full) == restored

    assert (await _cli(capsys, "--apply"))[0] == 0
    assert (await _cli(capsys, "--verify"))[0] == 0


async def test_an_archived_head_that_no_longer_fits_its_array_is_reported_and_left_archived(
    raw_collection: Any, entries_collection: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    full = await _at_the_size_limit(raw_collection, spare=70)
    assert (await _cli(capsys, "--apply"))[0] == 0
    await raw_collection.update_one(
        {"_id": ObjectId(full.head_id)}, {"$set": {"description": "x" * 4096}}
    )
    before = await _head(raw_collection, full)

    code, out = await _cli(capsys, "--restore-archived", "--apply")

    assert code == 1
    assert any(
        line.startswith(f"  [too_large] {full.conversation_id}: 64 messages") for line in out
    )
    assert await _head(raw_collection, full) == before
    assert (await _cli(capsys, "--verify"))[0] == 0


class _Database:
    """The database the vocabulary rewrite takes, with each collection this test's own."""

    def __init__(self, raw_collection: Any, entries_collection: Any) -> None:
        self._raw, self._entries = raw_collection, entries_collection

    def __getitem__(self, name: str) -> Any:
        if name == "conversation_entries":
            return self._entries
        return self._raw.database[f"{self._raw.name}_{name}"]


async def test_an_old_approval_card_reads_in_the_new_vocabulary_whichever_migration_runs_first(
    migration: ConversationEntriesMigration, raw_collection: Any, entries_collection: Any
) -> None:
    old = {"tool_name": "approval_request", "data": {"status": "executed", "tool": "send_email"}}
    ref = await _legacy(raw_collection, [_message(1), _message(2, "bot", tool_data=[old])])
    # The same old card as an earlier build of this stack stored it on an entry.
    await entries_collection.insert_one(
        {
            "user_id": USER,
            "conversation_id": "c-earlier",
            "seq": 1,
            "id": "e1",
            "kind": "reply",
            "tool_data": [old],
        }
    )
    await rewrite(_Database(raw_collection, entries_collection), apply=True)
    rewritten = (await entries_collection.find_one({"id": "e1"}))["tool_data"][0]["data"]
    await entries_collection.delete_one({"id": "e1"})

    await migration.migrate(ref, apply=True)

    reply = await entries_collection.find_one({"conversation_id": ref.conversation_id, "id": "m2"})
    assert reply["tool_data"][0]["data"] == rewritten
    assert rewritten == {
        "tool": "send_email",
        "outcome": "approved",
        "decider": "user",
        "action": "executed",
    }
    report = await rewrite(_Database(raw_collection, entries_collection), apply=True)
    assert report.counts["card status=executed"] == 0
    verified = await migration.verify(ref)
    assert verified.ok, verified.mismatches


async def test_a_conversation_verify_finds_wrong_is_refused_at_boot_until_it_verifies(
    raw_collection: Any, entries_collection: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    ref = await _legacy(raw_collection, [_message(1), _message(2, "bot")])
    assert (await _cli(capsys, "--apply"))[0] == 0
    entry_of = {"user_id": USER, "conversation_id": ref.conversation_id, "id": "m1"}
    await entries_collection.update_one(entry_of, {"$set": {"text": "tampered"}})

    assert (await _cli(capsys, "--verify"))[0] == 1

    with pytest.raises(UnmigratedConversationError, match=ref.conversation_id):
        await refuse_unmigrated_conversations()
    await entries_collection.update_one(entry_of, {"$set": {"text": "message 1"}})
    assert (await _cli(capsys, "--verify"))[0] == 0
    await refuse_unmigrated_conversations()
