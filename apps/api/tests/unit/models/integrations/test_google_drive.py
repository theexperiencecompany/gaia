"""Unit tests for the Google Drive payload models."""

from app.models.integrations.google_drive import (
    GoogleDriveFile,
    GoogleDriveFileList,
    GoogleDrivePermission,
    GoogleDrivePermissionCreate,
)


class TestGoogleDriveFileList:
    def test_reads_the_projected_fields_and_ignores_the_rest(self) -> None:
        page = GoogleDriveFileList.model_validate(
            {
                "kind": "drive#fileList",
                "incompleteSearch": False,
                "files": [
                    {
                        "id": "f1",
                        "name": "Plan",
                        "modifiedTime": "2026-01-02T03:04:05.000Z",
                        "webViewLink": "https://docs.google.com/document/d/f1/edit",
                        "mimeType": "application/vnd.google-apps.document",
                    }
                ],
            }
        )
        assert page.files == [
            GoogleDriveFile(
                id="f1",
                name="Plan",
                modifiedTime="2026-01-02T03:04:05.000Z",
                webViewLink="https://docs.google.com/document/d/f1/edit",
            )
        ]

    def test_missing_files_key_is_an_empty_list(self) -> None:
        assert GoogleDriveFileList.model_validate({}).files == []

    def test_a_partial_file_row_keeps_absent_fields_none(self) -> None:
        (file,) = GoogleDriveFileList.model_validate({"files": [{"id": "f1"}]}).files
        assert (file.id, file.name, file.modifiedTime, file.webViewLink) == ("f1", None, None, None)


class TestGoogleDrivePermission:
    def test_create_body_serializes_exactly_the_grant(self) -> None:
        body = GoogleDrivePermissionCreate(type="user", role="writer", emailAddress="a@x.com")
        assert body.model_dump(exclude_none=True) == {
            "type": "user",
            "role": "writer",
            "emailAddress": "a@x.com",
        }

    def test_permission_id_is_read_and_absent_is_none(self) -> None:
        assert GoogleDrivePermission.model_validate({"id": "perm-1", "kind": "x"}).id == "perm-1"
        assert GoogleDrivePermission.model_validate({}).id is None
