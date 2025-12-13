"""Memory-related data models."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class CreateMemoryRequest(BaseModel):
    """Request model for creating a memory."""

    content: str = Field(description="The memory content to store")
    metadata: Optional[dict] = Field(default=None, description="Optional metadata")


class CreateMemoryResponse(BaseModel):
    """Response model for memory creation."""

    success: bool
    memory_id: Optional[str] = None
    message: str


class DeleteMemoryResponse(BaseModel):
    """Response model for memory deletion."""

    success: bool
    message: str


class Message(BaseModel):
    """Represents a single message in a conversation."""

    role: str = Field(
        description="Role of the message sender (user, assistant, system)"
    )
    content: str = Field(description="Content of the message")
    timestamp: Optional[datetime] = Field(
        default=None, description="When the message was created"
    )


class MemoryEntry(BaseModel):
    """Represents a single memory entry."""

    id: Optional[str] = Field(
        default=None, description="Unique identifier for the memory"
    )
    content: str = Field(description="The memory content")
    user_id: Optional[str] = Field(
        default="", description="User ID associated with this memory"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata"
    )
    categories: Optional[List[str]] = Field(
        default_factory=list, description="Categories this memory belongs to"
    )
    created_at: Optional[datetime] = Field(
        default=None, description="When the memory was created"
    )
    updated_at: Optional[datetime] = Field(
        default=None, description="When the memory was last updated"
    )
    expiration_date: Optional[datetime] = Field(
        default=None, description="When this memory expires"
    )
    # Mem0 API specific fields
    immutable: Optional[bool] = Field(
        default=False, description="Whether this memory is immutable"
    )
    organization: Optional[str] = Field(
        default=None, description="Organization associated with this memory"
    )
    owner: Optional[str] = Field(default=None, description="Owner of this memory")
    # Search-specific fields
    relevance_score: Optional[float] = Field(
        default=None, description="Relevance score from search"
    )


class MemoryRelation(BaseModel):
    """Represents a relationship between entities in memory."""

    source: str = Field(description="Source entity of the relationship")
    source_type: str = Field(
        description="Type of the source entity (user, person, location, etc.)"
    )
    relationship: str = Field(description="Type of relationship")
    target: str = Field(description="Target entity of the relationship")
    target_type: str = Field(description="Type of the target entity")


class MemorySearchResult(BaseModel):
    """Results from memory search operation."""

    memories: List[MemoryEntry] = Field(
        default_factory=list, description="List of matching memories"
    )
    relations: List[MemoryRelation] = Field(
        default_factory=list, description="List of relationships between entities"
    )
    total_count: int = Field(default=0, description="Total number of matching memories")


class MemoryConfiguration(BaseModel):
    """Configuration for memory operations."""

    max_memories_per_search: int = Field(
        default=5, description="Maximum memories to retrieve per search"
    )
    auto_store_conversations: bool = Field(
        default=True, description="Automatically store conversations"
    )
    memory_ttl_days: Optional[int] = Field(
        default=None, description="Days to retain memories (None = forever)"
    )
    enable_semantic_search: bool = Field(
        default=True, description="Use semantic search for memory retrieval"
    )


class ConversationMemory(BaseModel):
    """Represents a conversation to be stored in memory."""

    user_message: str = Field(description="The user's message")
    assistant_response: str = Field(description="The assistant's response")
    conversation_id: str = Field(description="Conversation thread ID")
    user_id: str = Field(description="User ID")
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Additional context"
    )
