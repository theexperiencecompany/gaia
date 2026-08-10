"""
Tests for conversation endpoints (/api/v1/conversations/*).

Every endpoint is pinned to its exact contract: status code, full response
body, the exact arguments handed to the mocked service function, and the wide
event fields recorded via ``log.set`` (patched — the repo's established seam
for asserting wide-event fields). The service functions are the only thing
mocked; the endpoints themselves run for real against the test app.

Covers:
- POST /conversations — create
- GET /conversations — list (paginated)
- POST /conversations/batch-sync — batch sync
- GET /conversations/{id} — get single
- PUT /conversations/{id}/messages — update messages
- PUT /conversations/{id}/star — star/unstar
- PUT /conversations/{id}/messages/{message_id}/pin — pin message
- PUT /conversations/{id}/description — update description
- PATCH /conversations/{id}/read — mark as read
- PATCH /conversations/{id}/unread — mark as unread
- DELETE /conversations/{id} — delete single
- DELETE /conversations — delete all
- GET /messages/pinned — get pinned messages
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, call, patch

from fastapi import FastAPI
from httpx import AsyncClient
import pytest

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.models.chat_models import (
    BatchSyncRequest,
    ConversationModel,
    ConversationSource,
    ConversationSyncItem,
    MessageModel,
    SystemPurpose,
    UpdateMessagesRequest,
)
from app.models.conversation_models import (
    BatchSyncResponse,
    ConversationActionResponse,
    ConversationDocument,
    ConversationListResponse,
    ConversationMessageHit,
    ConversationSummary,
    ConversationSyncRow,
    CreateConversationResponse,
    DeleteAllConversationsResponse,
    PinMessageResponse,
    PinnedMessagesResponse,
    StarConversationResponse,
    UpdateDescriptionResponse,
    UpdateMessagesResponse,
)
from tests.conftest import FAKE_USER

CONV_SERVICE = "app.api.v1.endpoints.conversations"
USER_ID = FAKE_USER["user_id"]


def _summary() -> ConversationSummary:
    """A fully populated conversation-list row, so the body assertion sees it all."""
    return ConversationSummary(
        conversation_id="conv_123",
        user_id=USER_ID,
        description="My chat",
        starred=True,
        is_system_generated=False,
        is_onboarding_conversation=False,
        system_purpose=None,
        is_unread=True,
        source=ConversationSource.WEB,
        createdAt="2024-01-01T00:00:00+00:00",
        updatedAt=datetime(2024, 1, 1, tzinfo=UTC),
    )


class TestCreateConversation:
    """POST /api/v1/conversations"""

    async def test_create_returns_response(self, client: AsyncClient, test_app: FastAPI):
        # A user whose dict carries a None key and a plan: the endpoint reads
        # `user.get("plan")` for the wide event, and a mutant that replaced
        # that arg with None must land on different log fields — for a
        # plan-less user, .get(None) would be indistinguishable from .get("plan").
        user = {**FAKE_USER, "plan": "pro", None: "none-plan"}
        original = test_app.dependency_overrides.get(get_current_user)
        test_app.dependency_overrides[get_current_user] = lambda: user
        mock_resp = CreateConversationResponse(
            conversation_id="conv_123",
            user_id=USER_ID,
            createdAt="2024-01-01T00:00:00+00:00",
            detail="Conversation created successfully",
        )
        try:
            with (
                patch(f"{CONV_SERVICE}.log") as mock_log,
                patch(
                    f"{CONV_SERVICE}.create_conversation_service",
                    new_callable=AsyncMock,
                    return_value=mock_resp,
                ) as mock_create,
            ):
                resp = await client.post(
                    "/api/v1/conversations",
                    json={"conversation_id": "conv_123", "description": "New Chat"},
                )
        finally:
            test_app.dependency_overrides[get_current_user] = original

        assert resp.status_code == 200
        assert resp.json() == mock_resp.model_dump(mode="json")
        expected_model = ConversationModel(
            conversation_id="conv_123", description="New Chat"
        )
        mock_create.assert_awaited_once_with(expected_model, user)
        assert mock_log.set.call_args_list == [
            call(
                user={"id": USER_ID, "plan": "pro"},
                conversation={"operation": "create", "is_new": True},
            ),
            call(
                conversation={
                    "operation": "create",
                    "is_new": True,
                    "id": "conv_123",
                }
            ),
        ]

    async def test_create_requires_auth(self, unauthed_client: AsyncClient):
        resp = await unauthed_client.post(
            "/api/v1/conversations",
            json={"conversation_id": "conv_nope"},
        )
        assert resp.status_code == 401


class TestListConversations:
    """GET /api/v1/conversations"""

    async def test_list_default_pagination(self, client: AsyncClient):
        mock_resp = ConversationListResponse(
            conversations=[_summary()], total=1, page=1, limit=10, total_pages=1
        )
        with (
            patch(f"{CONV_SERVICE}.log") as mock_log,
            patch(
                f"{CONV_SERVICE}.get_conversations",
                new_callable=AsyncMock,
                return_value=mock_resp,
            ) as mock_list,
        ):
            resp = await client.get("/api/v1/conversations")

        assert resp.status_code == 200
        assert resp.json() == mock_resp.model_dump(mode="json")
        mock_list.assert_awaited_once_with(FAKE_USER, page=1, limit=10)
        assert mock_log.set.call_args_list == [
            call(
                user={"id": USER_ID},
                conversation={"operation": "list", "page": 1, "limit": 10},
            ),
            call(
                conversation={
                    "operation": "list",
                    "page": 1,
                    "limit": 10,
                    "total_returned": 1,
                }
            ),
        ]

    async def test_list_with_pagination(self, client: AsyncClient):
        mock_resp = ConversationListResponse(
            conversations=[_summary()], total=1, page=2, limit=5, total_pages=1
        )
        with patch(
            f"{CONV_SERVICE}.get_conversations",
            new_callable=AsyncMock,
            return_value=mock_resp,
        ) as mock_list:
            resp = await client.get("/api/v1/conversations?page=2&limit=5")

        assert resp.status_code == 200
        assert resp.json() == mock_resp.model_dump(mode="json")
        mock_list.assert_awaited_once_with(FAKE_USER, page=2, limit=5)

    async def test_list_invalid_page(self, client: AsyncClient):
        resp = await client.get("/api/v1/conversations?page=0")
        assert resp.status_code == 422

    @pytest.mark.regression
    async def test_list_rejects_page_that_would_overflow_the_mongo_skip(
        self, client: AsyncClient
    ) -> None:
        """A page too large to page with is a 422, not a 500.

        `page` was bounded below (ge=1) but not above, and the service turns it
        into `skip = (page - 1) * limit`. These exact values came from the
        schemathesis contract gate, which drove GET /api/v1/conversations to a
        500: the product is 10534517480782774985, past int64 max, so BSON cannot
        encode the skip and the driver error escapes as a server error.
        """
        resp = await client.get("/api/v1/conversations?limit=55&page=191536681468777728")

        assert resp.status_code == 422


class TestGetConversation:
    """GET /api/v1/conversations/{id}"""

    async def test_get_existing(self, client: AsyncClient):
        # A non-empty document id: the endpoint dumps with exclude={"id"}, and
        # a mutant that drops the exclusion must leak it into the body.
        doc = ConversationDocument(
            id="mongo_id_abc",
            conversation_id="conv_123",
            user_id=USER_ID,
            description="My chat",
            is_system_generated=True,
            system_purpose=SystemPurpose.WORKFLOW_EXECUTION,
            is_unread=True,
            source=ConversationSource.WEB,
            is_onboarding_demo=True,
            is_onboarding_conversation=True,
            starred=True,
            messages=[MessageModel(type="user", response="hello")],
            artifacts=[{"path": "a.txt", "size": 3}],
            createdAt="2024-01-01T00:00:00+00:00",
            updatedAt=datetime(2024, 1, 1, tzinfo=UTC),
        )
        with (
            patch(f"{CONV_SERVICE}.log") as mock_log,
            patch(
                f"{CONV_SERVICE}.get_conversation",
                new_callable=AsyncMock,
                return_value=doc,
            ) as mock_get,
        ):
            resp = await client.get("/api/v1/conversations/conv_123")

        assert resp.status_code == 200
        assert resp.json() == doc.model_dump(mode="json", exclude={"id"})
        # The endpoint dumps the document with exclude={"id"} — the Mongo _id
        # must not reach the client.
        assert "id" not in resp.json()
        mock_get.assert_awaited_once_with("conv_123", FAKE_USER)
        assert mock_log.set.call_args_list == [
            call(
                user={"id": USER_ID},
                conversation={"operation": "get", "id": "conv_123"},
            )
        ]


class TestDeleteConversation:
    """DELETE /api/v1/conversations/{id}"""

    async def test_delete_single(self, client: AsyncClient):
        mock_resp = ConversationActionResponse(
            message="Conversation deleted successfully", conversation_id="conv_123"
        )
        with (
            patch(f"{CONV_SERVICE}.log") as mock_log,
            patch(
                f"{CONV_SERVICE}.delete_conversation",
                new_callable=AsyncMock,
                return_value=mock_resp,
            ) as mock_delete,
        ):
            resp = await client.delete("/api/v1/conversations/conv_123")

        assert resp.status_code == 200
        assert resp.json() == mock_resp.model_dump(mode="json")
        mock_delete.assert_awaited_once_with("conv_123", FAKE_USER)
        assert mock_log.set.call_args_list == [
            call(
                user={"id": USER_ID},
                conversation={"operation": "delete", "id": "conv_123"},
            )
        ]

    async def test_delete_all(self, client: AsyncClient):
        mock_resp = DeleteAllConversationsResponse(
            message="All conversations deleted successfully"
        )
        with (
            patch(f"{CONV_SERVICE}.log") as mock_log,
            patch(
                f"{CONV_SERVICE}.delete_all_conversations",
                new_callable=AsyncMock,
                return_value=mock_resp,
            ) as mock_delete_all,
        ):
            resp = await client.delete("/api/v1/conversations")

        assert resp.status_code == 200
        assert resp.json() == mock_resp.model_dump(mode="json")
        mock_delete_all.assert_awaited_once_with(FAKE_USER)
        assert mock_log.set.call_args_list == [
            call(
                user={"id": USER_ID},
                conversation={"operation": "delete_all"},
            )
        ]


class TestStarConversation:
    """PUT /api/v1/conversations/{id}/star"""

    async def test_star(self, client: AsyncClient):
        mock_resp = StarConversationResponse(message="Conversation starred", starred=True)
        with (
            patch(f"{CONV_SERVICE}.log") as mock_log,
            patch(
                f"{CONV_SERVICE}.star_conversation",
                new_callable=AsyncMock,
                return_value=mock_resp,
            ) as mock_star,
        ):
            resp = await client.put(
                "/api/v1/conversations/conv_123/star",
                json={"starred": True},
            )

        assert resp.status_code == 200
        assert resp.json() == mock_resp.model_dump(mode="json")
        mock_star.assert_awaited_once_with("conv_123", True, FAKE_USER)
        assert mock_log.set.call_args_list == [
            call(
                user={"id": USER_ID},
                conversation={"operation": "star", "id": "conv_123", "is_starred": True},
            )
        ]


class TestPinMessage:
    """PUT /api/v1/conversations/{id}/messages/{message_id}/pin"""

    async def test_pin(self, client: AsyncClient):
        mock_resp = PinMessageResponse(message="Message pinned", pinned=True)
        with (
            patch(f"{CONV_SERVICE}.log") as mock_log,
            patch(
                f"{CONV_SERVICE}.pin_message",
                new_callable=AsyncMock,
                return_value=mock_resp,
            ) as mock_pin,
        ):
            resp = await client.put(
                "/api/v1/conversations/conv_123/messages/msg_456/pin",
                json={"pinned": True},
            )

        assert resp.status_code == 200
        assert resp.json() == mock_resp.model_dump(mode="json")
        mock_pin.assert_awaited_once_with("conv_123", "msg_456", True, FAKE_USER)
        assert mock_log.set.call_args_list == [
            call(
                user={"id": USER_ID},
                conversation={"operation": "pin_message", "id": "conv_123"},
            )
        ]


class TestUpdateDescription:
    """PUT /api/v1/conversations/{id}/description"""

    async def test_update_description(self, client: AsyncClient):
        mock_resp = UpdateDescriptionResponse(
            message="Description updated",
            conversation_id="conv_123",
            description="My important chat",
        )
        with (
            patch(f"{CONV_SERVICE}.log") as mock_log,
            patch(
                f"{CONV_SERVICE}.update_conversation_description",
                new_callable=AsyncMock,
                return_value=mock_resp,
            ) as mock_update,
        ):
            resp = await client.put(
                "/api/v1/conversations/conv_123/description",
                json={"description": "My important chat"},
            )

        assert resp.status_code == 200
        assert resp.json() == mock_resp.model_dump(mode="json")
        mock_update.assert_awaited_once_with("conv_123", "My important chat", FAKE_USER)
        assert mock_log.set.call_args_list == [
            call(
                user={"id": USER_ID},
                conversation={"operation": "update_description", "id": "conv_123"},
            )
        ]


class TestBatchSync:
    """POST /api/v1/conversations/batch-sync"""

    async def test_batch_sync(self, client: AsyncClient):
        request_model = BatchSyncRequest(
            conversations=[
                ConversationSyncItem(
                    conversation_id="c1", last_updated="2024-01-01T00:00:00+00:00"
                )
            ]
        )
        mock_resp = BatchSyncResponse(
            conversations=[
                ConversationSyncRow(
                    conversation_id="c1",
                    description="My chat",
                    starred=True,
                    is_system_generated=False,
                    is_onboarding_conversation=False,
                    system_purpose=None,
                    is_unread=True,
                    createdAt="2024-01-01T00:00:00+00:00",
                    updatedAt=datetime(2024, 1, 1, tzinfo=UTC),
                    messages=[MessageModel(type="user", response="hello")],
                    artifacts=[{"path": "a.txt", "size": 3}],
                    active_stream_id="stream_abc",
                )
            ]
        )
        with (
            patch(f"{CONV_SERVICE}.log") as mock_log,
            patch(
                f"{CONV_SERVICE}.batch_sync_conversations",
                new_callable=AsyncMock,
                return_value=mock_resp,
            ) as mock_sync,
        ):
            resp = await client.post(
                "/api/v1/conversations/batch-sync",
                json={
                    "conversations": [
                        {
                            "conversation_id": "c1",
                            "last_updated": "2024-01-01T00:00:00+00:00",
                        }
                    ]
                },
            )

        assert resp.status_code == 200
        assert resp.json() == mock_resp.model_dump(mode="json")
        mock_sync.assert_awaited_once_with(request_model, FAKE_USER)
        assert mock_log.set.call_args_list == [
            call(
                user={"id": USER_ID},
                conversation={"operation": "batch_sync"},
            )
        ]


class TestUpdateMessages:
    """PUT /api/v1/conversations/{id}/messages"""

    async def test_update_messages(self, client: AsyncClient):
        request_model = UpdateMessagesRequest(
            conversation_id="conv_123",
            messages=[MessageModel(type="user", response="hello")],
        )
        mock_resp = UpdateMessagesResponse(
            conversation_id="conv_123",
            message="Messages updated",
            modified_count=1,
            message_ids=["m_1"],
        )
        with (
            patch(f"{CONV_SERVICE}.log") as mock_log,
            patch(
                f"{CONV_SERVICE}.update_messages",
                new_callable=AsyncMock,
                return_value=mock_resp,
            ) as mock_update,
        ):
            resp = await client.put(
                "/api/v1/conversations/conv_123/messages",
                json={
                    "conversation_id": "conv_123",
                    "messages": [{"type": "user", "response": "hello"}],
                },
            )

        assert resp.status_code == 200
        assert resp.json() == mock_resp.model_dump(mode="json")
        mock_update.assert_awaited_once_with(request_model, FAKE_USER)
        assert mock_log.set.call_args_list == [
            call(
                user={"id": USER_ID},
                conversation={"operation": "update_messages"},
            )
        ]


class TestReadUnread:
    """PATCH /api/v1/conversations/{id}/read and /unread"""

    async def test_mark_as_read(self, client: AsyncClient):
        mock_resp = ConversationActionResponse(
            message="Conversation marked as read", conversation_id="conv_123"
        )
        with (
            patch(f"{CONV_SERVICE}.log") as mock_log,
            patch(
                f"{CONV_SERVICE}.mark_conversation_as_read",
                new_callable=AsyncMock,
                return_value=mock_resp,
            ) as mock_read,
        ):
            resp = await client.patch("/api/v1/conversations/conv_123/read")

        assert resp.status_code == 200
        assert resp.json() == mock_resp.model_dump(mode="json")
        mock_read.assert_awaited_once_with("conv_123", FAKE_USER)
        assert mock_log.set.call_args_list == [
            call(
                user={"id": USER_ID},
                conversation={"operation": "mark_read", "id": "conv_123"},
            )
        ]

    async def test_mark_as_unread(self, client: AsyncClient):
        mock_resp = ConversationActionResponse(
            message="Conversation marked as unread", conversation_id="conv_123"
        )
        with (
            patch(f"{CONV_SERVICE}.log") as mock_log,
            patch(
                f"{CONV_SERVICE}.mark_conversation_as_unread",
                new_callable=AsyncMock,
                return_value=mock_resp,
            ) as mock_unread,
        ):
            resp = await client.patch("/api/v1/conversations/conv_123/unread")

        assert resp.status_code == 200
        assert resp.json() == mock_resp.model_dump(mode="json")
        mock_unread.assert_awaited_once_with("conv_123", FAKE_USER)
        assert mock_log.set.call_args_list == [
            call(
                user={"id": USER_ID},
                conversation={"operation": "mark_unread", "id": "conv_123"},
            )
        ]


class TestPinnedMessages:
    """GET /api/v1/messages/pinned"""

    async def test_get_pinned(self, client: AsyncClient):
        # The payload key is "results", not "messages" — the old dict mock made
        # this test pass while asserting nothing about the real shape. A
        # non-empty row is deliberate: with results=[] the assertion cannot tell
        # a forwarded result from an empty one the endpoint invented itself.
        mock_resp = PinnedMessagesResponse(
            results=[
                ConversationMessageHit(
                    conversation_id="conv_123",
                    message=MessageModel(type="bot", response="pinned answer"),
                )
            ]
        )
        with (
            patch(f"{CONV_SERVICE}.log") as mock_log,
            patch(
                f"{CONV_SERVICE}.get_starred_messages",
                new_callable=AsyncMock,
                return_value=mock_resp,
            ) as mock_pinned,
        ):
            resp = await client.get("/api/v1/messages/pinned")

        assert resp.status_code == 200
        assert resp.json() == mock_resp.model_dump(mode="json")
        mock_pinned.assert_awaited_once_with(FAKE_USER)
        assert mock_log.set.call_args_list == [
            call(
                user={"id": USER_ID},
                conversation={"operation": "get_pinned"},
            )
        ]
