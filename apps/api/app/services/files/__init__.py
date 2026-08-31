"""User-uploaded file operations.

The flow, end to end:

  Upload    POST /files/upload → FileService.upload
              validate → Cloudinary blob + AI summary (parallel) → mirror into
              the session workspace (+ ``<file>.summary.md`` sidecar) → persist
              metadata (Mongo) + vector index (Chroma).

  Seed      new chat with files attached before it existed → FileService.seed_uploads
              download each blob → mirror into the now-created session + write its
              sidecar + stamp ``conversation_id`` so search can scope to it.

  Context   each chat turn → FileService.get_descriptions
              one batched Mongo read → the inline summary in the agent's context.

  Search    ``search_uploaded_files`` tool (executor) → vector search scoped to the
              current conversation's files.

``FileService`` is the entry point; the submodules hold the mechanics it orchestrates:
  store      Cloudinary + Mongo + Chroma persistence
  sandbox    JuiceFS workspace projection (upload mirror + summary sidecar)
  summaries  shape + render the AI summary
"""

from app.services.files.service import FileService

__all__ = ["FileService"]
