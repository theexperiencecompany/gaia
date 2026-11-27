"""Contract tests for ConversationRepository.

Business-key identity (conversation_id scoped to user_id), an embedded
messages array, legacy camelCase timestamps, and no cache policy — so this is
a bespoke suite (not the inherited UserScopedRepositoryContract) asserting on
concrete values against real Mongo.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
import uuid

from pydantic import ValidationError
import pytest

from app.db.mongodb import indexes
from app.db.repositories import conversations as conversations_module
from app.db.repositories.conversation_log import conversation_log_repository
from app.db.repositories.conversations import ConversationRepository
from app.models.chat_models import ConversationSource, SystemPurpose
from app.models.conversation_log_models import Entry, Notice, Reply, UserMessage
from app.models.conversation_models import ConversationDocument, ConversationSearchResults
from app.models.conversation_screen_models import UserItem
from app.services.conversation.mongo_log import MongoConversationLog
from shared.py.conversation_wire import ReplyItem, ToolDataEntry
from tests.helpers import local_timezone, shown_items

# Every test here writes entries, so each needs the collection with its unique indexes.
pytestmark = pytest.mark.usefixtures("entries_collection")


def _uid() -> str:
    return f"u-{uuid.uuid4().hex}"


def _cid() -> str:
    return f"c-{uuid.uuid4().hex}"


def _doc(**overrides: object) -> ConversationDocument:
    data: dict[str, object] = {
        "user_id": overrides.pop("user_id", _uid()),
        "conversation_id": overrides.pop("conversation_id", _cid()),
        "description": "New Chat",
        "source": "web",
        "createdAt": datetime.now(UTC).isoformat(),
    }
    data.update(overrides)
    return ConversationDocument.model_validate(data)


def _log() -> MongoConversationLog:
    return MongoConversationLog(conversation_log_repository, lambda: datetime.now(UTC))


async def _say(doc: ConversationDocument, *entries: Entry) -> None:
    """Append each entry to the conversation's log, as the step and the send route do."""
    for entry in entries:
        await _log().append(doc.conversation_id, doc.user_id, entry)


def _asked(text: str) -> UserMessage:
    return UserMessage(id=f"u-{uuid.uuid4().hex}", text=text, surface=ConversationSource.WEB)


def _replied(
    text: str,
    *,
    cards: tuple[ToolDataEntry, ...] = (),
    follow_ups: tuple[str, ...] = (),
    imported: bool = False,
) -> Reply:
    reply_id = f"r-{uuid.uuid4().hex}"
    return Reply(
        id=f"o-{reply_id}",
        reply_id=reply_id,
        attempt_id="a1",
        text=text,
        tool_data=cards,
        follow_up_actions=follow_ups,
        imported=imported,
    )


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

    async def test_create_drops_an_old_embedded_messages_array(self, repo, raw_collection):
        doc = _doc(messages=[{"type": "user", "response": "hi"}])
        await repo.create(doc)
        stored = await raw_collection.find_one({"conversation_id": doc.conversation_id})
        assert stored is not None
        assert "messages" not in stored
        assert stored["log_head"] == 0

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

    async def test_owner_ids_spans_users_and_ignores_other_conversations(self, repo):
        shared, other = _cid(), _cid()
        await repo.create(_doc(user_id="first", conversation_id=shared))
        await repo.create(_doc(user_id="second", conversation_id=shared))
        await repo.create(_doc(user_id="third", conversation_id=other))

        assert await repo.owner_ids(shared) == {"first", "second"}
        assert await repo.owner_ids(_cid()) == set()

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
        """The createdAt ISO string sorts lexicographically, chronological only because every writer emits the same UTC ISO-8601 shape."""
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
    async def test_an_exchange_reads_back_as_its_messages(self, repo):
        doc = _doc()
        await repo.create(doc)
        asked, replied = _asked("hi"), _replied("hello")
        await _say(doc, asked, replied)

        fetched = await repo.get(doc.conversation_id, user_id=doc.user_id)
        assert fetched is not None
        [user, reply] = shown_items(doc.conversation_id, fetched)
        assert isinstance(user, UserItem) and isinstance(reply, ReplyItem)
        assert [(user.id, (user.message.text,)), (reply.id, reply.bubbles)] == [
            (asked.id, ("hi",)),
            (replied.reply_id, ("hello",)),
        ]

    async def test_recent_follow_up_actions_reads_only_gaias_newest_window_deduped(self, repo):
        doc = _doc()
        await repo.create(doc)
        await _say(
            doc,
            # imported, as the entries migration wrote them: two replies need no settle between
            _replied("old", follow_ups=("outside window",), imported=True),
            _replied("a", follow_ups=("Draft", "Plan"), imported=True),
            _asked("q"),
            Notice(
                id=f"n-{uuid.uuid4().hex}",
                text="b",
                origin="test",
                follow_up_actions=("Plan", "Send"),
            ),
        )

        assert await repo.get_recent_follow_up_actions(
            doc.user_id, doc.conversation_id, window=2
        ) == ["Draft", "Plan", "Send"]

    async def test_recent_follow_up_actions_is_scoped_to_the_owner(self, repo):
        doc = _doc()
        await repo.create(doc)
        await _say(doc, _replied("a", follow_ups=("Draft",)))

        assert await repo.get_recent_follow_up_actions(_uid(), doc.conversation_id, window=5) == []
        assert await repo.get_recent_follow_up_actions(doc.user_id, _cid(), window=5) == []

    async def test_a_pinned_reply_is_listed_as_the_item_its_chat_shows(self, repo):
        doc = _doc()
        await repo.create(doc)
        replied = _replied("pin me")
        await _say(doc, _asked("hi"), replied)
        mid = replied.reply_id
        assert await conversation_log_repository.set_pinned(
            doc.conversation_id, user_id=doc.user_id, message_id=mid, pinned=True
        )
        fetched = await repo.get(doc.conversation_id, user_id=doc.user_id)
        assert fetched is not None
        [one] = [item for item in shown_items(doc.conversation_id, fetched) if item.id == mid]
        assert isinstance(one, ReplyItem) and one.pinned is True

        pinned = await repo.list_pinned_messages(doc.user_id)
        assert [(h.conversation_id, h.item) for h in pinned] == [(doc.conversation_id, one)]

    async def test_a_reload_keeps_every_key_emitters_stamp_on_a_cards_entry(self, repo):
        """tool_category/mcp_ui/mcp_server_url/subagent_id are invisible live but break a reload when dropped."""
        doc = _doc()
        await repo.create(doc)
        card: ToolDataEntry = {
            "tool_name": "tool_calls_data",
            "data": {"tool_name": "gmail_send", "tool_call_id": "tc-1"},
            "timestamp": "2026-01-01",
            "tool_category": "gmail",
            "subagent_id": "sa-1",
            "mcp_ui": {"resource_uri": "ui://card"},
            "mcp_server_url": "https://mcp.example.com",
        }
        replied = _replied("r", cards=(card,))
        await _say(doc, _asked("send it"), replied)

        fetched = await repo.get(doc.conversation_id, user_id=doc.user_id)
        assert fetched is not None
        [stored] = [
            item
            for item in shown_items(doc.conversation_id, fetched)
            if item.id == replied.reply_id
        ]
        assert isinstance(stored, ReplyItem)
        entry = stored.tool_data[0]
        assert entry.get("tool_category") == "gmail"
        assert entry.get("subagent_id") == "sa-1"
        assert entry.get("mcp_ui") == {"resource_uri": "ui://card"}
        assert entry.get("mcp_server_url") == "https://mcp.example.com"

    async def test_find_owner_of_message(self, repo):
        doc = _doc()
        await repo.create(doc)
        replied = _replied("owned")
        await _say(doc, _asked("hi"), replied)
        found = await repo.find_owner_of_message(doc.user_id, replied.reply_id)
        assert found == doc.conversation_id
        assert await repo.find_owner_of_message(doc.user_id, "no-such") is None


class TestTrackedTodoChats:
    """A tracked todo's chat: one per todo, reached only from it, never listed anywhere."""

    @pytest.fixture(autouse=True)
    async def _shipped_index(self, raw_collection) -> None:
        await raw_collection.create_index(
            indexes.CONVERSATION_TODO_BINDING_KEYS, **indexes.CONVERSATION_TODO_BINDING_OPTIONS
        )

    async def test_a_todos_chat_is_never_listed_starred_counted_or_searched(self, repo):
        user = _uid()
        chat = _doc(user_id=user, source=ConversationSource.WEB, description="normal")
        todo_chat = _doc(user_id=user, todo_id="todo-1", description="Watch the deploy")
        # Starring or an approval card must not pull it into the sidebar either.
        starred_todo_chat = _doc(user_id=user, todo_id="todo-2", starred=True)
        approval_todo_chat = _doc(
            user_id=user,
            todo_id="todo-3",
            source=ConversationSource.BACKGROUND,
        )
        for doc in (chat, todo_chat, starred_todo_chat, approval_todo_chat):
            await repo.create(doc)
        await _say(todo_chat, _asked("go"), _replied("the deploy is green"))

        active = await repo.list_active_summaries(user, skip=0, limit=10)
        assert [s.conversation_id for s in active] == [chat.conversation_id]
        assert await repo.count_active(user) == 1
        assert await repo.list_starred_summaries(user) == []
        assert await repo.search(user, pattern="deploy") == ConversationSearchResults()

    async def test_the_chat_is_found_by_its_todo_and_the_todo_by_its_chat(self, repo):
        user = _uid()
        todo_chat = _doc(user_id=user, todo_id="todo-1")
        chat = _doc(user_id=user)
        await repo.create(todo_chat)
        await repo.create(chat)

        assert await repo.find_todo_conversation_id(user, "todo-1") == todo_chat.conversation_id
        assert await repo.find_todo_conversation_id(user, "todo-2") is None
        # Another user's todo of the same id is not theirs.
        assert await repo.find_todo_conversation_id(_uid(), "todo-1") is None
        assert await repo.get_todo_id(todo_chat.conversation_id, user_id=user) == "todo-1"
        assert await repo.get_todo_id(chat.conversation_id, user_id=user) is None
        assert await repo.get_todo_id(todo_chat.conversation_id, user_id=_uid()) is None

    async def test_a_second_chat_for_the_same_todo_loses_the_create(self, repo):
        user = _uid()
        assert await repo.try_create(_doc(user_id=user, todo_id="todo-1")) is True
        assert await repo.try_create(_doc(user_id=user, todo_id="todo-1")) is False
        # Unbound chats and another user's chat for that todo id never collide.
        assert await repo.try_create(_doc(user_id=user)) is True
        assert await repo.try_create(_doc(user_id=user)) is True
        assert await repo.try_create(_doc(user_id=_uid(), todo_id="todo-1")) is True

    async def test_a_lookup_by_todo_is_served_by_the_binding_index(self, raw_collection):
        query = {"user_id": "u1", **conversations_module._todo_binding("todo-1")}

        plan = (await raw_collection.find(query).explain())["queryPlanner"]["winningPlan"]

        assert indexes.CONVERSATION_TODO_BINDING_OPTIONS["name"] in str(plan)

    async def test_deleting_todos_deletes_only_their_chats(self, repo):
        user = _uid()
        first = _doc(user_id=user, todo_id="todo-1")
        second = _doc(user_id=user, todo_id="todo-2")
        kept = _doc(user_id=user, todo_id="todo-3")
        chat = _doc(user_id=user)
        foreign = _doc(user_id=_uid(), todo_id="todo-1")
        for doc in (first, second, kept, chat, foreign):
            await repo.create(doc)

        deleted = await repo.delete_for_todos(user, ["todo-1", "todo-2"])

        assert sorted(deleted) == sorted([first.conversation_id, second.conversation_id])
        assert await repo.exists(kept.conversation_id, user_id=user)
        assert await repo.exists(chat.conversation_id, user_id=user)
        assert await repo.exists(foreign.conversation_id, user_id=foreign.user_id)
        assert await repo.delete_for_todos(user, ["todo-9"]) == []

    async def test_retitling_todos_retitles_only_their_chats_and_marks_them_for_sync(self, repo):
        user = _uid()
        bound = _doc(user_id=user, todo_id="todo-1", description="Watch staging")
        other = _doc(user_id=user, todo_id="todo-2", description="Watch canary")
        chat = _doc(user_id=user, description="Watch staging")
        foreign = _doc(user_id=_uid(), todo_id="todo-1", description="Watch staging")
        for doc in (bound, other, chat, foreign):
            await repo.create(doc)
        before = await repo.get(bound.conversation_id, user_id=user)

        await repo.retitle_todo_chats(user, ["todo-1"], "Watch production")

        retitled = await repo.get(bound.conversation_id, user_id=user)
        assert retitled is not None and before is not None
        assert retitled.description == "Watch production"
        # A client syncs a chat by updatedAt, so the new title must move it.
        assert retitled.updatedAt is not None and retitled.updatedAt != before.updatedAt
        for untouched in (other, chat):
            kept = await repo.get(untouched.conversation_id, user_id=user)
            assert kept is not None and kept.description == untouched.description
        kept_foreign = await repo.get(foreign.conversation_id, user_id=foreign.user_id)
        assert kept_foreign is not None and kept_foreign.description == "Watch staging"


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
        assert await repo.find_workflow_conversation_id(doc.user_id, "wf1") == doc.conversation_id
        assert (
            await repo.get_source(doc.conversation_id, user_id=doc.user_id)
            is ConversationSource.WORKFLOW_SYSTEM
        )
        assert await repo.find_workflow_conversation_id(doc.user_id, "missing") is None

    async def test_a_users_system_conversation_is_found_by_its_purpose(self, repo):
        user = _uid()
        briefings = _doc(
            user_id=user, is_system_generated=True, system_purpose=SystemPurpose.BRIEFING
        )
        email = _doc(
            user_id=user, is_system_generated=True, system_purpose=SystemPurpose.EMAIL_PROCESSING
        )
        other_user = _doc(is_system_generated=True, system_purpose=SystemPurpose.BRIEFING)
        plain = _doc(user_id=user)
        for doc in (briefings, email, other_user, plain):
            await repo.create(doc)

        found = await repo.find_system_conversation(user, SystemPurpose.BRIEFING)

        assert found is not None and found.conversation_id == briefings.conversation_id
        assert await repo.find_system_conversation(_uid(), SystemPurpose.BRIEFING) is None

    async def test_is_workflow_execution_only_for_a_workflows_own_conversation(self, repo):
        # The workflow thread reset keys on this: an email or reminder run is
        # system-generated too, and a chat conversation must never match.
        workflow = _doc(is_system_generated=True, system_purpose=SystemPurpose.WORKFLOW_EXECUTION)
        email = _doc(is_system_generated=True, system_purpose=SystemPurpose.EMAIL_PROCESSING)
        chat = _doc()
        for doc in (workflow, email, chat):
            await repo.create(doc)

        assert await repo.is_workflow_execution(workflow.conversation_id) is True
        assert await repo.is_workflow_execution(email.conversation_id) is False
        assert await repo.is_workflow_execution(chat.conversation_id) is False
        assert await repo.is_workflow_execution(_cid()) is False

    async def test_get_source(self, repo):
        doc = _doc(source=ConversationSource.WEB)
        await repo.create(doc)
        assert (
            await repo.get_source(doc.conversation_id, user_id=doc.user_id)
            is ConversationSource.WEB
        )
        assert await repo.get_source(_cid(), user_id=doc.user_id) is None

    async def test_get_source_refuses_a_stored_value_this_build_does_not_know(
        self, repo, raw_collection
    ):
        cid, uid = _cid(), _uid()
        await raw_collection.insert_one(
            {"user_id": uid, "conversation_id": cid, "source": "legacy_garbage"}
        )
        with pytest.raises(ValidationError, match="source"):
            await repo.get_source(cid, user_id=uid)


class TestSearchAndSweeps:
    async def test_search_messages_and_descriptions(self, repo):
        user = _uid()
        doc = _doc(user_id=user, description="grocery list")
        await repo.create(doc)
        replied = _replied("the weather is sunny")
        await _say(doc, _asked("go"), replied)
        fetched = await repo.get(doc.conversation_id, user_id=user)
        assert fetched is not None
        [shown] = [
            item
            for item in shown_items(doc.conversation_id, fetched)
            if item.id == replied.reply_id
        ]
        by_message = await repo.search(user, pattern="weather")
        assert [(h.conversation_id, h.item) for h in by_message.messages] == [
            (doc.conversation_id, shown)
        ]
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

    async def test_all_conversation_ids(self, repo):
        doc = _doc(user_id=_uid())
        await repo.create(doc)
        assert doc.conversation_id in await repo.all_conversation_ids()


_SINCE = datetime(2026, 10, 14, 3, 0, tzinfo=UTC)


async def _said_at(doc: ConversationDocument, minutes: int, entry: Entry) -> None:
    """Append entry to the conversation's log as committed minutes after the cutoff."""
    at = _SINCE + timedelta(minutes=minutes)
    await MongoConversationLog(conversation_log_repository, lambda: at).append(
        doc.conversation_id, doc.user_id, entry
    )


def _on(surface: ConversationSource, text: str = "hi") -> UserMessage:
    return UserMessage(id=f"u-{uuid.uuid4().hex}", text=text, surface=surface)


class TestBotRepliesSince:
    async def _seed(self, repo) -> str:
        user_id = _uid()
        telegram = _doc(user_id=user_id, source=ConversationSource.TELEGRAM)
        whatsapp = _doc(user_id=user_id, source=ConversationSource.WHATSAPP)
        web = _doc(user_id=user_id, source=ConversationSource.WEB)
        someone_else = _doc(source=ConversationSource.TELEGRAM)
        for doc in (telegram, whatsapp, web, someone_else):
            await repo.create(doc)
        await _said_at(telegram, 0, _on(ConversationSource.TELEGRAM, "at the cutoff"))
        await _said_at(telegram, 1, _on(ConversationSource.TELEGRAM, "first"))
        await _said_at(whatsapp, 2, _on(ConversationSource.WHATSAPP, "middle"))
        await _said_at(telegram, 3, _on(ConversationSource.TELEGRAM, "latest"))
        await _said_at(telegram, 4, _replied("gaia's reply"))
        await _said_at(web, 5, _on(ConversationSource.WEB))
        await _said_at(someone_else, 5, _on(ConversationSource.TELEGRAM, "someone else"))
        return user_id

    async def test_lists_the_users_bot_platform_messages_after_the_cutoff_newest_first(self, repo):
        user_id = await self._seed(repo)

        rows = await repo.list_bot_replies_since(user_id, _SINCE, limit=10)

        assert [(row.source, row.text) for row in rows] == [
            ("telegram", "latest"),
            ("whatsapp", "middle"),
            ("telegram", "first"),
        ]

    async def test_the_limit_keeps_the_newest(self, repo):
        user_id = await self._seed(repo)

        rows = await repo.list_bot_replies_since(user_id, _SINCE, limit=1)

        assert [row.text for row in rows] == ["latest"]

    async def test_a_cutoff_in_another_timezone_is_compared_in_utc(self, repo):
        user_id = await self._seed(repo)
        new_york = timezone(timedelta(hours=-5))

        with local_timezone("Asia/Kolkata"):
            rows = await repo.list_bot_replies_since(user_id, _SINCE.astimezone(new_york), limit=10)

        assert len(rows) == 3


async def test_owners_of_maps_each_existing_conversation_to_its_owner(repo):
    alice, bob = _uid(), _uid()
    a_conv, b_conv = _doc(user_id=alice), _doc(user_id=bob)
    await repo.create(a_conv)
    await repo.create(b_conv)
    await repo.create(_doc(user_id=alice))

    owners = await repo.owners_of([a_conv.conversation_id, b_conv.conversation_id, _cid()])

    assert owners == {a_conv.conversation_id: alice, b_conv.conversation_id: bob}
