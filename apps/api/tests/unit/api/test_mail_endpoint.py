"""Unit tests for mail (Gmail) API endpoints.

Tests the Gmail endpoints with mocked service layer and integration
dependency to verify routing, status codes, response bodies, and validation.

Gmail endpoints use ``require_integration("gmail")`` which internally calls
``check_integration_status``.  We patch that function to return ``True`` so
the dependency passes without a real Composio/Redis connection.
"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

MAIL_BASE = "/api/v1"

# All tests in this module need the integration check to pass.
pytestmark = [
    pytest.mark.unit,
    pytest.mark.usefixtures("_bypass_integration_check"),
]


@pytest.fixture(autouse=True)
async def _bypass_integration_check():
    """Patch check_integration_status so require_integration("gmail") passes."""
    with patch(
        "app.api.v1.dependencies.google_scope_dependencies.check_integration_status",
        new_callable=AsyncMock,
        return_value=True,
    ):
        yield


# ---------------------------------------------------------------------------
# GET /api/v1/gmail/labels
# ---------------------------------------------------------------------------


class TestListLabels:
    @patch(
        "app.api.v1.endpoints.mail.list_labels_service",
        new_callable=AsyncMock,
    )
    async def test_list_labels_returns_200(
        self, mock_labels: AsyncMock, client: AsyncClient
    ):
        mock_labels.return_value = {
            "success": True,
            "labels": [{"id": "INBOX", "name": "INBOX"}],
            "count": 1,
        }
        response = await client.get(f"{MAIL_BASE}/gmail/labels")
        assert response.status_code == 200
        data = response.json()
        assert "labels" in data
        assert data["count"] == 1

    @patch(
        "app.api.v1.endpoints.mail.list_labels_service",
        new_callable=AsyncMock,
    )
    async def test_list_labels_service_failure_returns_500(
        self, mock_labels: AsyncMock, client: AsyncClient
    ):
        mock_labels.return_value = {"success": False, "error": "API error"}
        response = await client.get(f"{MAIL_BASE}/gmail/labels")
        assert response.status_code == 500


# ---------------------------------------------------------------------------
# GET /api/v1/gmail/messages
# ---------------------------------------------------------------------------


class TestListMessages:
    @patch(
        "app.api.v1.endpoints.mail.search_messages",
        new_callable=AsyncMock,
    )
    async def test_list_messages_returns_200(
        self, mock_search: AsyncMock, client: AsyncClient
    ):
        mock_search.return_value = {
            "messages": [{"id": "msg-1", "snippet": "Hello"}],
            "nextPageToken": None,
        }
        response = await client.get(f"{MAIL_BASE}/gmail/messages")
        assert response.status_code == 200
        data = response.json()
        assert len(data["messages"]) == 1
        assert data["nextPageToken"] is None

    @patch(
        "app.api.v1.endpoints.mail.search_messages",
        new_callable=AsyncMock,
    )
    async def test_list_messages_with_pagination(
        self, mock_search: AsyncMock, client: AsyncClient
    ):
        mock_search.return_value = {
            "messages": [{"id": "msg-2"}],
            "nextPageToken": "token-abc",
        }
        response = await client.get(
            f"{MAIL_BASE}/gmail/messages",
            params={"max_results": 10, "pageToken": "prev-token"},
        )
        assert response.status_code == 200
        assert response.json()["nextPageToken"] == "token-abc"

    @patch(
        "app.api.v1.endpoints.mail.search_messages",
        new_callable=AsyncMock,
    )
    async def test_list_messages_service_error_returns_500(
        self, mock_search: AsyncMock, client: AsyncClient
    ):
        mock_search.side_effect = Exception("Gmail API error")
        response = await client.get(f"{MAIL_BASE}/gmail/messages")
        assert response.status_code == 500


# ---------------------------------------------------------------------------
# GET /api/v1/gmail/message/{message_id}
# ---------------------------------------------------------------------------


class TestGetEmailById:
    @patch(
        "app.api.v1.endpoints.mail.get_email_by_id_service",
        new_callable=AsyncMock,
    )
    async def test_get_email_returns_200(
        self, mock_get: AsyncMock, client: AsyncClient
    ):
        mock_get.return_value = {
            "success": True,
            "message": {"id": "msg-1", "subject": "Test"},
        }
        response = await client.get(f"{MAIL_BASE}/gmail/message/msg-1")
        assert response.status_code == 200
        data = response.json()
        assert data["message"]["id"] == "msg-1"
        assert data["status"] == "Message retrieved successfully"

    @patch(
        "app.api.v1.endpoints.mail.get_email_by_id_service",
        new_callable=AsyncMock,
    )
    async def test_get_email_not_found_returns_404(
        self, mock_get: AsyncMock, client: AsyncClient
    ):
        mock_get.return_value = {
            "success": False,
            "error": "Message not found",
        }
        response = await client.get(f"{MAIL_BASE}/gmail/message/nonexistent")
        assert response.status_code == 404

    @patch(
        "app.api.v1.endpoints.mail.get_email_by_id_service",
        new_callable=AsyncMock,
    )
    async def test_get_email_service_failure_returns_500(
        self, mock_get: AsyncMock, client: AsyncClient
    ):
        mock_get.return_value = {
            "success": False,
            "error": "Internal failure",
        }
        response = await client.get(f"{MAIL_BASE}/gmail/message/msg-1")
        assert response.status_code == 500


# ---------------------------------------------------------------------------
# GET /api/v1/gmail/search
# ---------------------------------------------------------------------------


class TestSearchEmails:
    @patch(
        "app.api.v1.endpoints.mail.search_messages",
        new_callable=AsyncMock,
    )
    async def test_search_emails_returns_200(
        self, mock_search: AsyncMock, client: AsyncClient
    ):
        mock_search.return_value = {
            "messages": [{"id": "msg-1"}],
            "nextPageToken": None,
        }
        response = await client.get(
            f"{MAIL_BASE}/gmail/search", params={"query": "invoice"}
        )
        assert response.status_code == 200

    @patch(
        "app.api.v1.endpoints.mail.search_messages",
        new_callable=AsyncMock,
    )
    async def test_search_emails_with_filters(
        self, mock_search: AsyncMock, client: AsyncClient
    ):
        mock_search.return_value = {"messages": [], "nextPageToken": None}
        response = await client.get(
            f"{MAIL_BASE}/gmail/search",
            params={
                "sender": "boss@company.com",
                "has_attachment": True,
                "is_read": False,
                "max_results": 5,
            },
        )
        assert response.status_code == 200
        # Verify the query was constructed with filters
        call_kwargs = mock_search.call_args.kwargs
        assert "from:boss@company.com" in call_kwargs["query"]
        assert "has:attachment" in call_kwargs["query"]
        assert "is:unread" in call_kwargs["query"]

    @patch(
        "app.api.v1.endpoints.mail.search_messages",
        new_callable=AsyncMock,
    )
    async def test_search_emails_caps_max_results_at_20(
        self, mock_search: AsyncMock, client: AsyncClient
    ):
        mock_search.return_value = {"messages": [], "nextPageToken": None}
        await client.get(
            f"{MAIL_BASE}/gmail/search",
            params={"query": "test", "max_results": 100},
        )
        call_kwargs = mock_search.call_args.kwargs
        assert call_kwargs["max_results"] == 20


# ---------------------------------------------------------------------------
# POST /api/v1/gmail/send-json
# ---------------------------------------------------------------------------


class TestSendEmailJson:
    @patch(
        "app.api.v1.endpoints.mail.send_email",
        new_callable=AsyncMock,
    )
    async def test_send_email_json_returns_200(
        self, mock_send: AsyncMock, client: AsyncClient
    ):
        mock_send.return_value = {"id": "sent-001"}
        response = await client.post(
            f"{MAIL_BASE}/gmail/send-json",
            json={
                "to": ["recipient@example.com"],
                "subject": "Hello",
                "body": "Test email body",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["message_id"] == "sent-001"
        assert data["status"] == "Email sent successfully"

    @patch(
        "app.api.v1.endpoints.mail.send_email",
        new_callable=AsyncMock,
    )
    async def test_send_email_json_with_cc_bcc(
        self, mock_send: AsyncMock, client: AsyncClient
    ):
        mock_send.return_value = {"id": "sent-002"}
        response = await client.post(
            f"{MAIL_BASE}/gmail/send-json",
            json={
                "to": ["a@test.com"],
                "subject": "CC Test",
                "body": "Body",
                "cc": ["cc@test.com"],
                "bcc": ["bcc@test.com"],
            },
        )
        assert response.status_code == 200

    async def test_send_email_json_missing_to_returns_422(self, client: AsyncClient):
        response = await client.post(
            f"{MAIL_BASE}/gmail/send-json",
            json={"subject": "Test", "body": "Body"},
        )
        assert response.status_code == 422

    async def test_send_email_json_missing_subject_returns_422(
        self, client: AsyncClient
    ):
        response = await client.post(
            f"{MAIL_BASE}/gmail/send-json",
            json={"to": ["a@test.com"], "body": "Body"},
        )
        assert response.status_code == 422

    async def test_send_email_json_missing_body_returns_422(self, client: AsyncClient):
        response = await client.post(
            f"{MAIL_BASE}/gmail/send-json",
            json={"to": ["a@test.com"], "subject": "Test"},
        )
        assert response.status_code == 422

    @patch(
        "app.api.v1.endpoints.mail.send_email",
        new_callable=AsyncMock,
    )
    async def test_send_email_json_service_error_returns_500(
        self, mock_send: AsyncMock, client: AsyncClient
    ):
        mock_send.side_effect = Exception("SMTP error")
        response = await client.post(
            f"{MAIL_BASE}/gmail/send-json",
            json={
                "to": ["a@test.com"],
                "subject": "Test",
                "body": "Body",
            },
        )
        assert response.status_code == 500


# ---------------------------------------------------------------------------
# POST /api/v1/gmail/mark-as-read
# ---------------------------------------------------------------------------


class TestMarkAsRead:
    @patch(
        "app.api.v1.endpoints.mail.mark_messages_as_read",
        new_callable=AsyncMock,
    )
    async def test_mark_as_read_returns_200(
        self, mock_mark: AsyncMock, client: AsyncClient
    ):
        mock_mark.return_value = [{"id": "msg-1"}, {"id": "msg-2"}]
        response = await client.post(
            f"{MAIL_BASE}/gmail/mark-as-read",
            json={"message_ids": ["msg-1", "msg-2"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["count"] == 2
        assert "msg-1" in data["marked_as_read"]

    async def test_mark_as_read_missing_ids_returns_422(self, client: AsyncClient):
        response = await client.post(f"{MAIL_BASE}/gmail/mark-as-read", json={})
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/v1/gmail/mark-as-unread
# ---------------------------------------------------------------------------


class TestMarkAsUnread:
    @patch(
        "app.api.v1.endpoints.mail.mark_messages_as_unread",
        new_callable=AsyncMock,
    )
    async def test_mark_as_unread_returns_200(
        self, mock_mark: AsyncMock, client: AsyncClient
    ):
        mock_mark.return_value = [{"id": "msg-1"}]
        response = await client.post(
            f"{MAIL_BASE}/gmail/mark-as-unread",
            json={"message_ids": ["msg-1"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["count"] == 1


# ---------------------------------------------------------------------------
# POST /api/v1/gmail/star
# ---------------------------------------------------------------------------


class TestStarEmails:
    @patch(
        "app.api.v1.endpoints.mail.star_messages",
        new_callable=AsyncMock,
    )
    async def test_star_emails_returns_200(
        self, mock_star: AsyncMock, client: AsyncClient
    ):
        mock_star.return_value = [{"id": "msg-1"}]
        response = await client.post(
            f"{MAIL_BASE}/gmail/star",
            json={"message_ids": ["msg-1"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "msg-1" in data["starred"]

    @patch(
        "app.api.v1.endpoints.mail.star_messages",
        new_callable=AsyncMock,
    )
    async def test_star_emails_service_error_returns_500(
        self, mock_star: AsyncMock, client: AsyncClient
    ):
        mock_star.side_effect = Exception("API error")
        response = await client.post(
            f"{MAIL_BASE}/gmail/star",
            json={"message_ids": ["msg-1"]},
        )
        assert response.status_code == 500


# ---------------------------------------------------------------------------
# POST /api/v1/gmail/unstar
# ---------------------------------------------------------------------------


class TestUnstarEmails:
    @patch(
        "app.api.v1.endpoints.mail.unstar_messages",
        new_callable=AsyncMock,
    )
    async def test_unstar_emails_returns_200(
        self, mock_unstar: AsyncMock, client: AsyncClient
    ):
        mock_unstar.return_value = [{"id": "msg-1"}]
        response = await client.post(
            f"{MAIL_BASE}/gmail/unstar",
            json={"message_ids": ["msg-1"]},
        )
        assert response.status_code == 200
        assert response.json()["success"] is True


# ---------------------------------------------------------------------------
# POST /api/v1/gmail/trash
# ---------------------------------------------------------------------------


class TestTrashEmails:
    @patch(
        "app.api.v1.endpoints.mail.trash_messages",
        new_callable=AsyncMock,
    )
    async def test_trash_returns_200(self, mock_trash: AsyncMock, client: AsyncClient):
        mock_trash.return_value = [{"id": "msg-1"}]
        response = await client.post(
            f"{MAIL_BASE}/gmail/trash",
            json={"message_ids": ["msg-1"]},
        )
        assert response.status_code == 200
        assert response.json()["success"] is True
        assert "msg-1" in response.json()["trashed"]


# ---------------------------------------------------------------------------
# POST /api/v1/gmail/untrash
# ---------------------------------------------------------------------------


class TestUntrashEmails:
    @patch(
        "app.api.v1.endpoints.mail.untrash_messages",
        new_callable=AsyncMock,
    )
    async def test_untrash_returns_200(
        self, mock_untrash: AsyncMock, client: AsyncClient
    ):
        mock_untrash.return_value = [{"id": "msg-1"}]
        response = await client.post(
            f"{MAIL_BASE}/gmail/untrash",
            json={"message_ids": ["msg-1"]},
        )
        assert response.status_code == 200
        assert response.json()["success"] is True
        assert "msg-1" in response.json()["restored"]


# ---------------------------------------------------------------------------
# POST /api/v1/gmail/archive
# ---------------------------------------------------------------------------


class TestArchiveEmails:
    @patch(
        "app.api.v1.endpoints.mail.archive_messages",
        new_callable=AsyncMock,
    )
    async def test_archive_returns_200(
        self, mock_archive: AsyncMock, client: AsyncClient
    ):
        mock_archive.return_value = [{"id": "msg-1"}]
        response = await client.post(
            f"{MAIL_BASE}/gmail/archive",
            json={"message_ids": ["msg-1"]},
        )
        assert response.status_code == 200
        assert response.json()["success"] is True
        assert "msg-1" in response.json()["archived"]


# ---------------------------------------------------------------------------
# POST /api/v1/gmail/move-to-inbox
# ---------------------------------------------------------------------------


class TestMoveToInbox:
    @patch(
        "app.api.v1.endpoints.mail.move_to_inbox",
        new_callable=AsyncMock,
    )
    async def test_move_to_inbox_returns_200(
        self, mock_move: AsyncMock, client: AsyncClient
    ):
        mock_move.return_value = [{"id": "msg-1"}]
        response = await client.post(
            f"{MAIL_BASE}/gmail/move-to-inbox",
            json={"message_ids": ["msg-1"]},
        )
        assert response.status_code == 200
        assert response.json()["success"] is True
        assert "msg-1" in response.json()["moved_to_inbox"]


# ---------------------------------------------------------------------------
# GET /api/v1/gmail/thread/{thread_id}
# ---------------------------------------------------------------------------


class TestGetThread:
    @patch(
        "app.api.v1.endpoints.mail.fetch_thread",
        new_callable=AsyncMock,
    )
    async def test_get_thread_returns_200(
        self, mock_fetch: AsyncMock, client: AsyncClient
    ):
        mock_fetch.return_value = {
            "messages": [
                {"id": "msg-1", "threadId": "thread-1"},
                {"id": "msg-2", "threadId": "thread-1"},
            ]
        }
        response = await client.get(f"{MAIL_BASE}/gmail/thread/thread-1")
        assert response.status_code == 200
        data = response.json()
        assert data["thread_id"] == "thread-1"
        assert data["messages_count"] == 2

    @patch(
        "app.api.v1.endpoints.mail.fetch_thread",
        new_callable=AsyncMock,
    )
    async def test_get_thread_service_error_returns_500(
        self, mock_fetch: AsyncMock, client: AsyncClient
    ):
        mock_fetch.side_effect = Exception("Thread not found")
        response = await client.get(f"{MAIL_BASE}/gmail/thread/bad-id")
        assert response.status_code == 500


# ---------------------------------------------------------------------------
# POST /api/v1/gmail/labels (create)
# ---------------------------------------------------------------------------


class TestCreateLabel:
    @patch(
        "app.api.v1.endpoints.mail.create_label",
        new_callable=AsyncMock,
    )
    async def test_create_label_returns_200(
        self, mock_create: AsyncMock, client: AsyncClient
    ):
        mock_create.return_value = {"id": "Label_1", "name": "Important"}
        response = await client.post(
            f"{MAIL_BASE}/gmail/labels",
            json={"name": "Important"},
        )
        assert response.status_code == 200
        assert response.json()["id"] == "Label_1"

    async def test_create_label_missing_name_returns_422(self, client: AsyncClient):
        response = await client.post(f"{MAIL_BASE}/gmail/labels", json={})
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# PUT /api/v1/gmail/labels/{label_id}
# ---------------------------------------------------------------------------


class TestUpdateLabel:
    @patch(
        "app.api.v1.endpoints.mail.update_label",
        new_callable=AsyncMock,
    )
    async def test_update_label_returns_200(
        self, mock_update: AsyncMock, client: AsyncClient
    ):
        mock_update.return_value = {"id": "Label_1", "name": "Renamed"}
        response = await client.put(
            f"{MAIL_BASE}/gmail/labels/Label_1",
            json={"name": "Renamed"},
        )
        assert response.status_code == 200
        assert response.json()["name"] == "Renamed"


# ---------------------------------------------------------------------------
# DELETE /api/v1/gmail/labels/{label_id}
# ---------------------------------------------------------------------------


class TestDeleteLabel:
    @patch(
        "app.api.v1.endpoints.mail.delete_label",
        new_callable=AsyncMock,
    )
    async def test_delete_label_success(
        self, mock_delete: AsyncMock, client: AsyncClient
    ):
        mock_delete.return_value = True
        response = await client.delete(f"{MAIL_BASE}/gmail/labels/Label_1")
        assert response.status_code == 200
        assert response.json()["status"] == "success"

    @patch(
        "app.api.v1.endpoints.mail.delete_label",
        new_callable=AsyncMock,
    )
    async def test_delete_label_failure(
        self, mock_delete: AsyncMock, client: AsyncClient
    ):
        mock_delete.return_value = False
        response = await client.delete(f"{MAIL_BASE}/gmail/labels/Label_1")
        assert response.status_code == 200
        assert response.json()["status"] == "error"


# ---------------------------------------------------------------------------
# POST /api/v1/gmail/messages/apply-label
# ---------------------------------------------------------------------------


class TestApplyLabels:
    @patch(
        "app.api.v1.endpoints.mail.apply_labels",
        new_callable=AsyncMock,
    )
    async def test_apply_labels_returns_200(
        self, mock_apply: AsyncMock, client: AsyncClient
    ):
        mock_apply.return_value = [{"id": "msg-1"}]
        response = await client.post(
            f"{MAIL_BASE}/gmail/messages/apply-label",
            json={"message_ids": ["msg-1"], "label_ids": ["Label_1"]},
        )
        assert response.status_code == 200
        assert response.json()["success"] is True

    async def test_apply_labels_missing_fields_returns_422(self, client: AsyncClient):
        response = await client.post(
            f"{MAIL_BASE}/gmail/messages/apply-label",
            json={"message_ids": ["msg-1"]},
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/v1/gmail/messages/remove-label
# ---------------------------------------------------------------------------


class TestRemoveLabels:
    @patch(
        "app.api.v1.endpoints.mail.remove_labels",
        new_callable=AsyncMock,
    )
    async def test_remove_labels_returns_200(
        self, mock_remove: AsyncMock, client: AsyncClient
    ):
        mock_remove.return_value = [{"id": "msg-1"}]
        response = await client.post(
            f"{MAIL_BASE}/gmail/messages/remove-label",
            json={"message_ids": ["msg-1"], "label_ids": ["Label_1"]},
        )
        assert response.status_code == 200
        assert response.json()["success"] is True


# ---------------------------------------------------------------------------
# POST /api/v1/gmail/drafts (create)
# ---------------------------------------------------------------------------


class TestCreateDraft:
    @patch(
        "app.api.v1.endpoints.mail.create_draft",
        new_callable=AsyncMock,
    )
    async def test_create_draft_returns_200(
        self, mock_create: AsyncMock, client: AsyncClient
    ):
        mock_create.return_value = {
            "id": "draft-001",
            "message": {"id": "msg-draft-001"},
        }
        response = await client.post(
            f"{MAIL_BASE}/gmail/drafts",
            json={
                "to": ["recipient@test.com"],
                "subject": "Draft Subject",
                "body": "Draft Body",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["draft_id"] == "draft-001"
        assert data["status"] == "Draft created successfully"

    async def test_create_draft_missing_to_returns_422(self, client: AsyncClient):
        response = await client.post(
            f"{MAIL_BASE}/gmail/drafts",
            json={"subject": "Test", "body": "Body"},
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/gmail/drafts
# ---------------------------------------------------------------------------


class TestListDrafts:
    @patch(
        "app.api.v1.endpoints.mail.list_drafts",
        new_callable=AsyncMock,
    )
    async def test_list_drafts_returns_200(
        self, mock_list: AsyncMock, client: AsyncClient
    ):
        mock_list.return_value = {
            "drafts": [{"id": "draft-001"}],
            "nextPageToken": None,
        }
        response = await client.get(f"{MAIL_BASE}/gmail/drafts")
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# GET /api/v1/gmail/drafts/{draft_id}
# ---------------------------------------------------------------------------


class TestGetDraft:
    @patch(
        "app.api.v1.endpoints.mail.get_draft",
        new_callable=AsyncMock,
    )
    async def test_get_draft_returns_200(
        self, mock_get: AsyncMock, client: AsyncClient
    ):
        mock_get.return_value = {"id": "draft-001", "message": {"id": "msg-001"}}
        response = await client.get(f"{MAIL_BASE}/gmail/drafts/draft-001")
        assert response.status_code == 200

    @patch(
        "app.api.v1.endpoints.mail.get_draft",
        new_callable=AsyncMock,
    )
    async def test_get_draft_error_returns_500(
        self, mock_get: AsyncMock, client: AsyncClient
    ):
        mock_get.side_effect = Exception("Not found")
        response = await client.get(f"{MAIL_BASE}/gmail/drafts/bad-id")
        assert response.status_code == 500


# ---------------------------------------------------------------------------
# PUT /api/v1/gmail/drafts/{draft_id}
# ---------------------------------------------------------------------------


class TestUpdateDraft:
    @patch(
        "app.api.v1.endpoints.mail.update_draft",
        new_callable=AsyncMock,
    )
    async def test_update_draft_returns_200(
        self, mock_update: AsyncMock, client: AsyncClient
    ):
        mock_update.return_value = {
            "id": "draft-001",
            "message": {"id": "msg-updated"},
        }
        response = await client.put(
            f"{MAIL_BASE}/gmail/drafts/draft-001",
            json={
                "to": ["new@test.com"],
                "subject": "Updated",
                "body": "Updated body",
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "Draft updated successfully"


# ---------------------------------------------------------------------------
# DELETE /api/v1/gmail/drafts/{draft_id}
# ---------------------------------------------------------------------------


class TestDeleteDraft:
    @patch(
        "app.api.v1.endpoints.mail.delete_draft",
        new_callable=AsyncMock,
    )
    async def test_delete_draft_success(
        self, mock_delete: AsyncMock, client: AsyncClient
    ):
        mock_delete.return_value = True
        response = await client.delete(f"{MAIL_BASE}/gmail/drafts/draft-001")
        assert response.status_code == 200
        assert response.json()["status"] == "success"

    @patch(
        "app.api.v1.endpoints.mail.delete_draft",
        new_callable=AsyncMock,
    )
    async def test_delete_draft_failure(
        self, mock_delete: AsyncMock, client: AsyncClient
    ):
        mock_delete.return_value = False
        response = await client.delete(f"{MAIL_BASE}/gmail/drafts/draft-001")
        assert response.status_code == 200
        assert response.json()["status"] == "error"


# ---------------------------------------------------------------------------
# POST /api/v1/gmail/drafts/{draft_id}/send
# ---------------------------------------------------------------------------


class TestSendDraft:
    @patch(
        "app.api.v1.endpoints.mail.send_draft",
        new_callable=AsyncMock,
    )
    async def test_send_draft_returns_200(
        self, mock_send: AsyncMock, client: AsyncClient
    ):
        mock_send.return_value = {
            "successful": True,
            "id": "sent-001",
            "threadId": "thread-001",
        }
        response = await client.post(f"{MAIL_BASE}/gmail/drafts/draft-001/send")
        assert response.status_code == 200
        data = response.json()
        assert data["successful"] is True
        assert data["status"] == "Draft sent successfully"

    @patch(
        "app.api.v1.endpoints.mail.send_draft",
        new_callable=AsyncMock,
    )
    async def test_send_draft_failure_returns_500(
        self, mock_send: AsyncMock, client: AsyncClient
    ):
        mock_send.return_value = {
            "successful": False,
            "error": "Draft expired",
        }
        response = await client.post(f"{MAIL_BASE}/gmail/drafts/draft-001/send")
        assert response.status_code == 500


# ---------------------------------------------------------------------------
# GET /api/v1/gmail/importance-summaries
# ---------------------------------------------------------------------------


class TestGetImportanceSummaries:
    @patch(
        "app.api.v1.endpoints.mail.get_importance_summaries_service",
        new_callable=AsyncMock,
    )
    async def test_returns_200(self, mock_svc: AsyncMock, client: AsyncClient):
        mock_svc.return_value = {"summaries": [], "count": 0}
        response = await client.get(f"{MAIL_BASE}/gmail/importance-summaries")
        assert response.status_code == 200

    @patch(
        "app.api.v1.endpoints.mail.get_importance_summaries_service",
        new_callable=AsyncMock,
    )
    async def test_with_params(self, mock_svc: AsyncMock, client: AsyncClient):
        mock_svc.return_value = {"summaries": [], "count": 0}
        response = await client.get(
            f"{MAIL_BASE}/gmail/importance-summaries",
            params={"limit": 10, "important_only": True},
        )
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# GET /api/v1/gmail/importance-summary/{message_id}
# ---------------------------------------------------------------------------


class TestGetSingleImportanceSummary:
    @patch(
        "app.api.v1.endpoints.mail.get_single_importance_summary_service",
        new_callable=AsyncMock,
    )
    async def test_returns_200(self, mock_svc: AsyncMock, client: AsyncClient):
        mock_svc.return_value = {
            "is_important": True,
            "importance_level": "HIGH",
            "summary": "Action required",
        }
        response = await client.get(f"{MAIL_BASE}/gmail/importance-summary/msg-1")
        assert response.status_code == 200

    @patch(
        "app.api.v1.endpoints.mail.get_single_importance_summary_service",
        new_callable=AsyncMock,
    )
    async def test_not_found_returns_404(
        self, mock_svc: AsyncMock, client: AsyncClient
    ):
        mock_svc.return_value = None
        response = await client.get(f"{MAIL_BASE}/gmail/importance-summary/nonexistent")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/v1/gmail/importance-summaries/bulk
# ---------------------------------------------------------------------------


class TestBulkImportanceSummaries:
    @patch(
        "app.api.v1.endpoints.mail.get_bulk_importance_summaries_service",
        new_callable=AsyncMock,
    )
    async def test_returns_200(self, mock_svc: AsyncMock, client: AsyncClient):
        mock_svc.return_value = {"summaries": {}, "count": 0}
        response = await client.post(
            f"{MAIL_BASE}/gmail/importance-summaries/bulk",
            json={"message_ids": ["msg-1", "msg-2"]},
        )
        assert response.status_code == 200

    async def test_missing_message_ids_returns_422(self, client: AsyncClient):
        response = await client.post(
            f"{MAIL_BASE}/gmail/importance-summaries/bulk",
            json={},
        )
        assert response.status_code == 422
