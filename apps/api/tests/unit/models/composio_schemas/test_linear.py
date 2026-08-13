"""Unit tests for ``app.models.composio_schemas.linear`` trigger payloads."""

from app.models.composio_schemas.linear import (
    LinearCommentAddedPayload,
    LinearIssueCreatedPayload,
)


def test_issue_created_payload_parses() -> None:
    payload = LinearIssueCreatedPayload.model_validate(
        {
            "action": "create",
            "data": {"id": "issue-1", "title": "Fix login"},
            "type": "Issue",
            "url": "https://linear.app/x/issue/issue-1",
        }
    )
    assert payload.action == "create"
    assert payload.data == {"id": "issue-1", "title": "Fix login"}
    assert payload.type == "Issue"
    assert payload.url == "https://linear.app/x/issue/issue-1"


def test_issue_created_payload_defaults_to_none() -> None:
    payload = LinearIssueCreatedPayload.model_validate({})
    assert payload.action is None
    assert payload.data is None
    assert payload.type is None
    assert payload.url is None


def test_comment_added_payload_parses() -> None:
    payload = LinearCommentAddedPayload.model_validate(
        {"action": "create", "data": {"body": "nice", "id": "c-1"}, "type": "Comment"}
    )
    assert payload.data == {"body": "nice", "id": "c-1"}
    assert payload.type == "Comment"
    assert payload.url is None


def test_data_accepts_mixed_value_types() -> None:
    """``data: dict[str, object]`` must accept non-str values (lists, ints)."""
    payload = LinearCommentAddedPayload.model_validate(
        {"data": {"reactions": [1, 2], "edited": True, "body": "text"}}
    )
    assert payload.data == {"reactions": [1, 2], "edited": True, "body": "text"}
