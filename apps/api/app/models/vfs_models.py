"""
Virtual Filesystem (VFS) Models.

Pydantic models for the MongoDB-backed virtual filesystem.
Supports the folder structure:

/users/{user_id}/
└── global/
    ├── skills/
    │   ├── learned/
    │   └── custom/
    ├── executor/
    │   ├── sessions/{conversation_id}/{agent_name}/
    │   ├── notes/
    │   └── files/
    └── subagents/{agent_name}/
        ├── notes/
        └── files/
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class VFSNodeType(str, Enum):
    """Type of VFS node."""

    FOLDER = "folder"
    FILE = "file"


class VFSNode(BaseModel):
    """
    Represents a file or folder in the virtual filesystem.

    This is the core document stored in MongoDB's vfs_nodes collection.
    """

    model_config = {"arbitrary_types_allowed": True}

    id: Optional[str] = Field(None, description="MongoDB ObjectId as string")
    user_id: str = Field(..., description="Owner user ID")
    path: str = Field(
        ..., description="Full normalized path (e.g., /users/{user_id}/global/...)"
    )
    name: str = Field(..., description="Node name (filename or folder name)")
    node_type: VFSNodeType = Field(..., description="Type: folder or file")
    parent_path: Optional[str] = Field(None, description="Parent folder path")

    # File-specific fields
    content: Optional[str] = Field(
        None, description="Inline content for small files (<1MB)"
    )
    gridfs_id: Optional[str] = Field(
        None, description="GridFS reference for large files (>=1MB)"
    )
    content_type: str = Field(default="text/plain", description="MIME type")
    size_bytes: int = Field(default=0, description="File size in bytes")

    # Extensible metadata
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Extensible metadata (tool_call_id, agent_name, conversation_id, etc.)",
    )

    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    accessed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class VFSNodeCreate(BaseModel):
    """Model for creating a new VFS node."""

    path: str = Field(..., description="Target path for the file/folder")
    content: Optional[str] = Field(None, description="File content (for files)")
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Optional metadata"
    )


class VFSNodeResponse(BaseModel):
    """Response model for VFS node operations."""

    path: str
    name: str
    node_type: VFSNodeType
    size_bytes: int = 0
    content_type: str = "text/plain"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class VFSListResponse(BaseModel):
    """Response model for directory listing."""

    path: str
    items: List[VFSNodeResponse]
    total_count: int


class VFSTreeNode(BaseModel):
    """Node in a directory tree representation."""

    name: str
    path: str
    node_type: VFSNodeType
    size_bytes: int = 0
    children: List["VFSTreeNode"] = Field(default_factory=list)


# Allow self-referential model
VFSTreeNode.model_rebuild()


class VFSSearchResult(BaseModel):
    """Result of a file search operation."""

    matches: List[VFSNodeResponse]
    total_count: int
    pattern: str
    base_path: str


class VFSSessionInfo(BaseModel):
    """Information about a conversation session's files."""

    conversation_id: str
    path: str
    agents: List[str] = Field(
        default_factory=list, description="Agents with files in this session"
    )
    file_count: int = 0
    total_size_bytes: int = 0
