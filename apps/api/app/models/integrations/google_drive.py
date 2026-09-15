"""Google Drive v3 payloads the Docs and Sheets tools read and send.

Reference: https://developers.google.com/workspace/drive/api/reference/rest/v3
"""

from pydantic import BaseModel, ConfigDict, Field


class GoogleDriveFile(BaseModel):
    """One ``files.list`` item under the ``files(id,name,modifiedTime,webViewLink)`` projection.

    Every field is optional: the tools request a projection, and Drive omits a
    field the caller's scope cannot see rather than sending ``null``.
    """

    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    name: str | None = None
    modifiedTime: str | None = None
    webViewLink: str | None = None


class GoogleDriveFileList(BaseModel):
    """``GET /drive/v3/files`` — ``files`` is absent when nothing matched."""

    model_config = ConfigDict(extra="ignore")

    files: list[GoogleDriveFile] = Field(default_factory=list)


class GoogleDrivePermissionCreate(BaseModel):
    """Body of ``POST /drive/v3/files/{id}/permissions`` for a single user grant."""

    type: str
    role: str
    emailAddress: str


class GoogleDrivePermission(BaseModel):
    """The ``permissions`` resource Drive returns for a grant — only ``id`` is read."""

    model_config = ConfigDict(extra="ignore")

    id: str | None = None
