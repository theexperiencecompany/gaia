"""Behavior spec for app/services/conversation_service.py (persistence, P0 critical-path).

This module is the MongoDB-backed CRUD layer for conversations. Every function takes
the authenticated ``user`` dict (or a ``user_id``) and translates a request into an
exact Motor query against ``conversations_collection``, then shapes the DB result into
the dict the API layer returns to the client. The web/mobile/bot clients depend on the
precise filter keys, update operators, projection fields, status codes and return shapes.

MECHANISM: each service builds a filter/update/pipeline dict, awaits a mocked Motor
collection method, branches on the driver result (acknowledged / modified_count /
deleted_count / find_one truthiness), and either raises HTTPException or returns a dict.
The only I/O boundary is ``conversations_collection`` (Motor) and two pure transform
helpers (``convert_conversation_messages`` / ``convert_legacy_tool_data``) — patched in
or exercised for real as appropriate. No network/LLM.

MUST-CATCH (each maps to >=1 test and >=1 killed mutant):

create_conversation_service:
  - missing user_id -> HTTP 403 "Not authenticated" (auth guard before any DB write)
  - the inserted document carries user_id, conversation_id, description, messages=[],
    is_system_generated/is_unread defaulting to False, and source serialized to its
    string .value (bot) or None (web) — the $nin source filter contract depends on it
  - insert raising -> HTTP 500 with the error embedded
  - insert not acknowledged -> HTTP 500
  - success returns conversation_id, user_id and "Conversation created successfully"

get_conversations:
  - every find() filter AND count_documents filter is scoped to the caller's user_id
  - the $nin source filter excludes exactly the four bot sources on every query
  - starred filter requires starred==True; non-starred filter matches missing-or-False
  - both cursors sort createdAt descending (-1); non-starred applies skip=(page-1)*limit
    and limit; the projection includes the documented fields
  - total = len(starred)+non_starred_count; total_pages = ceil(count/limit) or 1 when 0
  - _id is stringified on every returned conversation

get_conversation:
  - filter is scoped to {user_id, conversation_id} (ownership)
  - missing doc -> HTTP 404; success stringifies _id and runs convert_conversation_messages

star_conversation:
  - update sets {"starred": <bool>} and bumps updatedAt; filter scoped to user
  - modified_count==0 -> HTTP 404; success echoes the starred flag

delete_all_conversations / delete_conversation:
  - filter scoped to user (and conversation_id for the single delete)
  - deleted_count==0 -> HTTP 404; success message + conversation_id

update_messages:
  - each message stripped of None fields and given a message_id if absent
  - the $push uses $each with the built messages; updatedAt bumped; filter scoped to user
  - modified_count==0 -> HTTP 404; success returns modified_count + message_ids

pin_message:
  - missing conversation -> 404; message not in conversation -> 404; update no-op -> 404
  - the update sets messages.$.pinned to the requested bool, filtered on messages.message_id
  - success message says pinned/unpinned to match the flag

get_starred_messages:
  - aggregation matches user, unwinds messages, keeps pinned==True, projects message
  - each returned message runs through convert_legacy_tool_data; empty -> []

create_system_conversation:
  - persists user_id, messages=[], is_system_generated True; not acknowledged/raise -> 500
  - success returns the purpose, description and "System conversation created successfully"

get_or_create_system_conversation:
  - existing doc -> returned with stringified _id, no insert
  - missing -> creates with the purpose-mapped description, or the caller's override,
    or the "System: <Title>" fallback for an unmapped purpose

update_conversation_description:
  - update sets {"description": ...}; modified_count==0 -> 404; success echoes description

mark_conversation_as_read / mark_conversation_as_unread:
  - missing user_id -> 403; read sets is_unread False (no 404 branch — fire and forget);
    unread sets is_unread True and 404s on no match

batch_sync_conversations:
  - missing user_id -> 403; empty conversations -> {"conversations": []} with no DB call
  - a valid last_updated builds an $or(updatedAt > dt OR not exists); invalid timestamp
    is swallowed so the conversation is still matched; datetimes serialized to ISO

_convert_datetime_to_iso / _convert_ids:
  - datetime fields -> isoformat in place; non-datetime/missing untouched; _id stringified

EQUIVALENT MUTANTS (allowed survivors, justified):
  - get_or_create_system_conversation description_map keys "task_automation" and
    "system_notifications": SystemPurpose has no such members, so those branches are
    unreachable from any real caller (system_purpose is typed SystemPurpose). const_str
    mutations on those two keys cannot change behavior. Proven by the enum definition.
  - get_conversations total_pages guard `non_starred_count > 0` -> `> 1` (const_int
    0->1): the two predicates produce IDENTICAL total_pages for every count/limit, because
    they only diverge at count==1, where the ceil formula already equals the else branch
    (1). Proven exhaustively over count in [0,200) x limit in [1,50): zero divergences.
  - batch_sync_conversations `if not match_conditions: return {"conversations": []}`
    (L528-529): dead code. After the early empty-map return, the build loop always appends
    one condition per mapped conversation, so match_conditions is never empty here. The
    return_none / const_str mutations on this unreachable branch cannot change behavior.
  - Function docstrings (const_str -> '' on the triple-quoted function docstrings):
    behavior-preserving by definition.
"""

from datetime import UTC, datetime

from bson import ObjectId
from fastapi import HTTPException
import pytest

from app.models.chat_models import (
    BatchSyncRequest,
    ConversationModel,
    ConversationSource,
    ConversationSyncItem,
    MessageModel,
    SystemPurpose,
    UpdateMessagesRequest,
)
from app.services.conversation_service import (
    _convert_datetime_to_iso,
    _convert_ids,
    batch_sync_conversations,
    create_conversation_service,
    create_system_conversation,
    delete_all_conversations,
    delete_conversation,
    get_conversation,
    get_conversations,
    get_or_create_system_conversation,
    get_starred_messages,
    mark_conversation_as_read,
    mark_conversation_as_unread,
    pin_message,
    star_conversation,
    update_conversation_description,
    update_messages,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fakes for the only I/O boundary: the Motor conversations_collection.
# These are deterministic in-memory doubles, not mocks-that-assert-called. They
# record the exact args the service passed so tests assert the real query shape.
# ---------------------------------------------------------------------------


class FakeCursor:
    """Chainable async cursor mirroring Motor's find().sort().skip().limit().to_list()."""

    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs
        self.sort_args: tuple | None = None
        self.skip_arg: int | None = None
        self.limit_arg: int | None = None
        self.to_list_arg: object = "UNSET"

    def sort(self, *args):
        self.sort_args = args
        return self

    def skip(self, n):
        self.skip_arg = n
        return self

    def limit(self, n):
        self.limit_arg = n
        return self

    async def to_list(self, length):
        self.to_list_arg = length
        return self._docs


class FakeAggCursor:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    async def to_list(self, length):
        return self._docs


class FakeResult:
    def __init__(self, **kwargs) -> None:
        self.__dict__.update(kwargs)


class FakeCollection:
    """Records every call's args and returns pre-seeded results."""

    def __init__(self) -> None:
        self.find_calls: list[tuple] = []
        self.find_cursors: list[FakeCursor] = []
        self._find_queue: list[FakeCursor] = []
        self.count_calls: list[dict] = []
        self._count_return = 0
        self.find_one_calls: list[dict] = []
        self._find_one_return: dict | None = None
        self._find_one_error: Exception | None = None
        self.insert_calls: list[dict] = []
        self._insert_result: FakeResult | None = None
        self._insert_error: Exception | None = None
        self.update_calls: list[tuple] = []
        self._update_result: FakeResult | None = None
        self.delete_one_calls: list[dict] = []
        self.delete_many_calls: list[dict] = []
        self._delete_result: FakeResult | None = None
        self.aggregate_calls: list[list] = []
        self._aggregate_return: list[dict] = []

    def find(self, query, projection=None):
        self.find_calls.append((query, projection))
        cursor = self._find_queue.pop(0) if self._find_queue else FakeCursor([])
        self.find_cursors.append(cursor)
        return cursor

    def seed_find(self, *cursors: FakeCursor) -> None:
        self._find_queue = list(cursors)

    async def count_documents(self, query):
        self.count_calls.append(query)
        return self._count_return

    async def find_one(self, query):
        self.find_one_calls.append(query)
        if self._find_one_error is not None:
            raise self._find_one_error
        return self._find_one_return

    async def insert_one(self, doc):
        self.insert_calls.append(doc)
        if self._insert_error is not None:
            raise self._insert_error
        return self._insert_result

    async def update_one(self, query, update):
        self.update_calls.append((query, update))
        return self._update_result

    async def delete_one(self, query):
        self.delete_one_calls.append(query)
        return self._delete_result

    async def delete_many(self, query):
        self.delete_many_calls.append(query)
        return self._delete_result

    def aggregate(self, pipeline):
        self.aggregate_calls.append(pipeline)
        return FakeAggCursor(self._aggregate_return)


@pytest.fixture
def col(monkeypatch):
    """Patch the module's own collection binding with an in-memory fake."""
    fake = FakeCollection()
    monkeypatch.setattr("app.services.conversation_service.conversations_collection", fake)
    return fake


@pytest.fixture
def user():
    return {"user_id": "user_123", "email": "test@example.com"}


# ---------------------------------------------------------------------------
# create_conversation_service
# ---------------------------------------------------------------------------


class TestCreateConversationService:
    async def test_persists_full_document_and_returns_success(self, col, user):
        col._insert_result = FakeResult(acknowledged=True)

        conversation = ConversationModel(conversation_id="conv_abc", description="Test Chat")
        result = await create_conversation_service(conversation, user)

        assert result["conversation_id"] == "conv_abc"
        assert result["user_id"] == "user_123"
        assert result["detail"] == "Conversation created successfully"
        assert "createdAt" in result

        doc = col.insert_calls[0]
        assert doc["user_id"] == "user_123"
        assert doc["conversation_id"] == "conv_abc"
        assert doc["description"] == "Test Chat"
        assert doc["messages"] == []
        assert doc["is_system_generated"] is False
        assert doc["is_unread"] is False
        assert doc["is_onboarding_demo"] is False
        assert doc["source"] is None
        assert doc["createdAt"] == result["createdAt"]

    async def test_no_user_id_raises_403_before_any_db_call(self, col):
        conversation = ConversationModel(conversation_id="c", description="x")

        with pytest.raises(HTTPException) as exc:
            await create_conversation_service(conversation, {})

        assert exc.value.status_code == 403
        assert exc.value.detail == "Not authenticated"
        assert col.insert_calls == []

    async def test_insert_not_acknowledged_raises_500(self, col, user):
        col._insert_result = FakeResult(acknowledged=False)
        conversation = ConversationModel(conversation_id="c", description="x")

        with pytest.raises(HTTPException) as exc:
            await create_conversation_service(conversation, user)

        assert exc.value.status_code == 500
        assert exc.value.detail == "Failed to create conversation"

    async def test_insert_exception_wrapped_as_500_with_detail(self, col, user):
        col._insert_error = RuntimeError("DB down")
        conversation = ConversationModel(conversation_id="c", description="x")

        with pytest.raises(HTTPException) as exc:
            await create_conversation_service(conversation, user)

        assert exc.value.status_code == 500
        assert "DB down" in exc.value.detail
        assert "Failed to create conversation" in exc.value.detail

    async def test_bot_source_serialized_to_string_value(self, col, user):
        col._insert_result = FakeResult(acknowledged=True)
        conversation = ConversationModel(
            conversation_id="conv_bot",
            description="WhatsApp",
            source=ConversationSource.WHATSAPP,
        )

        await create_conversation_service(conversation, user)

        assert col.insert_calls[0]["source"] == "whatsapp"

    async def test_explicit_system_flags_persisted(self, col, user):
        col._insert_result = FakeResult(acknowledged=True)
        conversation = ConversationModel(
            conversation_id="conv_sys",
            description="System",
            is_system_generated=True,
            system_purpose=SystemPurpose.EMAIL_PROCESSING,
            is_unread=True,
        )

        await create_conversation_service(conversation, user)

        doc = col.insert_calls[0]
        assert doc["is_system_generated"] is True
        assert doc["is_unread"] is True
        assert doc["system_purpose"] == SystemPurpose.EMAIL_PROCESSING


# ---------------------------------------------------------------------------
# get_conversations
# ---------------------------------------------------------------------------


class TestGetConversations:
    async def test_filters_scoped_to_user_with_bot_exclusion(self, col, user):
        col.seed_find(FakeCursor([]), FakeCursor([]))
        col._count_return = 0

        await get_conversations(user, page=1, limit=10)

        assert len(col.find_calls) == 2
        for query, _projection in col.find_calls:
            assert query["user_id"] == "user_123"
            assert query["source"] == {"$nin": ["telegram", "discord", "slack", "whatsapp"]}
        assert col.count_calls[0]["user_id"] == "user_123"
        assert col.count_calls[0]["source"] == {
            "$nin": ["telegram", "discord", "slack", "whatsapp"]
        }

    async def test_starred_and_non_starred_filters_distinct(self, col, user):
        col.seed_find(FakeCursor([]), FakeCursor([]))
        col._count_return = 0

        await get_conversations(user, page=1, limit=10)

        starred_query = col.find_calls[0][0]
        non_starred_query = col.find_calls[1][0]
        assert starred_query["starred"] is True
        assert non_starred_query["$or"] == [
            {"starred": {"$exists": False}},
            {"starred": False},
        ]
        assert "starred" not in non_starred_query

    async def test_projection_is_exact(self, col, user):
        col.seed_find(FakeCursor([]), FakeCursor([]))
        col._count_return = 0

        await get_conversations(user, page=1, limit=10)

        # Both find() calls share the same projection; assert it exactly so a dropped
        # or renamed field (or a flipped include flag) is caught.
        assert col.find_calls[0][1] == {
            "_id": 1,
            "user_id": 1,
            "conversation_id": 1,
            "description": 1,
            "starred": 1,
            "is_system_generated": 1,
            "is_onboarding_conversation": 1,
            "system_purpose": 1,
            "is_unread": 1,
            "source": 1,
            "createdAt": 1,
            "updatedAt": 1,
        }
        assert col.find_calls[1][1] == col.find_calls[0][1]

    async def test_sort_skip_limit_reflect_pagination(self, col, user):
        starred = FakeCursor([])
        non_starred = FakeCursor([])
        col.seed_find(starred, non_starred)
        col._count_return = 50

        await get_conversations(user, page=3, limit=5)

        assert starred.sort_args == ("createdAt", -1)
        assert non_starred.sort_args == ("createdAt", -1)
        assert non_starred.skip_arg == 10  # (3-1)*5
        assert non_starred.limit_arg == 5
        assert starred.skip_arg is None
        assert starred.limit_arg is None

    async def test_combines_starred_and_paginated_with_stringified_ids(self, col, user):
        soid, noid = ObjectId(), ObjectId()
        starred = FakeCursor([{"_id": soid, "conversation_id": "s1", "starred": True}])
        non_starred = FakeCursor([{"_id": noid, "conversation_id": "n1"}])
        col.seed_find(starred, non_starred)
        col._count_return = 1

        result = await get_conversations(user, page=1, limit=10)

        ids = [c["conversation_id"] for c in result["conversations"]]
        assert ids == ["s1", "n1"]  # starred first, then non-starred
        assert result["conversations"][0]["_id"] == str(soid)
        assert result["conversations"][1]["_id"] == str(noid)
        assert result["total"] == 2  # len(starred)=1 + count=1

    async def test_total_pages_ceil_with_remainder(self, col, user):
        col.seed_find(FakeCursor([]), FakeCursor([]))
        col._count_return = 21

        result = await get_conversations(user, page=2, limit=10)

        assert result["page"] == 2
        assert result["limit"] == 10
        # ceil(21/10) = 3 — distinguishes the (count + limit - 1) // limit formula
        # from off-by-one mutations of the `- 1` term.
        assert result["total_pages"] == 3
        assert result["total"] == 21

    async def test_total_pages_exact_multiple(self, col, user):
        col.seed_find(FakeCursor([]), FakeCursor([]))
        col._count_return = 10

        result = await get_conversations(user, page=1, limit=10)

        # ceil(10/10) = 1 exactly — flipping `limit - 1` to `limit + 1` would yield 2.
        assert result["total_pages"] == 1
        assert result["total"] == 10

    async def test_total_pages_is_one_when_no_non_starred(self, col, user):
        col.seed_find(FakeCursor([]), FakeCursor([]))
        col._count_return = 0

        result = await get_conversations(user, page=1, limit=10)

        assert result["total_pages"] == 1

    async def test_default_page_and_limit(self, col, user):
        starred = FakeCursor([])
        non_starred = FakeCursor([])
        col.seed_find(starred, non_starred)
        col._count_return = 0

        result = await get_conversations(user)

        assert result["page"] == 1
        assert result["limit"] == 10
        assert non_starred.skip_arg == 0  # (1-1)*10
        assert non_starred.limit_arg == 10


# ---------------------------------------------------------------------------
# get_conversation
# ---------------------------------------------------------------------------


class TestGetConversation:
    async def test_returns_converted_conversation_scoped_to_owner(self, col, user):
        oid = ObjectId()
        col._find_one_return = {
            "_id": oid,
            "user_id": "user_123",
            "conversation_id": "conv_abc",
            "messages": [],
        }

        result = await get_conversation("conv_abc", user)

        assert result["conversation_id"] == "conv_abc"
        assert result["_id"] == str(oid)
        assert col.find_one_calls[0] == {
            "user_id": "user_123",
            "conversation_id": "conv_abc",
        }

    async def test_missing_doc_raises_404(self, col, user):
        col._find_one_return = None

        with pytest.raises(HTTPException) as exc:
            await get_conversation("missing", user)

        assert exc.value.status_code == 404
        assert exc.value.detail == "Conversation not found or does not belong to the user"

    async def test_filter_uses_callers_user_id_not_a_constant(self, col):
        col._find_one_return = None
        with pytest.raises(HTTPException):
            await get_conversation("conv_abc", {"user_id": "user_other"})
        assert col.find_one_calls[0]["user_id"] == "user_other"

    async def test_legacy_tool_data_in_messages_is_converted(self, col, user):
        oid = ObjectId()
        col._find_one_return = {
            "_id": oid,
            "user_id": "user_123",
            "conversation_id": "conv_abc",
            "messages": [{"message_id": "m1", "weather_data": {"temp": 5}}],
        }

        result = await get_conversation("conv_abc", user)

        msg = result["messages"][0]
        assert "weather_data" not in msg  # folded into unified tool_data
        assert msg["tool_data"][0]["tool_name"] == "weather_data"
        assert msg["tool_data"][0]["data"] == {"temp": 5}


# ---------------------------------------------------------------------------
# star_conversation
# ---------------------------------------------------------------------------


class TestStarConversation:
    async def test_sets_starred_true_and_bumps_updated_at(self, col, user):
        col._update_result = FakeResult(modified_count=1)

        result = await star_conversation("conv_abc", True, user)

        assert result == {
            "message": "Conversation updated successfully",
            "starred": True,
        }
        query, update = col.update_calls[0]
        assert query == {"user_id": "user_123", "conversation_id": "conv_abc"}
        assert update["$set"] == {"starred": True}
        assert update["$currentDate"] == {"updatedAt": True}

    async def test_sets_starred_false(self, col, user):
        col._update_result = FakeResult(modified_count=1)

        result = await star_conversation("conv_abc", False, user)

        assert result["starred"] is False
        assert col.update_calls[0][1]["$set"] == {"starred": False}

    async def test_no_match_raises_404(self, col, user):
        col._update_result = FakeResult(modified_count=0)

        with pytest.raises(HTTPException) as exc:
            await star_conversation("missing", True, user)

        assert exc.value.status_code == 404
        assert exc.value.detail == "Conversation not found or update failed"


# ---------------------------------------------------------------------------
# delete_conversation / delete_all_conversations
# ---------------------------------------------------------------------------


class TestDeleteConversation:
    async def test_deletes_single_scoped_to_user(self, col, user):
        col._delete_result = FakeResult(deleted_count=1)

        result = await delete_conversation("conv_abc", user)

        assert result == {
            "message": "Conversation deleted successfully",
            "conversation_id": "conv_abc",
        }
        assert col.delete_one_calls[0] == {
            "user_id": "user_123",
            "conversation_id": "conv_abc",
        }

    async def test_single_no_match_raises_404(self, col, user):
        col._delete_result = FakeResult(deleted_count=0)

        with pytest.raises(HTTPException) as exc:
            await delete_conversation("missing", user)

        assert exc.value.status_code == 404
        assert exc.value.detail == "Conversation not found or does not belong to the user"

    async def test_delete_all_scoped_to_user(self, col, user):
        col._delete_result = FakeResult(deleted_count=5)

        result = await delete_all_conversations(user)

        assert result == {"message": "All conversations deleted successfully"}
        assert col.delete_many_calls[0] == {"user_id": "user_123"}

    async def test_delete_all_no_match_raises_404(self, col, user):
        col._delete_result = FakeResult(deleted_count=0)

        with pytest.raises(HTTPException) as exc:
            await delete_all_conversations(user)

        assert exc.value.status_code == 404
        assert exc.value.detail == "No conversations found for the user"


# ---------------------------------------------------------------------------
# update_messages
# ---------------------------------------------------------------------------


class TestUpdateMessages:
    async def test_pushes_messages_and_returns_ids(self, col, user):
        col._update_result = FakeResult(modified_count=1)
        request = UpdateMessagesRequest(
            conversation_id="conv_abc",
            messages=[MessageModel(type="user", response="Hello")],
        )

        result = await update_messages(request, user)

        assert result["conversation_id"] == "conv_abc"
        assert result["message"] == "Messages updated"
        assert result["modified_count"] == 1
        assert len(result["message_ids"]) == 1

        query, update = col.update_calls[0]
        assert query == {"user_id": "user_123", "conversation_id": "conv_abc"}
        assert update["$currentDate"] == {"updatedAt": True}
        pushed = update["$push"]["messages"]["$each"]
        assert len(pushed) == 1
        assert pushed[0]["message_id"] == result["message_ids"][0]
        assert pushed[0]["response"] == "Hello"

    async def test_preserves_existing_message_id(self, col, user):
        col._update_result = FakeResult(modified_count=1)
        request = UpdateMessagesRequest(
            conversation_id="conv_abc",
            messages=[MessageModel(type="user", response="Hi", message_id="explicit_id")],
        )

        result = await update_messages(request, user)

        assert result["message_ids"] == ["explicit_id"]
        pushed = col.update_calls[0][1]["$push"]["messages"]["$each"][0]
        assert pushed["message_id"] == "explicit_id"

    async def test_strips_none_fields_from_messages(self, col, user):
        col._update_result = FakeResult(modified_count=1)
        request = UpdateMessagesRequest(
            conversation_id="conv_abc",
            messages=[MessageModel(type="user", response="Hi", disclaimer=None)],
        )

        await update_messages(request, user)

        pushed = col.update_calls[0][1]["$push"]["messages"]["$each"][0]
        assert "disclaimer" not in pushed
        assert pushed["response"] == "Hi"

    async def test_no_match_raises_404(self, col, user):
        col._update_result = FakeResult(modified_count=0)
        request = UpdateMessagesRequest(
            conversation_id="missing",
            messages=[MessageModel(type="user", response="Hi")],
        )

        with pytest.raises(HTTPException) as exc:
            await update_messages(request, user)

        assert exc.value.status_code == 404
        assert exc.value.detail == "Conversation not found or does not belong to the user"


# ---------------------------------------------------------------------------
# pin_message
# ---------------------------------------------------------------------------


class TestPinMessage:
    def _conv_with(self, *message_ids):
        return {
            "_id": ObjectId(),
            "user_id": "user_123",
            "conversation_id": "conv_abc",
            "messages": [{"message_id": mid} for mid in message_ids],
        }

    async def test_pins_message_with_positional_update(self, col, user):
        col._find_one_return = self._conv_with("msg_1")
        col._update_result = FakeResult(modified_count=1)

        result = await pin_message("conv_abc", "msg_1", True, user)

        assert result == {
            "message": "Message with ID msg_1 pinned successfully",
            "pinned": True,
        }
        # The lookup that locates the conversation is scoped to the owner.
        assert col.find_one_calls[0] == {
            "user_id": "user_123",
            "conversation_id": "conv_abc",
        }
        query, update = col.update_calls[0]
        assert query == {
            "user_id": "user_123",
            "conversation_id": "conv_abc",
            "messages.message_id": "msg_1",
        }
        assert update["$set"] == {"messages.$.pinned": True}
        assert update["$currentDate"] == {"updatedAt": True}

    async def test_unpins_message(self, col, user):
        col._find_one_return = self._conv_with("msg_1")
        col._update_result = FakeResult(modified_count=1)

        result = await pin_message("conv_abc", "msg_1", False, user)

        assert result == {
            "message": "Message with ID msg_1 unpinned successfully",
            "pinned": False,
        }
        assert col.update_calls[0][1]["$set"] == {"messages.$.pinned": False}

    async def test_missing_conversation_raises_404(self, col, user):
        col._find_one_return = None

        with pytest.raises(HTTPException) as exc:
            await pin_message("conv_abc", "msg_1", True, user)

        assert exc.value.status_code == 404
        assert exc.value.detail == "Conversation not found"
        assert col.update_calls == []

    async def test_message_not_in_conversation_raises_404(self, col, user):
        col._find_one_return = self._conv_with("other_msg")

        with pytest.raises(HTTPException) as exc:
            await pin_message("conv_abc", "msg_target", True, user)

        assert exc.value.status_code == 404
        assert exc.value.detail == "Message not found in conversation"
        assert col.update_calls == []

    async def test_update_no_op_raises_404(self, col, user):
        col._find_one_return = self._conv_with("msg_1")
        col._update_result = FakeResult(modified_count=0)

        with pytest.raises(HTTPException) as exc:
            await pin_message("conv_abc", "msg_1", True, user)

        assert exc.value.status_code == 404
        assert exc.value.detail == "Message not found or update failed"


# ---------------------------------------------------------------------------
# get_starred_messages
# ---------------------------------------------------------------------------


class TestGetStarredMessages:
    async def test_aggregation_pipeline_and_conversion(self, col, user):
        col._aggregate_return = [
            {
                "conversation_id": "conv_1",
                "message": {"message_id": "m1", "pinned": True, "weather_data": {"t": 1}},
            }
        ]

        result = await get_starred_messages(user)

        assert len(result["results"]) == 1
        entry = result["results"][0]
        assert entry["conversation_id"] == "conv_1"
        # convert_legacy_tool_data (real) folds the legacy field into tool_data
        assert "weather_data" not in entry["message"]
        assert entry["message"]["tool_data"][0]["tool_name"] == "weather_data"
        assert entry["message"]["tool_data"][0]["data"] == {"t": 1}

        pipeline = col.aggregate_calls[0]
        assert pipeline[0] == {"$match": {"user_id": "user_123"}}
        assert pipeline[1] == {"$unwind": "$messages"}
        assert pipeline[2] == {"$match": {"messages.pinned": True}}
        assert pipeline[3] == {"$project": {"_id": 0, "conversation_id": 1, "message": "$messages"}}

    async def test_empty_results(self, col, user):
        col._aggregate_return = []

        result = await get_starred_messages(user)

        assert result == {"results": []}

    async def test_entry_without_message_key_passed_through(self, col, user):
        # The conversion branch only runs when "message" is present.
        col._aggregate_return = [{"conversation_id": "conv_2"}]

        result = await get_starred_messages(user)

        assert result["results"] == [{"conversation_id": "conv_2"}]


# ---------------------------------------------------------------------------
# create_system_conversation
# ---------------------------------------------------------------------------


class TestCreateSystemConversation:
    async def test_persists_and_returns_system_doc(self, col):
        col._insert_result = FakeResult(acknowledged=True)

        result = await create_system_conversation(
            "user_123", "Email Actions", SystemPurpose.EMAIL_PROCESSING
        )

        assert result["user_id"] == "user_123"
        assert result["description"] == "Email Actions"
        assert result["is_system_generated"] is True
        assert result["system_purpose"] == SystemPurpose.EMAIL_PROCESSING
        assert result["detail"] == "System conversation created successfully"
        # A fresh uuid conversation_id and createdAt are echoed back to the caller
        # and must match what was persisted.
        assert result["conversation_id"]
        assert "createdAt" in result

        doc = col.insert_calls[0]
        assert doc["user_id"] == "user_123"
        assert doc["messages"] == []
        assert doc["is_system_generated"] is True
        assert doc["is_unread"] is True  # the model sets is_unread=True
        assert doc["conversation_id"] == result["conversation_id"]
        assert doc["createdAt"] == result["createdAt"]
        # model_dump(exclude_unset=True) drops never-set fields, so the unset
        # `source` default must not leak into the persisted document.
        assert "source" not in doc

    async def test_not_acknowledged_raises_500(self, col):
        col._insert_result = FakeResult(acknowledged=False)

        with pytest.raises(HTTPException) as exc:
            await create_system_conversation("user_123", "x", SystemPurpose.OTHER)

        assert exc.value.status_code == 500
        # The not-acknowledged HTTPException is raised inside the try and re-wrapped by
        # the broad except, so the surfaced detail nests the original 500 message.
        assert (
            exc.value.detail
            == "Failed to create system conversation: 500: Failed to create system conversation"
        )

    async def test_insert_exception_wrapped_as_500(self, col):
        col._insert_error = RuntimeError("boom")

        with pytest.raises(HTTPException) as exc:
            await create_system_conversation("user_123", "x", SystemPurpose.OTHER)

        assert exc.value.status_code == 500
        assert "boom" in exc.value.detail


# ---------------------------------------------------------------------------
# get_or_create_system_conversation
# ---------------------------------------------------------------------------


class TestGetOrCreateSystemConversation:
    async def test_returns_existing_with_stringified_id_no_insert(self, col):
        oid = ObjectId()
        col._find_one_return = {
            "_id": oid,
            "conversation_id": "conv_sys",
            "is_system_generated": True,
            "system_purpose": "email_processing",
        }

        result = await get_or_create_system_conversation("user_123", SystemPurpose.EMAIL_PROCESSING)

        assert result["conversation_id"] == "conv_sys"
        assert result["_id"] == str(oid)
        assert col.insert_calls == []  # reused, not recreated
        assert col.find_one_calls[0] == {
            "user_id": "user_123",
            "is_system_generated": True,
            "system_purpose": SystemPurpose.EMAIL_PROCESSING,
        }

    async def test_creates_with_mapped_description_when_missing(self, col):
        col._find_one_return = None
        col._insert_result = FakeResult(acknowledged=True)

        result = await get_or_create_system_conversation("user_123", SystemPurpose.EMAIL_PROCESSING)

        assert result["description"] == "Email Actions & Notifications"
        assert result["is_system_generated"] is True

    async def test_reminder_mapped_description(self, col):
        col._find_one_return = None
        col._insert_result = FakeResult(acknowledged=True)

        result = await get_or_create_system_conversation(
            "user_123", SystemPurpose.REMINDER_PROCESSING
        )

        assert result["description"] == "Reminder Management"

    async def test_caller_description_overrides_map(self, col):
        col._find_one_return = None
        col._insert_result = FakeResult(acknowledged=True)

        result = await get_or_create_system_conversation(
            "user_123", SystemPurpose.OTHER, description="Custom Desc"
        )

        assert result["description"] == "Custom Desc"

    async def test_unmapped_purpose_falls_back_to_titlecased_default(self, col):
        col._find_one_return = None
        col._insert_result = FakeResult(acknowledged=True)

        # WORKFLOW_EXECUTION = "workflow_execution" is not in description_map.
        result = await get_or_create_system_conversation(
            "user_123", SystemPurpose.WORKFLOW_EXECUTION
        )

        assert result["description"] == "System: Workflow Execution"


# ---------------------------------------------------------------------------
# update_conversation_description
# ---------------------------------------------------------------------------


class TestUpdateConversationDescription:
    async def test_updates_description(self, col, user):
        col._update_result = FakeResult(modified_count=1)

        result = await update_conversation_description("conv_abc", "New Title", user)

        assert result == {
            "message": "Conversation description updated successfully",
            "conversation_id": "conv_abc",
            "description": "New Title",
        }
        query, update = col.update_calls[0]
        assert query == {"user_id": "user_123", "conversation_id": "conv_abc"}
        assert update["$set"] == {"description": "New Title"}
        assert update["$currentDate"] == {"updatedAt": True}

    async def test_no_match_raises_404(self, col, user):
        col._update_result = FakeResult(modified_count=0)

        with pytest.raises(HTTPException) as exc:
            await update_conversation_description("missing", "x", user)

        assert exc.value.status_code == 404
        assert exc.value.detail == "Conversation not found or description not updated"


# ---------------------------------------------------------------------------
# mark_conversation_as_read / mark_conversation_as_unread
# ---------------------------------------------------------------------------


class TestMarkReadUnread:
    async def test_mark_read_sets_unread_false(self, col, user):
        col._update_result = FakeResult(modified_count=1)

        result = await mark_conversation_as_read("conv_abc", user)

        assert result == {
            "message": "Conversation marked as read",
            "conversation_id": "conv_abc",
        }
        query, update = col.update_calls[0]
        assert query == {"user_id": "user_123", "conversation_id": "conv_abc"}
        assert update["$set"] == {"is_unread": False}
        assert update["$currentDate"] == {"updatedAt": True}

    async def test_mark_read_no_user_id_raises_403(self, col):
        with pytest.raises(HTTPException) as exc:
            await mark_conversation_as_read("conv_abc", {})

        assert exc.value.status_code == 403
        assert exc.value.detail == "Not authenticated"
        assert col.update_calls == []

    async def test_mark_unread_sets_unread_true(self, col, user):
        col._update_result = FakeResult(modified_count=1)

        result = await mark_conversation_as_unread("conv_abc", user)

        assert result == {
            "message": "Conversation marked as unread",
            "conversation_id": "conv_abc",
        }
        query, update = col.update_calls[0]
        assert query == {"user_id": "user_123", "conversation_id": "conv_abc"}
        assert update["$set"] == {"is_unread": True}
        assert update["$currentDate"] == {"updatedAt": True}

    async def test_mark_unread_no_user_id_raises_403(self, col):
        with pytest.raises(HTTPException) as exc:
            await mark_conversation_as_unread("conv_abc", {})

        assert exc.value.status_code == 403
        assert exc.value.detail == "Not authenticated"
        assert col.update_calls == []

    async def test_mark_unread_no_match_raises_404(self, col, user):
        col._update_result = FakeResult(modified_count=0)

        with pytest.raises(HTTPException) as exc:
            await mark_conversation_as_unread("conv_abc", user)

        assert exc.value.status_code == 404
        assert exc.value.detail == "Conversation not found or update failed"


# ---------------------------------------------------------------------------
# batch_sync_conversations
# ---------------------------------------------------------------------------


class TestBatchSyncConversations:
    async def test_no_user_id_raises_403(self, col):
        with pytest.raises(HTTPException) as exc:
            await batch_sync_conversations(BatchSyncRequest(conversations=[]), {})

        assert exc.value.status_code == 403
        assert exc.value.detail == "Not authenticated"

    async def test_empty_conversations_returns_empty_without_db(self, col, user):
        result = await batch_sync_conversations(BatchSyncRequest(conversations=[]), user)

        assert result == {"conversations": []}
        assert col.aggregate_calls == []  # short-circuits before any DB call

    async def test_valid_timestamp_builds_updated_after_match(self, col, user):
        col._aggregate_return = []
        request = BatchSyncRequest(
            conversations=[
                ConversationSyncItem(conversation_id="conv_1", last_updated="2024-01-01T00:00:00Z")
            ]
        )

        await batch_sync_conversations(request, user)

        pipeline = col.aggregate_calls[0]
        cond = pipeline[0]["$match"]["$or"][0]
        assert cond["user_id"] == "user_123"
        assert cond["conversation_id"] == "conv_1"
        gt_clause, exists_clause = cond["$or"]
        assert gt_clause["updatedAt"]["$gt"] == datetime(2024, 1, 1, tzinfo=UTC)
        assert exists_clause == {"updatedAt": {"$exists": False}}
        # The aggregation projects exactly these fields (messages included for sync).
        assert pipeline[1]["$project"] == {
            "_id": 0,
            "conversation_id": 1,
            "description": 1,
            "starred": 1,
            "is_system_generated": 1,
            "is_onboarding_conversation": 1,
            "system_purpose": 1,
            "is_unread": 1,
            "createdAt": 1,
            "updatedAt": 1,
            "messages": 1,
        }

    async def test_invalid_timestamp_is_swallowed_and_conversation_still_matched(self, col, user):
        col._aggregate_return = []
        request = BatchSyncRequest(
            conversations=[
                ConversationSyncItem(conversation_id="conv_1", last_updated="not-a-date")
            ]
        )

        await batch_sync_conversations(request, user)

        cond = col.aggregate_calls[0][0]["$match"]["$or"][0]
        # No $or timestamp clause -> the conversation is matched unconditionally.
        assert "$or" not in cond
        assert cond == {"user_id": "user_123", "conversation_id": "conv_1"}

    async def test_no_last_updated_matches_unconditionally(self, col, user):
        col._aggregate_return = []
        request = BatchSyncRequest(conversations=[ConversationSyncItem(conversation_id="conv_1")])

        await batch_sync_conversations(request, user)

        cond = col.aggregate_calls[0][0]["$match"]["$or"][0]
        assert "$or" not in cond

    async def test_serializes_conversation_and_message_datetimes(self, col, user):
        c_created = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
        c_updated = datetime(2024, 6, 2, 12, 0, 0, tzinfo=UTC)
        m_ts = datetime(2024, 6, 3, tzinfo=UTC)
        m_created = datetime(2024, 6, 4, tzinfo=UTC)
        m_date = datetime(2024, 6, 5, tzinfo=UTC)
        col._aggregate_return = [
            {
                "conversation_id": "conv_1",
                "createdAt": c_created,
                "updatedAt": c_updated,
                "messages": [
                    {
                        "message_id": "m1",
                        "timestamp": m_ts,
                        "createdAt": m_created,
                        "date": m_date,
                    }
                ],
            }
        ]
        request = BatchSyncRequest(conversations=[ConversationSyncItem(conversation_id="conv_1")])

        result = await batch_sync_conversations(request, user)

        conv = result["conversations"][0]
        # Conversation-level createdAt AND updatedAt are serialized.
        assert conv["createdAt"] == c_created.isoformat()
        assert conv["updatedAt"] == c_updated.isoformat()
        # Each message's timestamp, createdAt and date fields are serialized.
        msg = conv["messages"][0]
        assert msg["timestamp"] == m_ts.isoformat()
        assert msg["createdAt"] == m_created.isoformat()
        assert msg["date"] == m_date.isoformat()


# ---------------------------------------------------------------------------
# helpers: _convert_datetime_to_iso / _convert_ids
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_converts_datetime_field_in_place(self):
        dt = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)
        obj = {"createdAt": dt, "name": "test"}

        _convert_datetime_to_iso(obj, "createdAt")

        assert obj["createdAt"] == dt.isoformat()
        assert obj["name"] == "test"

    def test_converts_multiple_fields(self):
        dt1 = datetime(2024, 1, 1, tzinfo=UTC)
        dt2 = datetime(2024, 2, 2, tzinfo=UTC)
        obj = {"createdAt": dt1, "updatedAt": dt2}

        _convert_datetime_to_iso(obj, "createdAt", "updatedAt")

        assert obj["createdAt"] == dt1.isoformat()
        assert obj["updatedAt"] == dt2.isoformat()

    def test_leaves_non_datetime_value_unchanged(self):
        obj = {"createdAt": "already_string"}
        _convert_datetime_to_iso(obj, "createdAt")
        assert obj["createdAt"] == "already_string"

    def test_missing_field_is_not_added(self):
        obj = {"name": "test"}
        _convert_datetime_to_iso(obj, "createdAt")
        assert "createdAt" not in obj

    def test_convert_ids_stringifies_object_id_and_returns_same_list(self):
        oid = ObjectId()
        conversations = [{"_id": oid, "conversation_id": "c1"}]

        result = _convert_ids(conversations)

        assert result is conversations  # mutates in place and returns it
        assert result[0]["_id"] == str(oid)

    def test_convert_ids_also_converts_both_datetime_fields(self):
        oid = ObjectId()
        created = datetime(2024, 3, 3, tzinfo=UTC)
        updated = datetime(2024, 4, 4, tzinfo=UTC)
        conversations = [{"_id": oid, "createdAt": created, "updatedAt": updated}]

        _convert_ids(conversations)

        # _convert_ids passes BOTH "createdAt" and "updatedAt" to the iso helper.
        assert conversations[0]["createdAt"] == created.isoformat()
        assert conversations[0]["updatedAt"] == updated.isoformat()
