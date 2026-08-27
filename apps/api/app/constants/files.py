"""Constants for user-uploaded file operations."""

from app.constants.chroma import CHROMA_COLLECTION_SUFFIX

# ChromaDB collection holding uploaded-file/document summaries for semantic search.
# Suffixed like every other GAIA collection so concurrent CI lanes sharing one
# Chroma server do not read or delete each other's documents.
CHROMA_DOCUMENTS_COLLECTION = "documents" + CHROMA_COLLECTION_SUFFIX

# Timeout for downloading a Cloudinary-hosted upload when seeding it into a
# freshly created conversation's sandbox.
FILE_SEED_DOWNLOAD_TIMEOUT_SECONDS = 30.0

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

# Local (offline, native-code) document extraction runs synchronously on a
# thread. This bounds how long a request waits (e.g. a decompression-bomb
# DOCX/XLSX). It does not stop the worker thread: the native call has no
# cooperative cancellation and keeps its executor slot until it finishes.
# (Decompression-bomb *memory* is bounded by MAX_UPLOAD_BYTES at the upload
# endpoint, not by this timeout.)
LOCAL_EXTRACTION_TIMEOUT_SECONDS = 60.0

# LlamaParse is a hosted cloud API used only as an OCR fallback for scanned
# or image-based PDFs; bound the call so a stalled cloud job can't hang the
# request.
OCR_EXTRACTION_TIMEOUT_SECONDS = 120.0

# Markdown chunks are capped so one summary fits a single LLM prompt.
MAX_CHUNK_CHARS = 3000

# Summarization/indexing budget for one document. Chunks beyond this are not
# indexed for search (the full file stays available in the workspace); a note
# entry records the truncation. Keeps LLM cost and the Mongo file document
# (page_wise_summary embeds every indexed chunk's content) bounded.
MAX_INDEXED_CHUNKS = 200

# Concurrent LLM calls per document while summarizing chunks.
SUMMARY_LLM_MAX_CONCURRENCY = 8
