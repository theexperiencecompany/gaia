"""Unit tests for ``app.models.composio_schemas.google_docs`` trigger payloads."""

from pydantic import ValidationError
import pytest

from app.models.composio_schemas.google_docs import (
    GoogleDocsDocument,
    GoogleDocsPageAddedPayload,
)


def test_document_parses_with_owner_and_modifier_dicts() -> None:
    doc = GoogleDocsDocument.model_validate(
        {
            "createdTime": "2026-01-01T00:00:00Z",
            "id": "doc-1",
            "name": "Quarterly plan",
            "mimeType": "application/vnd.google-apps.document",
            "modifiedTime": "2026-01-02T00:00:00Z",
            "lastModifyingUser": {"email": "a@b.c", "displayName": "Ann"},
            "owners": [{"email": "a@b.c"}],
        }
    )
    assert doc.id == "doc-1"
    assert doc.lastModifyingUser == {"email": "a@b.c", "displayName": "Ann"}
    assert doc.owners == [{"email": "a@b.c"}]


def test_document_requires_id_and_name() -> None:
    with pytest.raises(ValidationError):
        GoogleDocsDocument.model_validate(
            {
                "createdTime": "2026-01-01T00:00:00Z",
                "name": "no id",
                "mimeType": "application/vnd.google-apps.document",
                "modifiedTime": "2026-01-02T00:00:00Z",
            }
        )


def test_page_added_payload_wraps_optional_document() -> None:
    empty = GoogleDocsPageAddedPayload.model_validate({})
    assert empty.document is None

    payload = GoogleDocsPageAddedPayload.model_validate(
        {
            "document": {
                "createdTime": "2026-01-01T00:00:00Z",
                "id": "doc-1",
                "name": "Plan",
                "mimeType": "application/vnd.google-apps.document",
                "modifiedTime": "2026-01-02T00:00:00Z",
            }
        }
    )
    assert payload.document is not None
    assert payload.document.id == "doc-1"
    assert payload.document.owners is None
