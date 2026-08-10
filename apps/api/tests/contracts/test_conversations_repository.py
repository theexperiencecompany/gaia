"""Contract tests for ConversationRepository.

Business-key identity (``conversation_id`` scoped to ``user_id``), an embedded
``messages`` array, legacy camelCase timestamps, and no cache policy — so this is
a bespoke suite (not the inherited ``UserScopedRepositoryContract``) asserting on
concrete values against real Mongo.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import uuid

import pytest

from app.db.repositories.conversations import ConversationRepository
from app.models.chat_models import ConversationSource, MessageModel, SystemPurpose
from app.models.conversation_models import ConversationDocument


def _uid() -> str:
    return f"u-{uuid.uuid4().hex}"


def _cid() -> str:
    return f"c-{uuid.uuid4().hex}"


def _doc(**overrides: object) -> ConversationDocument:
    data: dict[str, object] = {
        "user_id": overrides.pop("user_id", _uid()),
        "conversation_id": overrides.pop("conversation_id", _cid()),
        "description": "New Chat",
        "createdAt": datetime.now(UTC).isoformat(),
    }
    data.update(overrides)
    return ConversationDocument.model_validate(data)


@pytest.fixture
def repo(raw_collection) -> ConversationRepository:
    return ConversationRepository()


class TestConversationCrud:
    async def test_create_then_get_roundtrips_by_business_key(self, repo):
        doc = _doc(description="hello")
        created = await repo.create(doc)
        assert created.conversation_id == doc.conversation_id
        fetched = await repo.get(doc.conversation_id, user_id=doc.user_id)
        assert fetched is not None
        assert fetched.conversation_id == doc.conversation_id
        assert fetched.description == "hello"
        # createdAt stays the caller-provided ISO string; _id is not surfaced.
        assert fetched.createdAt == doc.createdAt
        assert fetched.id == ""

    async def test_get_missing_returns_none(self, repo):
        assert await repo.get(_cid(), user_id=_uid()) is None

    async def test_cross_user_isolation(self, repo):
        doc = _doc(user_id="owner", description="secret")
        await repo.create(doc)
        assert await repo.get(doc.conversation_id, user_id="attacker") is None
        assert (
            await repo.set_starred(doc.conversation_id, user_id="attacker", starred=True) is False
        )
        assert await repo.delete(doc.conversation_id, user_id="attacker") is False
        still = await repo.get(doc.conversation_id, user_id="owner")
        assert still is not None and still.starred is None

    async def test_exists(self, repo):
        doc = _doc()
        await repo.create(doc)
        assert await repo.exists(doc.conversation_id, user_id=doc.user_id) is True
        assert await repo.exists(doc.conversation_id, user_id="other") is False
        assert await repo.exists(_cid(), user_id=doc.user_id) is False

    async def test_delete_then_gone(self, repo):
        doc = _doc()
        await repo.create(doc)
        assert await repo.delete(doc.conversation_id, user_id=doc.user_id) is True
        assert await repo.get(doc.conversation_id, user_id=doc.user_id) is None


class TestConversationFieldWrites:
    async def test_set_starred_and_updatedat_bump(self, repo):
        doc = _doc()
        await repo.create(doc)
        assert await repo.set_starred(doc.conversation_id, user_id=doc.user_id, starred=True)
        fetched = await repo.get(doc.conversation_id, user_id=doc.user_id)
        assert fetched is not None and fetched.starred is True
        # updatedAt was absent at create and is now a tz-aware UTC datetime.
        assert fetched.updatedAt is not None
        assert fetched.updatedAt.tzinfo is not None
        assert fetched.updatedAt.utcoffset() == timedelta(0)

    async def test_set_description_and_unread(self, repo):
        doc = _doc()
        await repo.create(doc)
        assert await repo.set_description(
            doc.conversation_id, user_id=doc.user_id, description="renamed"
        )
        assert await repo.set_unread(doc.conversation_id, user_id=doc.user_id, unread=True)
        fetched = await repo.get(doc.conversation_id, user_id=doc.user_id)
        assert fetched is not None
        assert fetched.description == "renamed" and fetched.is_unread is True

    async def test_field_write_missing_returns_false(self, repo):
        assert await repo.set_starred(_cid(), user_id=_uid(), starred=True) is False


class TestListSummaries:
    async def test_active_excludes_starred_and_bot_sources(self, repo):
        user = _uid()
        web = _doc(user_id=user, source=ConversationSource.WEB)
        bot = _doc(user_id=user, source=ConversationSource.TELEGRAM)
        starred = _doc(user_id=user, source=ConversationSource.WEB, starred=True)
        for d in (web, bot, starred):
            await repo.create(d)

        active = await repo.list_active_summaries(user, skip=0, limit=10)
        active_ids = {s.conversation_id for s in active}
        assert web.conversation_id in active_ids
        assert bot.conversation_id not in active_ids  # bot source excluded
        assert starred.conversation_id not in active_ids  # starred excluded
        assert await repo.count_active(user) == 1
        # summary carries the load-bearing user_id and no messages field leak.
        assert all(s.user_id == user for s in active)

        starred_list = await repo.list_starred_summaries(user)
        assert {s.conversation_id for s in starred_list} == {starred.conversation_id}

    async def test_active_pagination(self, repo):
        user = _uid()
        for _ in range(3):
            await repo.create(_doc(user_id=user, source=ConversationSource.WEB))
        page = await repo.list_active_summaries(user, skip=1, limit=1)
        assert len(page) == 1
        assert await repo.count_active(user) == 3

    async def test_both_summary_lists_are_newest_first(self, repo):
        """createdAt descending, for the starred and active lists alike.

        ``createdAt`` is an ISO string, so this is Mongo's lexicographic order —
        chronological only because every writer emits the same UTC ISO-8601
        shape. Seeded oldest-first so an unsorted read would fail here.
        """
        user = _uid()
        base = datetime(2026, 1, 1, tzinfo=UTC)
        ids: dict[str, str] = {}
        for label, hours in (("old", 0), ("mid", 1), ("new", 2)):
            for kind, starred in (("active", None), ("starred", True)):
                doc = _doc(
                    user_id=user,
                    source=ConversationSource.WEB,
                    starred=starred,
                    createdAt=(base + timedelta(hours=hours)).isoformat(),
                )
                await repo.create(doc)
                ids[f"{label}-{kind}"] = doc.conversation_id

        active = await repo.list_active_summaries(user, skip=0, limit=10)
        assert [s.conversation_id for s in active] == [
            ids["new-active"],
            ids["mid-active"],
            ids["old-active"],
        ]

        starred_list = await repo.list_starred_summaries(user)
        assert [s.conversation_id for s in starred_list] == [
            ids["new-starred"],
            ids["mid-starred"],
            ids["old-starred"],
        ]


class TestMessages:
    async def test_append_returns_ids_and_persists(self, repo):
        doc = _doc()
        await repo.create(doc)
        ids = await repo.append_messages(
            doc.conversation_id,
            user_id=doc.user_id,
            messages=[
                MessageModel(type="user", response="hi"),
                MessageModel(type="bot", response="hello"),
            ],
        )
        assert ids is not None and len(ids) == 2
        fetched = await repo.get(doc.conversation_id, user_id=doc.user_id)
        assert fetched is not None
        assert [m.response for m in fetched.messages] == ["hi", "hello"]
        assert [m.message_id for m in fetched.messages] == ids

    async def test_append_missing_conversation_returns_none(self, repo):
        assert (
            await repo.append_messages(
                _cid(), user_id=_uid(), messages=[MessageModel(type="user", response="x")]
            )
            is None
        )

    async def test_append_respects_max_messages_slice(self, repo):
        doc = _doc()
        await repo.create(doc)
        for i in range(3):
            await repo.append_messages(
                doc.conversation_id,
                user_id=doc.user_id,
                messages=[MessageModel(type="user", response=f"m{i}")],
                max_messages=2,
            )
        fetched = await repo.get(doc.conversation_id, user_id=doc.user_id)
        assert fetched is not None
        assert [m.response for m in fetched.messages] == ["m1", "m2"]  # oldest sliced off

    async def test_pin_and_list_and_get_message(self, repo):
        doc = _doc()
        await repo.create(doc)
        ids = await repo.append_messages(
            doc.conversation_id,
            user_id=doc.user_id,
            messages=[MessageModel(type="bot", response="pin me")],
        )
        assert ids is not None
        mid = ids[0]
        assert await repo.set_message_pinned(
            doc.conversation_id, user_id=doc.user_id, message_id=mid, pinned=True
        )
        one = await repo.get_message(doc.conversation_id, mid, user_id=doc.user_id)
        assert one is not None and one.pinned is True

        pinned = await repo.list_pinned_messages(doc.user_id)
        assert [(h.conversation_id, h.message.message_id) for h in pinned] == [
            (doc.conversation_id, mid)
        ]

    async def test_tool_data_and_follow_up_writes(self, repo):
        doc = _doc()
        await repo.create(doc)
        ids = await repo.append_messages(
            doc.conversation_id,
            user_id=doc.user_id,
            messages=[MessageModel(type="bot", response="r")],
        )
        assert ids is not None
        mid = ids[0]
        assert await repo.append_message_tool_data(
            doc.conversation_id,
            user_id=doc.user_id,
            message_id=mid,
            entries=[{"tool_name": "weather", "data": {"t": 1}, "timestamp": "2026-01-01"}],
        )
        assert await repo.set_message_follow_up_actions(
            doc.conversation_id, user_id=doc.user_id, message_id=mid, actions=["do x"]
        )
        msg = await repo.get_message(doc.conversation_id, mid, user_id=doc.user_id)
        assert msg is not None
        assert msg.tool_data is not None and msg.tool_data[0]["tool_name"] == "weather"
        assert msg.follow_up_actions == ["do x"]

    async def test_append_preserves_every_key_emitters_stamp_on_tool_data(self, repo):
        """A persisted tool_data entry keeps the keys the emitters actually set.

        ``append_messages`` writes through ``MessageModel.model_dump()``, which
        drops any key ``ToolDataEntry`` does not declare. ``format_tool_call_entry``
        stamps ``tool_category``/``mcp_ui``/``mcp_server_url`` and the subagent
        path stamps ``subagent_id``; losing them on write is invisible live (the
        SSE frame carries them) and only shows on reload — a tool card rendering
        with the wrong icon and an MCP App that never comes back.
        """
        doc = _doc()
        await repo.create(doc)
        message = MessageModel(type="bot", response="r")
        message.tool_data = [
            {
                "tool_name": "tool_calls_data",
                "data": {"tool_name": "gmail_send", "tool_call_id": "tc-1"},
                "timestamp": "2026-01-01",
                "tool_category": "gmail",
                "subagent_id": "sa-1",
                "mcp_ui": {"resource_uri": "ui://card"},
                "mcp_server_url": "https://mcp.example.com",
            }
        ]
        ids = await repo.append_messages(
            doc.conversation_id, user_id=doc.user_id, messages=[message]
        )
        assert ids is not None

        stored = await repo.get_message(doc.conversation_id, ids[0], user_id=doc.user_id)
        assert stored is not None and stored.tool_data is not None
        entry = stored.tool_data[0]
        assert entry.get("tool_category") == "gmail"
        assert entry.get("subagent_id") == "sa-1"
        assert entry.get("mcp_ui") == {"resource_uri": "ui://card"}
        assert entry.get("mcp_server_url") == "https://mcp.example.com"

    async def test_find_owner_of_message(self, repo):
        doc = _doc()
        await repo.create(doc)
        ids = await repo.append_messages(
            doc.conversation_id,
            user_id=doc.user_id,
            messages=[MessageModel(type="bot", response="owned")],
        )
        assert ids is not None
        found = await repo.find_owner_of_message(doc.user_id, ids[0])
        assert found == doc.conversation_id
        assert await repo.find_owner_of_message(doc.user_id, "no-such") is None


class TestLegacyReadTolerance:
    async def test_get_reads_legacy_message_missing_timestamp_and_legacy_tool_field(
        self, repo, raw_collection
    ):
        # Seed a raw doc bypassing the repository: a message whose tool_data entry
        # predates the timestamp field, plus a legacy per-tool field to convert.
        cid, uid = _cid(), _uid()
        await raw_collection.insert_one(
            {
                "user_id": uid,
                "conversation_id": cid,
                "description": "legacy",
                "createdAt": datetime.now(UTC).isoformat(),
                "messages": [
                    {
                        "type": "bot",
                        "response": "r",
                        "tool_data": [{"tool_name": "old", "data": {}}],  # no timestamp
                        "weather_data": {"temp": 5},  # legacy per-tool field
                    }
                ],
            }
        )
        fetched = await repo.get(cid, user_id=uid)
        assert fetched is not None
        tool_names = {e["tool_name"] for e in (fetched.messages[0].tool_data or [])}
        assert "old" in tool_names and "weather_data" in tool_names  # legacy field folded in


class TestWorkflowAndOnboarding:
    async def test_find_and_bind_workflow_conversation(self, repo):
        doc = _doc(
            is_system_generated=True,
            system_purpose=SystemPurpose.WORKFLOW_EXECUTION,
        )
        await repo.create(doc)
        assert await repo.set_workflow_binding(
            doc.conversation_id, user_id=doc.user_id, workflow_id="wf1", workflow_title="Nightly"
        )
        found = await repo.find_workflow_conversation(doc.user_id, "wf1")
        assert found is not None and found.conversation_id == doc.conversation_id
        assert found.source is ConversationSource.WORKFLOW_SYSTEM
        assert await repo.find_workflow_conversation(doc.user_id, "missing") is None

    async def test_get_source(self, repo):
        doc = _doc(source=ConversationSource.WEB)
        await repo.create(doc)
        assert (
            await repo.get_source(doc.conversation_id, user_id=doc.user_id)
            is ConversationSource.WEB
        )
        assert await repo.get_source(_cid(), user_id=doc.user_id) is None

    async def test_get_source_coerces_unknown_stored_value_to_none(self, repo, raw_collection):
        cid, uid = _cid(), _uid()
        await raw_collection.insert_one(
            {"user_id": uid, "conversation_id": cid, "source": "legacy_garbage"}
        )
        assert await repo.get_source(cid, user_id=uid) is None

    async def test_mark_and_probe_onboarding(self, repo):
        doc = _doc()
        await repo.create(doc)
        await repo.append_messages(
            doc.conversation_id,
            user_id=doc.user_id,
            messages=[MessageModel(type="user", response="hey")],
        )
        assert await repo.mark_onboarding_conversation(doc.conversation_id, user_id=doc.user_id)
        probe = await repo.get_onboarding_probe(doc.conversation_id)
        assert probe is not None
        assert probe.is_onboarding_conversation is True and probe.message_count == 1


class TestSearchAndSweeps:
    async def test_search_messages_and_descriptions(self, repo):
        user = _uid()
        doc = _doc(user_id=user, description="grocery list")
        await repo.create(doc)
        await repo.append_messages(
            doc.conversation_id,
            user_id=user,
            messages=[MessageModel(type="bot", response="the weather is sunny")],
        )
        by_message = await repo.search(user, pattern="weather")
        assert [h.conversation_id for h in by_message.messages] == [doc.conversation_id]
        by_desc = await repo.search(user, pattern="grocery")
        assert [h.conversation_id for h in by_desc.conversations] == [doc.conversation_id]

    async def test_recent_for_user_sorted_desc(self, repo):
        user = _uid()
        first = _doc(user_id=user, createdAt="2026-01-01T00:00:00+00:00")
        second = _doc(user_id=user, createdAt="2026-02-01T00:00:00+00:00")
        await repo.create(first)
        await repo.create(second)
        recent = await repo.recent_for_user(user, limit=10)
        assert [c.conversation_id for c in recent] == [
            second.conversation_id,
            first.conversation_id,
        ]

    async def test_delete_all_for_user_returns_ids(self, repo):
        user = _uid()
        a = _doc(user_id=user)
        b = _doc(user_id=user)
        await repo.create(a)
        await repo.create(b)
        deleted = await repo.delete_all_for_user(user)
        assert set(deleted) == {a.conversation_id, b.conversation_id}
        assert await repo.count_active(user) == 0

    async def test_delete_onboarding_demos(self, repo):
        user = _uid()
        demo = _doc(user_id=user, is_onboarding_demo=True)
        keep = _doc(user_id=user, source=ConversationSource.WEB)
        await repo.create(demo)
        await repo.create(keep)
        assert await repo.delete_onboarding_demos(user) == 1
        assert await repo.get(keep.conversation_id, user_id=user) is not None
        assert await repo.get(demo.conversation_id, user_id=user) is None

    async def test_find_updated_since(self, repo):
        from app.models.chat_models import ConversationSyncItem

        user = _uid()
        past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()

        recent = _doc(user_id=user)
        seen = _doc(user_id=user)
        never = _doc(user_id=user)
        for d in (recent, seen, never):
            await repo.create(d)
        # `recent` and `seen` both get an updatedAt around now.
        await repo.set_starred(recent.conversation_id, user_id=user, starred=True)
        await repo.set_starred(seen.conversation_id, user_id=user, starred=True)

        items = [
            # updatedAt (~now) is after `past` → included.
            ConversationSyncItem(conversation_id=recent.conversation_id, last_updated=past),
            # updatedAt (~now) is before `future` → excluded.
            ConversationSyncItem(conversation_id=seen.conversation_id, last_updated=future),
            # no updatedAt at all → always included, whatever the cutoff.
            ConversationSyncItem(conversation_id=never.conversation_id, last_updated=future),
        ]
        found = {d.conversation_id for d in await repo.find_updated_since(user, items)}
        assert recent.conversation_id in found
        assert never.conversation_id in found
        assert seen.conversation_id not in found

    async def test_all_conversation_ids_and_active_users(self, repo):
        user = _uid()
        doc = _doc(user_id=user)
        await repo.create(doc)
        await repo.set_starred(doc.conversation_id, user_id=user, starred=True)  # sets updatedAt
        assert doc.conversation_id in await repo.all_conversation_ids()
        since = datetime.now(UTC) - timedelta(minutes=5)
        assert user in await repo.active_user_ids_since(since)
