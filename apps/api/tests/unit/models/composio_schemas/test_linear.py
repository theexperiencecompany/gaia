"""Unit tests for app/models/composio_schemas/linear.py."""

from pydantic import ValidationError
import pytest

from app.models.composio_schemas.linear import (
    LinearCommentAddedPayload,
    LinearIssueCreatedPayload,
    LinearIssueUpdatedPayload,
)


class TestLinearIssueCreatedPayload:
    def test_valid_minimal(self):
        m = LinearIssueCreatedPayload()
        assert m.action is None
        assert m.data is None
        assert m.type is None
        assert m.url is None

    def test_valid_full(self):
        m = LinearIssueCreatedPayload(
            action="create",
            data={"identifier": "ENG-1"},
            type="Issue",
            url="https://linear.app/org/issue/ENG-1",
        )
        assert m.data == {"identifier": "ENG-1"}
        assert m.type == "Issue"

    def test_wrong_type_data(self):
        with pytest.raises(ValidationError):
            LinearIssueCreatedPayload(data=["not", "a", "dict"])


class TestLinearCommentAddedPayload:
    # Identical shape to LinearIssueCreatedPayload — same four optional fields.
    def test_valid_full(self):
        m = LinearCommentAddedPayload(
            action="create",
            data={"body": "hello"},
            type="Comment",
            url="https://linear.app/org/issue/ENG-1#comment-1",
        )
        assert m.data == {"body": "hello"}
        assert m.type == "Comment"

    def test_valid_minimal(self):
        m = LinearCommentAddedPayload()
        assert m.action is None
        assert m.url is None


class TestLinearIssueUpdatedPayload:
    # Same envelope as the other Linear triggers — action/data/type/url.
    def test_valid_full(self):
        m = LinearIssueUpdatedPayload(
            action="update",
            data={"identifier": "ENG-1", "state": "done"},
            type="Issue",
            url="https://linear.app/org/issue/ENG-1",
        )
        assert m.action == "update"
        assert m.data is not None
        assert m.type == "Issue"


# ---------------------------------------------------------------------------
# gmail trigger payloads
# ---------------------------------------------------------------------------
