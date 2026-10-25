"""An in-process S3 bucket behind the store's S3Client protocol (kept apart so other suites import no boto)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import io

from botocore.exceptions import ClientError

from app.services.blob_store import S3Object


@dataclass
class _StoredObject:
    body: bytes
    content_type: str
    metadata: dict[str, str]


def s3_client_error(code: str, operation: str) -> ClientError:
    """Build the ClientError botocore raises for an S3 error code."""
    return ClientError({"Error": {"Code": code, "Message": code}}, operation)


@dataclass
class FakeS3Client:
    """One bucket's objects in memory, and every call it took; refuse_with fails each with that S3 code."""

    bucket: str
    objects: dict[str, _StoredObject] = field(default_factory=dict)
    refuse_with: str | None = None
    calls: list[tuple[str, dict[str, object]]] = field(default_factory=list)

    def _check(self, bucket: str, operation: str) -> None:
        if self.refuse_with is not None:
            raise s3_client_error(self.refuse_with, operation)
        if bucket != self.bucket:
            raise s3_client_error("NoSuchBucket", operation)

    def put_object(
        self, *, Bucket: str, Key: str, Body: bytes, ContentType: str, Metadata: Mapping[str, str]
    ) -> object:
        self.calls.append(
            (
                "PutObject",
                {
                    "Bucket": Bucket,
                    "Key": Key,
                    "Body": Body,
                    "ContentType": ContentType,
                    "Metadata": Metadata,
                },
            )
        )
        self._check(Bucket, "PutObject")
        self.objects[Key] = _StoredObject(Body, ContentType, dict(Metadata))
        return {}

    def get_object(self, *, Bucket: str, Key: str) -> S3Object:
        self._check(Bucket, "GetObject")
        stored = self.objects.get(Key)
        if stored is None:
            raise s3_client_error("NoSuchKey", "GetObject")
        return {
            "Body": io.BytesIO(stored.body),
            "ContentType": stored.content_type,
            "Metadata": {"kind": stored.metadata["kind"]},
        }

    def delete_object(self, *, Bucket: str, Key: str) -> object:
        self.calls.append(("DeleteObject", {"Bucket": Bucket, "Key": Key}))
        self._check(Bucket, "DeleteObject")
        self.objects.pop(Key, None)
        return {}
