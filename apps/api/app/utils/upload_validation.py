"""
Upload validation — size / filename / MIME / magic-byte checks.

Prevents oversize uploads from exhausting memory, blocks double-extension
polyglots (e.g. `shell.php.png`), and rejects files whose client-claimed
Content-Type does not match the actual bytes.
"""

from __future__ import annotations

from fastapi import HTTPException, UploadFile, status

MAX_UPLOAD_BYTES = 10 * 1024 * 1024

# Allowed (content-type, magic-bytes-prefix) pairs.
# Each entry: (content_type, cloudinary resource_type, list of byte signatures)
_ALLOWED_TYPES: dict[str, tuple[str, tuple[bytes, ...]]] = {
    "image/png": ("image", (b"\x89PNG\r\n\x1a\n",)),
    "image/jpeg": ("image", (b"\xff\xd8\xff",)),
    "image/gif": ("image", (b"GIF87a", b"GIF89a")),
    "image/webp": ("image", (b"RIFF",)),  # RIFF....WEBP — we only check prefix
    "image/bmp": ("image", (b"BM",)),
    "image/svg+xml": ("image", (b"<?xml", b"<svg", b"<SVG")),
    "application/pdf": ("raw", (b"%PDF-",)),
    "text/plain": ("raw", ()),
    "text/markdown": ("raw", ()),
    "text/csv": ("raw", ()),
    "application/json": ("raw", ()),
    "application/msword": ("raw", (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",)),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (
        "raw",
        (b"PK\x03\x04",),
    ),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": (
        "raw",
        (b"PK\x03\x04",),
    ),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": (
        "raw",
        (b"PK\x03\x04",),
    ),
}

# Extensions that must never appear in an uploaded filename, even as a
# secondary extension. Blocks the `.php.png` polyglot trick.
_DANGEROUS_EXTENSIONS = frozenset(
    {
        "php",
        "php3",
        "php4",
        "php5",
        "phtml",
        "exe",
        "dll",
        "so",
        "dylib",
        "bat",
        "cmd",
        "sh",
        "ps1",
        "jsp",
        "asp",
        "aspx",
        "cgi",
        "pl",
        "py",
        "rb",
        "jar",
        "war",
        "ear",
        "msi",
        "app",
        "deb",
        "rpm",
        "html",
        "htm",
        "xhtml",
        "svg",  # HTML-ish served from CDN = stored XSS
        "js",
        "mjs",
    }
)


def _filename_extensions(filename: str) -> list[str]:
    """Return every extension in the filename, lowercased (foo.tar.gz -> ['tar','gz'])."""
    base = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    parts = base.split(".")
    return [p.lower() for p in parts[1:]] if len(parts) > 1 else []


def validate_filename(filename: str | None) -> None:
    """Raise 400 if filename is missing, contains path separators, or has a dangerous extension anywhere."""
    if not filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename is required.",
        )
    if "/" in filename or "\\" in filename or "\x00" in filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename must not contain path separators.",
        )
    exts = _filename_extensions(filename)
    for ext in exts:
        if ext in _DANGEROUS_EXTENSIONS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Filename contains a disallowed extension (.{ext}).",
            )


def validate_content_type(
    content_type: str | None,
) -> tuple[str, str, tuple[bytes, ...]]:
    """
    Ensure the client-supplied content-type is in the allowlist. Returns a tuple of
    (normalized_content_type, cloudinary_resource_type, magic_signatures).
    """
    if not content_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Content type is required.",
        )
    normalized = content_type.split(";")[0].strip().lower()
    if normalized not in _ALLOWED_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported content type: {normalized}.",
        )
    resource_type, signatures = _ALLOWED_TYPES[normalized]
    return normalized, resource_type, signatures


def enforce_size_preflight(content_length: int | None) -> None:
    """Reject oversize uploads before reading any bytes, based on Content-Length header."""
    if content_length is not None and content_length > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File size exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.",
        )


async def read_bounded(file: UploadFile) -> bytes:
    """
    Read the upload body into memory with a hard cap. Reads one byte past the
    limit so we can definitively detect oversize bodies even when Content-Length
    was absent or lied.
    """
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File size exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.",
        )
    return content


def verify_magic_bytes(content: bytes, signatures: tuple[bytes, ...]) -> None:
    """Confirm the payload actually starts with one of the allowed signatures."""
    if not signatures:
        return  # text/json/csv etc. have no reliable magic; skip
    if not any(content.startswith(sig) for sig in signatures):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File content does not match the claimed content type.",
        )


async def validate_upload(file: UploadFile, content_length: int | None) -> tuple[bytes, str, str]:
    """
    Full upload validation pipeline. Raises HTTPException on any failure.

    Returns (content_bytes, normalized_content_type, cloudinary_resource_type).
    """
    enforce_size_preflight(content_length)
    validate_filename(file.filename)
    normalized, resource_type, signatures = validate_content_type(file.content_type)
    content = await read_bounded(file)
    verify_magic_bytes(content, signatures)
    return content, normalized, resource_type
