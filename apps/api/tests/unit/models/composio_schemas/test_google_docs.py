"""Unit tests for app/models/composio_schemas/google_docs.py."""

from pydantic import ValidationError
import pytest

from app.models.composio_schemas.google_docs import GoogleDocsPageAddedPayload


class TestGoogleDocsPageAddedPayload:
    def test_valid_full(self):
        m = GoogleDocsPageAddedPayload(
            document={
                "createdTime": "2025-01-01T00:00:00Z",
                "id": "doc123",
                "mimeType": "application/vnd.google-apps.document",
                "modifiedTime": "2025-01-02T00:00:00Z",
                "name": "Notes",
                "lastModifyingUser": {"emailAddress": "a@b.com"},
                "owners": [{"emailAddress": "a@b.com"}],
            }
        )
        assert m.document is not None
        assert m.document.id == "doc123"
        assert m.document.name == "Notes"
        assert m.document.lastModifyingUser == {"emailAddress": "a@b.com"}
        assert m.document.owners == [{"emailAddress": "a@b.com"}]

    def test_document_optional(self):
        m = GoogleDocsPageAddedPayload()
        assert m.document is None

    def test_document_missing_required_field(self):
        with pytest.raises(ValidationError):
            GoogleDocsPageAddedPayload(document={"id": "doc123"})

    def test_document_wrong_type(self):
        with pytest.raises(ValidationError):
            GoogleDocsPageAddedPayload(document="not-a-doc")


# ---------------------------------------------------------------------------
# google_sheets
# ---------------------------------------------------------------------------
