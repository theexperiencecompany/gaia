"""Constants for user-uploaded file operations."""

# ChromaDB collection holding uploaded-file/document summaries for semantic search.
CHROMA_DOCUMENTS_COLLECTION = "documents"

# Timeout for downloading a Cloudinary-hosted upload when seeding it into a
# freshly created conversation's sandbox.
FILE_SEED_DOWNLOAD_TIMEOUT_SECONDS = 30.0
