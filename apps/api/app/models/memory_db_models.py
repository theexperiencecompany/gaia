"""SQLAlchemy models for the GAIA memory engine (canonical Postgres store).

PostgreSQL is the source of truth for memories: fact records with
supersession lineage, full-text search, entities, graph edges, episodic
memory, and core documents. ChromaDB holds only the dense vectors.
"""

from datetime import date, datetime
from typing import Any
import uuid

from sqlalchemy import (
    Boolean,
    Computed,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.constants.memory import DEFAULT_MEMORY_IMPORTANCE, FORGET_REASON_MAX_CHARS
from app.db.postgresql import Base

# Weighted FTS document: content carries weight A, the category folder path
# weight B (slashes become spaces so each folder segment is a lexeme).
_MEMORY_SEARCH_TSV = (
    "setweight(to_tsvector('english', content), 'A') || "
    "setweight(to_tsvector('english', replace(category_path, '/', ' ')), 'B')"
)


class MemoryRecord(Base):
    """An atomic memory: a semantic fact or an experience.

    Never hard-deleted from agent flows. Contradictions create a new row
    linked via ``parent_id``/``root_id`` with ``relation_type='updates'``
    and flip the old row's ``is_latest`` to False. User-initiated deletes
    set ``is_forgotten=True``.
    """

    __tablename__ = "memories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # MemoryKind
    content: Mapped[str] = mapped_column(Text, nullable=False)
    category_path: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    occurred_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    occurred_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    mentioned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_latest: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    root_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    relation_type: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # MemoryRelationType
    is_forgotten: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    forget_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    forget_reason: Mapped[str | None] = mapped_column(
        String(FORGET_REASON_MAX_CHARS), nullable=True
    )
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)  # MemorySourceType
    source_id: Mapped[str | None] = mapped_column(String, nullable=True)
    importance: Mapped[float] = mapped_column(
        Float, default=DEFAULT_MEMORY_IMPORTANCE, nullable=False
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    search_tsv: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed(_MEMORY_SEARCH_TSV, persisted=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_memories_user_latest", "user_id", "is_latest"),
        Index("ix_memories_user_category", "user_id", "category_path"),
        Index("ix_memories_user_created", "user_id", "created_at"),
        Index("ix_memories_search_tsv", "search_tsv", postgresql_using="gin"),
    )


class MemoryEntity(Base):
    """A named entity (person, place, project, ...) mentioned in memories."""

    __tablename__ = "memory_entities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Lowercase-normalized copy of name, maintained at write time, so the
    # uniqueness constraint is case-insensitive ("Nadia" == "nadia").
    name_lower: Mapped[str] = mapped_column(String(255), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("user_id", "name_lower", name="uq_memory_entities_user_name"),
    )


class MemoryEntityLink(Base):
    """Links a memory to an entity it mentions (event-centric graph)."""

    __tablename__ = "memory_entity_links"

    memory_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memories.id", ondelete="CASCADE"), primary_key=True
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memory_entities.id", ondelete="CASCADE"), primary_key=True
    )


class MemoryGraphEdge(Base):
    """LLM-extracted entity-to-entity relationship with provenance."""

    __tablename__ = "memory_graph_edges"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    source_entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memory_entities.id", ondelete="CASCADE"), nullable=False
    )
    target_entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memory_entities.id", ondelete="CASCADE"), nullable=False
    )
    relationship: Mapped[str] = mapped_column(String(255), nullable=False)
    memory_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memories.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "source_entity_id",
            "relationship",
            "target_entity_id",
            name="uq_memory_graph_edges_triple",
        ),
    )


class MemoryEpisode(Base):
    """One row per (user, date): what happened that day, appended at ingestion."""

    __tablename__ = "memory_episodes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    entries: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, nullable=False
    )  # [{time, text, source}]
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (UniqueConstraint("user_id", "date", name="uq_memory_episodes_user_date"),)


class MemoryDocument(Base):
    """Core markdown document GAIA maintains about the user (user.md, agenda.md, ...)."""

    __tablename__ = "memory_documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    doc_type: Mapped[str] = mapped_column(String(20), nullable=False)  # MemoryDocType
    content: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    # Last N previous versions: [{version, content, updated_at}], newest first.
    history: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (UniqueConstraint("user_id", "doc_type", name="uq_memory_documents_user_doc"),)
