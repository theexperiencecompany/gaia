"""CRUD for core markdown documents (user.md, memory.md, agenda.md, ...)."""

from datetime import UTC, datetime

from sqlalchemy import select

from app.constants.memory import DOCUMENT_HISTORY_LIMIT, MemoryDocType
from app.memory.pg_store._session import memory_session
from app.models.memory_db_models import MemoryDocument


async def get_documents(user_id: str) -> list[MemoryDocument]:
    """All of a user's core documents."""
    async with memory_session() as session:
        result = await session.execute(
            select(MemoryDocument)
            .where(MemoryDocument.user_id == user_id)
            .order_by(MemoryDocument.doc_type)
        )
        return list(result.scalars().all())


async def get_document(user_id: str, doc_type: MemoryDocType) -> MemoryDocument | None:
    """One core document by type."""
    async with memory_session() as session:
        result = await session.execute(
            select(MemoryDocument).where(
                MemoryDocument.user_id == user_id,
                MemoryDocument.doc_type == doc_type.value,
            )
        )
        return result.scalar_one_or_none()


async def upsert_document(user_id: str, doc_type: MemoryDocType, content: str) -> MemoryDocument:
    """Create or rewrite a core document, archiving the previous version.

    Bumps ``version``, pushes the outgoing content onto ``history``
    (newest first, capped at ``DOCUMENT_HISTORY_LIMIT``).
    """
    async with memory_session() as session:
        result = await session.execute(
            select(MemoryDocument).where(
                MemoryDocument.user_id == user_id,
                MemoryDocument.doc_type == doc_type.value,
            )
        )
        document = result.scalar_one_or_none()
        if document is None:
            document = MemoryDocument(user_id=user_id, doc_type=doc_type.value, content=content)
            session.add(document)
        else:
            archived = {
                "version": document.version,
                "content": document.content,
                "updated_at": datetime.now(UTC).isoformat(),
            }
            document.history = [archived, *document.history][:DOCUMENT_HISTORY_LIMIT]
            document.version += 1
            document.content = content
        await session.commit()
        # ``updated_at`` is a SQL-side onupdate default: UPDATEs (unlike
        # INSERTs, which populate it via RETURNING) leave the attribute
        # expired, and the row outlives this session — reload it here.
        await session.refresh(document)
    return document
