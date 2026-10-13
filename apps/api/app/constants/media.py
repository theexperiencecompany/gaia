"""Inline-media (image) constants.

Inline media is an image the model receives as pixels rather than prose. It lives
in history as a LangChain v1 data content block
({"type": "image", "base64": ..., "mime_type": ...}) inside a ToolMessage, and
is fitted to the active model lane at request time (see app/agents/llm/vision/).

Three budgets bound it, at three boundaries: per file (MAX_IMAGE_FILE_BYTES),
per block (TARGET_INLINE_IMAGE_BYTES — what one image costs in a provider
request and in every Postgres checkpoint that persists it), and per request
(MAX_INLINE_MEDIA_BLOCKS).
"""

PNG_MIME = "image/png"
JPEG_MIME = "image/jpeg"
WEBP_MIME = "image/webp"
GIF_MIME = "image/gif"

# Extensions the `read` tool and the device bridge treat as inline images.
IMAGE_MIME_BY_EXTENSION: dict[str, str] = {
    ".png": PNG_MIME,
    ".jpg": JPEG_MIME,
    ".jpeg": JPEG_MIME,
    ".webp": WEBP_MIME,
    ".gif": GIF_MIME,
}

# Filename suffix for the MIMEs `ImageCodec` can emit. A producer that persists an
# image names the file with this, so a later `read` of that path resolves the same
# MIME back through IMAGE_MIME_BY_EXTENSION above.
IMAGE_EXTENSION_BY_MIME: dict[str, str] = {
    PNG_MIME: ".png",
    JPEG_MIME: ".jpg",
    WEBP_MIME: ".webp",
}

# Pillow's sniffed format → MIME; decoded bytes are authoritative since a file
# extension or MCP `mimeType` can lie. Formats Pillow decodes but doesn't list
# (BMP, TIFF, HEIC) transcode to JPEG.
MIME_BY_PILLOW_FORMAT: dict[str, str] = {
    "PNG": PNG_MIME,
    "JPEG": JPEG_MIME,
    "WEBP": WEBP_MIME,
    "GIF": GIF_MIME,
}

# MIME types every lane we route media to actually accepts. Gemini rejects
# `image/gif` outright with a 400, so a GIF reaching the provider untouched would
# kill the whole turn. Anything outside this set is transcoded to JPEG first.
PROVIDER_SAFE_IMAGE_MIMES = frozenset({PNG_MIME, JPEG_MIME, WEBP_MIME})
TRANSCODE_MIME = JPEG_MIME
TRANSCODE_FORMAT = "JPEG"
TRANSCODE_QUALITY = 80
# Step quality down when the primary still busts TARGET_INLINE_IMAGE_BYTES: a dense
# 1568px image can exceed the byte budget even after downscaling, and that payload
# is persisted in every checkpoint. The last step is the floor — best effort.
TRANSCODE_QUALITY_STEPS = (TRANSCODE_QUALITY, 60, 40)

# Refuse image data larger than this outright, before decoding it.
MAX_IMAGE_FILE_BYTES = 10 * 1024 * 1024
# Refuse images above this pixel area before re-encoding — bounds decode memory, not
# just output size: a 315 KB 9999x9999 PNG decodes to ~300 MB. Caps one decode near
# 175 MB (a 6K screen is ~20 MP; a 100 MP source would take ~700 MB).
MAX_IMAGE_PIXELS = 25_000_000
# Re-encode images above this size so the base64 payload stays small in the
# provider request and in the Postgres checkpointer, which persists the full
# ToolMessage on every checkpoint.
TARGET_INLINE_IMAGE_BYTES = 1 * 1024 * 1024
# Longest edge after downscaling. Above this, providers downsample anyway, so the
# extra pixels only cost payload. Doubles as a decompression-bomb bound: a
# small-bytes / huge-pixels image is capped here too.
DOWNSCALE_LONGEST_EDGE = 1568

# Cap on images per model request. Media is never compacted away, so without this a
# thread with twenty screenshots would re-send ~28 MB of base64 every turn. Most
# recent blocks win; older ones are replaced by MEDIA_EVICTED_NOTICE.
MAX_INLINE_MEDIA_BLOCKS = 5
# Ceiling on the images one MCP tool result may contribute, applied while decoding
# so a hostile server response can't be materialized before the budget above sees it.
MAX_MEDIA_BLOCKS_PER_TOOL_RESULT = 5

# What one media block costs a char-based context estimate: roughly what a provider
# bills for a downscaled image, rather than its base64 length — 1 MB of base64 would
# read as ~350k tokens and trigger compaction on the first screenshot.
MEDIA_BLOCK_TOKEN_ESTIMATE = 1000

MEDIA_OMITTED_NOTICE = (
    "[Inline media omitted: the current model cannot view media directly. "
    "Tell the user what you were unable to view if it matters for their request.]"
)
MEDIA_EVICTED_NOTICE = (
    "[Inline media omitted: only the most recent images are kept in context. "
    "To look at it now, `read` it back from the path named in this result, or "
    "re-run the tool that produced it if it named none.]"
)

# Key under which a ToolMessage carries per-block media descriptions, in block order.
# Written at tool-execution time, read at the request boundary by MediaAdapter — a
# pre-model hook can't cache it since its output is discarded after one model call.
MEDIA_DESCRIPTIONS_KEY = "media_descriptions"

MEDIA_DESCRIBE_FAILED = "[Image could not be described: the vision model was unavailable.]"

TOOL_MEDIA_DESCRIBE_PROMPT = (
    "An image was returned by the '{tool_name}' tool. Context from the tool result:\n"
    "{context}\n\n"
    "Describe the image in detail: layout, subjects, colors, and any text or UI "
    "elements (transcribe important text exactly). The description substitutes "
    "for the image for a model that cannot view it."
)
