"""User-uploaded file operations.

FileService.upload validates, stores the Cloudinary blob + AI summary in parallel,
mirrors into the session workspace with a <file>.summary.md sidecar, then persists
metadata (Mongo) and the vector index (Chroma). FileService.attach_uploads does the
same mirroring for any upload that reached the server without a conversation
(new-chat files, or a client that omitted the id), stamping conversation_id and
the workspace path. FileService.get_uploads batches the stored metadata into agent
context; search_uploaded_files vector-searches scoped to the conversation's files.

FileService is the entry point; submodules hold the mechanics: store (Cloudinary
+ Mongo + Chroma), sandbox (JuiceFS workspace projection), summaries (AI summary
shape + render).
"""

from app.services.files.service import FileService

__all__ = ["FileService"]
