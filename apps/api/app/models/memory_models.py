"""Public API schemas for the GAIA memory system.

This is the contract the frontend mirrors: memory entries with supersession
lineage, the folder tree, the entity graph, the episodic journal, core
documents, and the settings-UI overview.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from app.constants.memory import (
    DEFAULT_MEMORY_IMPORTANCE,
    MemoryDocType,
    MemoryEntityType,
    MemoryKind,
    MemoryRelationType,
    MemorySourceType,
)


class MemoryEntityRef(BaseModel):
    """A named entity linked to a memory."""

    id: str = Field(description="Entity ID")
    name: str = Field(description="Canonical entity name")
    entity_type: MemoryEntityType = Field(description="What kind of thing the entity is")


class MemoryEntry(BaseModel):
    """A single memory: an atomic fact or experience with lineage and provenance."""

    id: str | None = Field(default=None, description="Unique identifier for the memory")
    content: str = Field(description="The memory content")
    kind: MemoryKind = Field(default=MemoryKind.FACT, description="Fact or experience")
    category_path: str = Field(
        default="", description="Folder this memory files under, e.g. 'work/gaia'"
    )
    importance: float = Field(
        default=DEFAULT_MEMORY_IMPORTANCE, description="Long-term importance score (0-1)"
    )
    occurred_start: datetime | None = Field(
        default=None, description="When the described event started, if temporal"
    )
    occurred_end: datetime | None = Field(
        default=None, description="When the described event ended, if temporal"
    )
    mentioned_at: datetime | None = Field(default=None, description="When the user mentioned this")
    version: int = Field(default=1, description="Version number within the supersession chain")
    is_latest: bool = Field(default=True, description="Whether this is the chain head")
    parent_id: str | None = Field(
        default=None, description="Memory this version supersedes or extends"
    )
    root_id: str | None = Field(default=None, description="First memory in the chain")
    relation_type: MemoryRelationType | None = Field(
        default=None, description="How this version relates to its parent"
    )
    is_forgotten: bool = Field(default=False, description="Soft-deleted by the user or agent")
    forget_after: datetime | None = Field(
        default=None, description="When this memory expires from recall, if temporal"
    )
    forget_reason: str | None = Field(
        default=None, description="Why this memory was forgotten, when it was"
    )
    source_type: MemorySourceType = Field(
        default=MemorySourceType.CONVERSATION, description="Where this memory was ingested from"
    )
    source_id: str | None = Field(
        default=None, description="Source identifier (conversation ID, email ID, ...)"
    )
    created_at: datetime | None = Field(default=None, description="When the memory was created")
    updated_at: datetime | None = Field(
        default=None, description="When the memory was last updated"
    )
    relevance_score: float | None = Field(
        default=None, description="Relevance score when returned from search"
    )
    entities: list[MemoryEntityRef] = Field(
        default_factory=list, description="Entities this memory mentions"
    )


class MemorySearchResult(BaseModel):
    """Results from a memory search."""

    memories: list[MemoryEntry] = Field(
        default_factory=list, description="List of matching memories"
    )
    total_count: int = Field(default=0, description="Total number of matching memories")


class MemoryListResponse(BaseModel):
    """One page of a user's memories."""

    memories: list[MemoryEntry] = Field(default_factory=list, description="Memories on this page")
    page: int = Field(description="Current page number (1-based)")
    page_size: int = Field(description="Number of memories per page")
    total_count: int = Field(description="Total memories matching the query")


class MemoryTreeNode(BaseModel):
    """One folder in the memory directory tree."""

    name: str = Field(description="Folder name (last path segment)")
    path: str = Field(description="Full category path, e.g. 'work/gaia'")
    count: int = Field(description="Number of memories in this folder and its children")
    children: list["MemoryTreeNode"] = Field(default_factory=list, description="Sub-folders")
    memories: list[MemoryEntry] | None = Field(
        default=None, description="Memories directly in this folder, when expanded"
    )


class MemoryTreeResponse(BaseModel):
    """The user's full memory folder tree."""

    tree: list[MemoryTreeNode] = Field(default_factory=list, description="Top-level folders")
    total_count: int = Field(description="Total memories across the tree")


class MemoryGraphNode(BaseModel):
    """An entity node in the memory graph."""

    id: str = Field(description="Entity ID")
    name: str = Field(description="Canonical entity name")
    entity_type: MemoryEntityType = Field(description="What kind of thing the entity is")
    memory_count: int = Field(description="Number of memories linked to this entity")


class MemoryGraphEdge(BaseModel):
    """A labeled entity-to-entity relationship in the memory graph."""

    id: str = Field(description="Edge ID")
    source_entity_id: str = Field(description="Source entity ID")
    target_entity_id: str = Field(description="Target entity ID")
    relationship: str = Field(description="Verb phrase, e.g. 'works at'")
    memory_id: str | None = Field(
        default=None, description="Memory this edge was extracted from (provenance)"
    )


class MemoryGraphResponse(BaseModel):
    """The user's entity graph with the memories that back it."""

    nodes: list[MemoryGraphNode] = Field(default_factory=list, description="Entity nodes")
    edges: list[MemoryGraphEdge] = Field(default_factory=list, description="Relationship edges")
    memories: list[MemoryEntry] = Field(
        default_factory=list, description="Memories linked to the returned entities"
    )


class MemoryEpisodeEntry(BaseModel):
    """One timestamped line in a day's journal."""

    time: str = Field(description="Time of day the entry was written (HH:MM)")
    text: str = Field(description="Terse past-tense journal line")
    source: str = Field(description="Where the entry came from (conversation, email, ...)")


class MemoryEpisode(BaseModel):
    """One day of the episodic journal."""

    date: str = Field(description="ISO date (YYYY-MM-DD)")
    entries: list[MemoryEpisodeEntry] = Field(
        default_factory=list, description="Journal lines appended through the day"
    )
    summary: str | None = Field(
        default=None, description="Day summary, written lazily on day rollover"
    )


class MemoryEpisodesResponse(BaseModel):
    """Episodic journal pages for a date range."""

    episodes: list[MemoryEpisode] = Field(default_factory=list, description="One per day")


class MemoryDocument(BaseModel):
    """A core markdown document GAIA maintains about the user."""

    doc_type: MemoryDocType = Field(description="Which core document this is")
    content: str = Field(description="Markdown content")
    version: int = Field(description="Current version number")
    updated_at: datetime = Field(description="When the document was last updated")


class MemoryDocumentsResponse(BaseModel):
    """All of a user's core memory documents."""

    documents: list[MemoryDocument] = Field(default_factory=list, description="Core documents")


class MemoryDocumentPreview(BaseModel):
    """Truncated core-document preview for the overview screen."""

    doc_type: MemoryDocType = Field(description="Which core document this is")
    preview: str = Field(description="First lines of the document")
    updated_at: datetime = Field(description="When the document was last updated")


class MemoryOverviewResponse(BaseModel):
    """Headline numbers and document previews for the memory settings UI."""

    total_memories: int = Field(description="Total non-forgotten memories")
    total_entities: int = Field(description="Total entities in the graph")
    folder_count: int = Field(description="Number of folders in the tree")
    episode_count: int = Field(description="Number of journal days")
    documents: list[MemoryDocumentPreview] = Field(
        default_factory=list, description="Core document previews"
    )


class CreateMemoryRequest(BaseModel):
    """Request model for creating a memory."""

    content: str = Field(description="The memory content to store")
    category_path: str | None = Field(
        default=None, description="Folder to file under; auto-categorized when omitted"
    )


class UpdateMemoryRequest(BaseModel):
    """Request model for editing a memory (chains a new version)."""

    content: str = Field(description="The corrected memory content")


class UpdateDocumentRequest(BaseModel):
    """Request model for editing a core memory document."""

    content: str = Field(description="The full new markdown content")


class CreateMemoryResponse(BaseModel):
    """Response model for memory creation."""

    success: bool
    memory_id: str | None = None
    message: str


class DeleteMemoryResponse(BaseModel):
    """Response model for memory deletion."""

    success: bool
    message: str
