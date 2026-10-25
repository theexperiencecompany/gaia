"""BLOB_STORE=s3: private objects in one bucket, a boot probe that names what is wrong."""

from __future__ import annotations

from collections.abc import Iterator

from botocore.exceptions import EndpointConnectionError
import pytest

from app.config.deployment import BlobStoreKind
from app.config.settings import settings
from app.constants.files import (
    S3_MAX_ATTEMPTS,
    S3_TIMEOUT_SECONDS,
    S3_WRITE_PROBE_KEY,
    BlobKind,
    S3AddressingStyle,
)
from app.services.blob_store import (
    S3BlobStore,
    blob_store,
    ensure_blob_store_ready,
    open_readable_blob,
    s3_blob_store,
)
from app.utils.errors import AppError
from tests.helpers import captured_wide_event
from tests.s3_fakes import FakeS3Client, s3_client_error

BUCKET = "gaia-files"
ENDPOINT = "https://s3.example.test"


@pytest.fixture
def bucket() -> FakeS3Client:
    return FakeS3Client(BUCKET)


@pytest.fixture
def store(bucket: FakeS3Client) -> S3BlobStore:
    return S3BlobStore(bucket, BUCKET, ENDPOINT)


@pytest.fixture
def s3_deployment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Boot a self-host instance with BLOB_STORE=s3 and every bucket setting present."""
    monkeypatch.setattr(settings, "ENV", "selfhost")
    monkeypatch.setattr(settings, "BLOB_STORE", BlobStoreKind.S3)
    monkeypatch.setattr(settings, "S3_ENDPOINT_URL", ENDPOINT)
    monkeypatch.setattr(settings, "S3_BUCKET", BUCKET)
    monkeypatch.setattr(settings, "S3_ACCESS_KEY_ID", "key-id")
    monkeypatch.setattr(settings, "S3_SECRET_ACCESS_KEY", "secret")
    monkeypatch.setattr(settings, "S3_REGION", "auto")
    s3_blob_store.cache_clear()
    yield
    s3_blob_store.cache_clear()


async def _put(store: S3BlobStore, owner: str, public_id: str, kind: BlobKind) -> str:
    return await store.put(
        owner, public_id, b"bytes", resource_type="image", kind=kind, content_type="image/png"
    )


def _fields(error: AppError) -> tuple[str, str, str, int, str]:
    return (error.message, error.why, error.fix, error.status_code, error.code)


def _put_refusal(code: str) -> str:
    """Render the ClientError the probe's write gets back for an S3 error code."""
    return str(s3_client_error(code, "PutObject"))


class TestStore:
    async def test_put_stores_a_private_object_and_returns_the_blob_route_url(
        self, store: S3BlobStore, bucket: FakeS3Client
    ) -> None:
        url = await _put(store, "u1", "chat/../pic.png", BlobKind.CHAT_UPLOAD)

        assert url == "/api/v1/blobs/u1/chat_.._pic.png"
        stored = bucket.objects["u1/chat_.._pic.png"]
        assert stored.body == b"bytes"
        assert stored.content_type == "image/png"
        assert stored.metadata == {"kind": "chat_upload"}

    async def test_read_returns_what_put_stored(self, store: S3BlobStore) -> None:
        url = await _put(store, "u1", "pic", BlobKind.GENERATED_IMAGE)

        assert await store.read("u1", "pic", url) == b"bytes"

    async def test_open_resolves_type_and_kind(self, store: S3BlobStore) -> None:
        await _put(store, "u1", "pic", BlobKind.AVATAR)

        blob = await store.open("u1", "pic")

        assert blob is not None
        assert (blob.content, blob.content_type, blob.kind) == (
            b"bytes",
            "image/png",
            BlobKind.AVATAR,
        )

    async def test_a_missing_object_reads_as_not_found(self, store: S3BlobStore) -> None:
        assert await store.open("u1", "nope") is None
        with pytest.raises(FileNotFoundError) as raised:
            await store.read("u1", "nope", "/api/v1/blobs/u1/nope")

        assert str(raised.value) == "no S3 blob 'nope' for owner u1"

    async def test_an_unsafe_key_never_reaches_the_bucket(
        self, store: S3BlobStore, bucket: FakeS3Client
    ) -> None:
        bucket.refuse_with = "AccessDenied"

        assert await store.open("u1", "../u2_pic") is None
        assert await store.open("u1", ".hidden") is None

    async def test_an_unsafe_owner_is_refused(self, store: S3BlobStore) -> None:
        with pytest.raises(ValueError, match="unsafe blob owner id"):
            await _put(store, "../u2", "pic", BlobKind.CHAT_UPLOAD)

    async def test_a_read_the_bucket_refuses_is_raised_not_a_404(
        self, store: S3BlobStore, bucket: FakeS3Client
    ) -> None:
        await _put(store, "u1", "pic", BlobKind.CHAT_UPLOAD)
        bucket.refuse_with = "AccessDenied"

        with pytest.raises(Exception, match="AccessDenied"):
            await store.open("u1", "pic")

    async def test_delete_removes_the_object(
        self, store: S3BlobStore, bucket: FakeS3Client
    ) -> None:
        await _put(store, "u1", "pic", BlobKind.CHAT_UPLOAD)

        await store.delete("u1", "pic")

        assert bucket.objects == {}

    async def test_a_failed_delete_is_logged_never_raised(
        self, store: S3BlobStore, bucket: FakeS3Client
    ) -> None:
        bucket.refuse_with = "AccessDenied"

        async with captured_wide_event() as event:
            await store.delete("u1", "pic")

        [error] = event["errors"]
        assert (
            error["msg"],
            error["owner_id"],
            error["key"],
            error["error"],
            error["error_type"],
        ) == (
            "[blobs] s3 delete failed",
            "u1",
            "u1/pic",
            str(s3_client_error("AccessDenied", "DeleteObject")),
            "ClientError",
        )


class TestBootProbe:
    async def test_a_writable_bucket_passes_and_keeps_no_probe_object(
        self, store: S3BlobStore, bucket: FakeS3Client
    ) -> None:
        await store.verify_bucket()

        assert bucket.calls == [
            (
                "PutObject",
                {
                    "Bucket": BUCKET,
                    "Key": S3_WRITE_PROBE_KEY,
                    "Body": b"",
                    "ContentType": "application/octet-stream",
                    "Metadata": {},
                },
            ),
            ("DeleteObject", {"Bucket": BUCKET, "Key": S3_WRITE_PROBE_KEY}),
        ]
        assert S3_WRITE_PROBE_KEY not in bucket.objects

    async def test_a_missing_bucket_names_the_bucket(self, bucket: FakeS3Client) -> None:
        with pytest.raises(AppError) as raised:
            await S3BlobStore(bucket, "no-such-bucket", ENDPOINT).verify_bucket()

        assert _fields(raised.value) == (
            "File uploads are not set up: the S3 bucket 'no-such-bucket' does not exist "
            f"at {ENDPOINT}.",
            _put_refusal("NoSuchBucket"),
            "Create the bucket, or set S3_BUCKET to the name of one that exists.",
            503,
            "s3_bucket_missing",
        )

    @pytest.mark.parametrize(
        "code", ["InvalidAccessKeyId", "SignatureDoesNotMatch", "AccessDenied", "403"]
    )
    async def test_rejected_credentials_name_the_credential_settings(
        self, store: S3BlobStore, bucket: FakeS3Client, code: str
    ) -> None:
        bucket.refuse_with = code

        with pytest.raises(AppError) as raised:
            await store.verify_bucket()

        assert _fields(raised.value) == (
            "File uploads are not set up: the S3 credentials cannot write to the bucket "
            f"'{BUCKET}'.",
            _put_refusal(code),
            "Check S3_ACCESS_KEY_ID and S3_SECRET_ACCESS_KEY, and that the key may write and "
            "delete objects.",
            503,
            "s3_credentials_rejected",
        )

    async def test_any_other_refusal_names_its_code(
        self, store: S3BlobStore, bucket: FakeS3Client
    ) -> None:
        bucket.refuse_with = "PermanentRedirect"

        with pytest.raises(AppError) as raised:
            await store.verify_bucket()

        assert _fields(raised.value) == (
            f"File uploads are not set up: the S3 bucket '{BUCKET}' refused a test write "
            "(PermanentRedirect).",
            _put_refusal("PermanentRedirect"),
            "Check S3_ENDPOINT_URL, S3_REGION and S3_ADDRESSING_STYLE match the bucket service.",
            503,
            "s3_write_failed",
        )

    async def test_an_unreachable_endpoint_names_the_endpoint(self, bucket: FakeS3Client) -> None:
        def unreachable(**_kwargs: object) -> object:
            raise EndpointConnectionError(endpoint_url=ENDPOINT)

        bucket.put_object = unreachable  # type: ignore[method-assign]  # why: simulate the network failing under the real store

        with pytest.raises(AppError) as raised:
            await S3BlobStore(bucket, BUCKET, ENDPOINT).verify_bucket()

        assert _fields(raised.value) == (
            f"File uploads are not set up: the S3 endpoint {ENDPOINT} is unreachable.",
            str(EndpointConnectionError(endpoint_url=ENDPOINT)),
            "Set S3_ENDPOINT_URL to the bucket service's S3 API URL, reachable from the API.",
            503,
            "s3_endpoint_unreachable",
        )

    async def test_boot_runs_the_probe_under_blob_store_s3(
        self, s3_deployment: None, bucket: FakeS3Client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bucket.refuse_with = "NoSuchBucket"
        monkeypatch.setattr(
            "app.services.blob_store.s3_blob_store",
            lambda: S3BlobStore(bucket, BUCKET, ENDPOINT),
        )

        with pytest.raises(AppError) as raised:
            await ensure_blob_store_ready()

        assert raised.value.code == "s3_bucket_missing"


class TestSelection:
    def test_blob_store_s3_builds_a_client_for_the_configured_bucket(
        self, s3_deployment: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "S3_ADDRESSING_STYLE", S3AddressingStyle.PATH)

        store = blob_store()

        assert isinstance(store, S3BlobStore)
        assert (store.bucket, store.endpoint_url) == (BUCKET, ENDPOINT)
        meta = store.client.meta  # type: ignore[attr-defined]  # why: boto3's generated client, outside the narrow protocol
        config = meta.config
        assert (meta.endpoint_url, meta.region_name) == (ENDPOINT, "auto")
        assert (
            config.signature_version,
            config.s3,
            config.connect_timeout,
            config.read_timeout,
            config.retries,
        ) == (
            "s3v4",
            {"addressing_style": "path"},
            S3_TIMEOUT_SECONDS,
            S3_TIMEOUT_SECONDS,
            # botocore counts the first try too: max_attempts retries is one more attempt
            {"total_max_attempts": S3_MAX_ATTEMPTS + 1, "mode": "legacy"},
        )

    @pytest.mark.parametrize(
        "missing", ["S3_ENDPOINT_URL", "S3_BUCKET", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY"]
    )
    def test_a_missing_setting_refuses_with_the_settings_to_set(
        self, s3_deployment: None, monkeypatch: pytest.MonkeyPatch, missing: str
    ) -> None:
        monkeypatch.setattr(settings, missing, None)

        with pytest.raises(AppError) as raised:
            blob_store()

        assert _fields(raised.value) == (
            "File uploads are not set up: BLOB_STORE=s3 is missing its bucket settings.",
            "",
            "Set S3_ENDPOINT_URL, S3_BUCKET, S3_ACCESS_KEY_ID and S3_SECRET_ACCESS_KEY.",
            503,
            "s3_not_configured",
        )

    async def test_the_blob_route_serves_by_kind_from_the_bucket(
        self, s3_deployment: None, store: S3BlobStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("app.services.blob_store.s3_blob_store", lambda: store)
        await _put(store, "u1", "upload", BlobKind.CHAT_UPLOAD)
        await _put(store, "u1", "avatar", BlobKind.AVATAR)

        assert (await open_readable_blob("u1", "u1", "upload")).content == b"bytes"
        assert (await open_readable_blob("u2", "u1", "avatar")).kind is BlobKind.AVATAR
        with pytest.raises(AppError) as raised:
            await open_readable_blob("u2", "u1", "upload")
        assert raised.value.status_code == 404


def test_a_client_error_code_round_trips_through_the_fake() -> None:
    assert s3_client_error("NoSuchKey", "GetObject").response["Error"]["Code"] == "NoSuchKey"
