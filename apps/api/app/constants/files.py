"""Constants for user-uploaded file operations."""

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType

from app.constants.chroma import CHROMA_COLLECTION_SUFFIX

# ChromaDB collection holding uploaded-file/document summaries for semantic search.
# Suffixed like every other GAIA collection so concurrent CI lanes sharing one
# Chroma server do not read or delete each other's documents.
CHROMA_DOCUMENTS_COLLECTION = "documents" + CHROMA_COLLECTION_SUFFIX

# Timeout for downloading a Cloudinary-hosted blob (e.g. seeding an upload into
# a freshly created conversation's sandbox).
BLOB_DOWNLOAD_TIMEOUT_SECONDS = 30.0

# MIME types of upload-allowed office documents, routed to local extraction.
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
CSV_MIME = "text/csv"
PDF_MIME = "application/pdf"
# Legacy binary Word (OLE2) — extracted locally by anydoc like DOCX.
DOC_MIME = "application/msword"
# Additional formats anydoc converts to Markdown (verified against real files).
# text/rtf matches the backend upload allowlist (upload_validation.py).
RTF_MIME = "text/rtf"
EPUB_MIME = "application/epub+zip"
ODT_MIME = "application/vnd.oasis.opendocument.text"
ODS_MIME = "application/vnd.oasis.opendocument.spreadsheet"
ODP_MIME = "application/vnd.oasis.opendocument.presentation"

# Bounds how long a request waits for local document extraction (e.g. a
# decompression-bomb DOCX/XLSX); does not stop the worker thread (no
# cooperative cancellation). Bomb memory is bounded by MAX_UPLOAD_BYTES.
LOCAL_EXTRACTION_TIMEOUT_SECONDS = 60.0

# LlamaParse is a hosted cloud API used only as an OCR fallback for scanned
# or image-based PDFs; bound the call so a stalled cloud job can't hang the
# request.
OCR_EXTRACTION_TIMEOUT_SECONDS = 120.0

# Markdown chunks are capped so one summary fits a single LLM prompt.
MAX_CHUNK_CHARS = 3000

# Chunks beyond this are not indexed for search (the full file stays available
# in the workspace); a note entry records the truncation. Bounds LLM cost and the Mongo file document.
MAX_INDEXED_CHUNKS = 200

# Concurrent LLM calls per document while summarizing chunks.
SUMMARY_LLM_MAX_CONCURRENCY = 8

# Single-purpose file-share grants (Composio fetches the bytes during tool
# execution): lifetime of a minted grant URL and the default per-fetch byte cap.
SHARE_GRANT_TTL_SECONDS = 300
SHARE_GRANT_MAX_TTL_SECONDS = 3600
SHARE_GRANT_MAX_BYTES = 25 * 1024 * 1024

# Summary for an uploaded image when no configured provider can read images.
IMAGE_SUMMARY_NO_VISION_PROVIDER = (
    "Image not described: no configured AI provider on this instance can read images."
)

# Local-volume and S3 blobs are served by the authenticated blob route under this
# path. Stored relative: the self-host web and API share one origin, and a
# relative URL survives a change of domain.
BLOB_ROUTE_URL_PREFIX = "/api/v1/blobs"
# Inside each local blob's directory: its bytes and its metadata.
LOCAL_BLOB_DATA_FILENAME = "data"
LOCAL_BLOB_META_FILENAME = "meta.json"
# Written and deleted at boot to prove the bucket takes writes; owner ids never start with a dot.
S3_WRITE_PROBE_KEY = ".gaia-write-probe"
S3_TIMEOUT_SECONDS = 15
S3_MAX_ATTEMPTS = 3
# Error codes S3-compatible services return; each maps to its own boot failure.
S3_MISSING_OBJECT_CODES = frozenset({"NoSuchKey", "404"})
S3_MISSING_BUCKET_CODES = frozenset({"NoSuchBucket"})
S3_BAD_CREDENTIAL_CODES = frozenset(
    {"InvalidAccessKeyId", "SignatureDoesNotMatch", "AccessDenied", "InvalidToken", "403"}
)


class S3AddressingStyle(StrEnum):
    """How the bucket appears in an S3 request URL; the value is S3_ADDRESSING_STYLE."""

    # https://<bucket>.<endpoint>/<key>: AWS, Cloudflare R2, Backblaze B2, Railway buckets.
    VIRTUAL = "virtual"
    # https://<endpoint>/<bucket>/<key>: MinIO and older Railway buckets.
    PATH = "path"


# Blob responses render only inert content in a browser: a same-origin HTML or
# SVG upload must never run script as the app.
BLOB_ROUTE_RESPONSE_HEADERS = {
    "Content-Security-Policy": "sandbox; default-src 'none'; img-src 'self'; media-src 'self'; style-src 'unsafe-inline'",
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "private, max-age=3600",
}
# Types a browser may show in place; everything else downloads.
BLOB_ROUTE_INLINE_TYPE_PREFIXES = ("image/", "audio/", "video/", "application/pdf", "text/plain")


class BlobKind(StrEnum):
    """What a stored blob is; its kind decides who may read it (BLOB_AUDIENCE)."""

    AVATAR = "avatar"
    CHAT_UPLOAD = "chat_upload"
    GENERATED_IMAGE = "generated_image"
    SUPPORT_ATTACHMENT = "support_attachment"


class BlobAudience(StrEnum):
    """Who may read a blob besides its owner."""

    OWNER = "owner"
    INSTANCE_MEMBERS = "instance_members"


# Who may read each kind of self-hosted blob. Avatars appear beside a member's
# name (members list, marketplace creator); GAIA has no conversation sharing,
# so a conversation's uploads and generated images stay with their owner.
BLOB_AUDIENCE: Mapping[BlobKind, BlobAudience] = MappingProxyType(
    {
        BlobKind.AVATAR: BlobAudience.INSTANCE_MEMBERS,
        BlobKind.CHAT_UPLOAD: BlobAudience.OWNER,
        BlobKind.GENERATED_IMAGE: BlobAudience.OWNER,
        BlobKind.SUPPORT_ATTACHMENT: BlobAudience.OWNER,
    }
)
