"""User-uploaded file operations.

FileService.upload validates, stores the Cloudinary blob + AI summary in parallel,
mirrors into the session workspace with a <file>.summary.md sidecar, then persists
metadata (Mongo) and the vector index (Chroma). FileService.seed_uploads does the
same mirroring for files attached before their chat existed, stamping
conversation_id so search can scope to it. FileService.get_descriptions batches
the inline summaries into agent context; search_uploaded_files vector-searches
scoped to the current conversation's files.

FileService is the entry point; submodules hold the mechanics: store (Cloudinary
+ Mongo + Chroma), sandbox (JuiceFS workspace projection), summaries (AI summary
shape + render).
"""

from app.services.files.service import FileService

__all__ = ["FileService"]
