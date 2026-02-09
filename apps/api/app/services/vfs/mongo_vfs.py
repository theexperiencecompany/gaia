"""
MongoDB-backed Virtual Filesystem (VFS) Core Service.

Provides file and folder operations backed by MongoDB with GridFS
support for large files. All operations are async and user-scoped.

SECURITY: All operations require user_id and validate access.
Users can ONLY access paths under /users/{their_user_id}/.
"""

import fnmatch
import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.config.loggers import app_logger as logger
from app.db.mongodb.collections import _get_mongodb_instance, vfs_nodes_collection
from app.models.vfs_models import (
    VFSAnalysisResult,
    VFSListResponse,
    VFSNodeResponse,
    VFSNodeType,
    VFSSearchResult,
    VFSSessionInfo,
    VFSTreeNode,
)
from app.services.vfs.path_resolver import (
    get_extension,
    get_filename,
    get_parent_path,
    normalize_path,
    validate_user_access,
)
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorGridFSBucket


class VFSAccessError(PermissionError):
    """Raised when a user attempts to access another user's files."""

    def __init__(self, path: str, user_id: str):
        self.path = path
        self.user_id = user_id
        super().__init__(
            f"Access denied: User '{user_id}' cannot access path '{path}'. "
            f"Users can only access /users/{user_id}/..."
        )


class MongoVFS:
    """
    MongoDB-backed Virtual Filesystem.

    Storage strategy:
    - Small files (< 1MB): stored inline in vfs_nodes.content
    - Large files (>= 1MB): stored in GridFS, referenced by gridfs_id

    SECURITY: All paths are user-scoped: /users/{user_id}/...
    All operations validate that the requesting user owns the path.
    """

    # Files smaller than this are stored inline
    INLINE_SIZE_LIMIT = 1_048_576  # 1MB

    def __init__(self):
        self._gridfs_bucket: Optional[AsyncIOMotorGridFSBucket] = None

    async def _get_gridfs(self) -> AsyncIOMotorGridFSBucket:
        """Lazy-load GridFS bucket."""
        if self._gridfs_bucket is None:
            mongodb = _get_mongodb_instance()
            self._gridfs_bucket = AsyncIOMotorGridFSBucket(mongodb.database)
        return self._gridfs_bucket

    def _validate_access(self, path: str, user_id: str) -> str:
        """
        Validate that the user has access to the path.

        Args:
            path: The path to validate
            user_id: The user requesting access

        Returns:
            The normalized path if access is valid

        Raises:
            VFSAccessError: If user doesn't have access to the path
            ValueError: If user_id is not provided
        """
        if not user_id:
            raise ValueError("user_id is required for VFS operations")

        normalized = normalize_path(path)

        # Validate that the path belongs to this user
        if not validate_user_access(normalized, user_id):
            logger.warning(
                f"VFS ACCESS DENIED: User '{user_id}' attempted to access '{path}'"
            )
            raise VFSAccessError(normalized, user_id)

        return normalized

    def _auto_prefix_path(self, path: str, user_id: str) -> str:
        """
        Auto-prefix a path with user scope if not already scoped.

        Args:
            path: The path to prefix
            user_id: The user ID

        Returns:
            The path with proper user scope
        """
        normalized = normalize_path(path)
        if not normalized.startswith("/users/"):
            normalized = f"/users/{user_id}/global/{normalized.lstrip('/')}"
        return normalized

    # ==================== Write Operations ====================

    async def write(
        self,
        path: str,
        content: str,
        user_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Write a file to the VFS.

        Auto-creates parent directories.
        Overwrites if file already exists.

        Args:
            path: Target path for the file
            content: File content (string)
            user_id: The user ID (REQUIRED for security)
            metadata: Optional metadata dict

        Returns:
            The normalized file path

        Raises:
            VFSAccessError: If user doesn't have access to the path
        """
        # Auto-prefix and validate
        path = self._auto_prefix_path(path, user_id)
        path = self._validate_access(path, user_id)

        parent = get_parent_path(path)
        name = get_filename(path)
        metadata = metadata or {}
        metadata["user_id"] = user_id  # Track ownership
        now = datetime.now(timezone.utc)

        # Ensure parent directories exist (with user_id)
        await self._ensure_directories(parent, user_id)

        content_bytes = content.encode("utf-8")
        size_bytes = len(content_bytes)

        # Determine storage strategy
        if size_bytes >= self.INLINE_SIZE_LIMIT:
            # Store in GridFS
            bucket = await self._get_gridfs()

            # Delete existing GridFS file if exists
            existing = await vfs_nodes_collection.find_one(
                {"path": path, "user_id": user_id}
            )
            if existing and existing.get("gridfs_id"):
                try:
                    await bucket.delete(ObjectId(existing["gridfs_id"]))
                except Exception:
                    pass  # nosec B110

            gridfs_id = await bucket.upload_from_stream(
                path, content_bytes, metadata={"path": path, "user_id": user_id}
            )
            inline_content = None
            gridfs_id_str = str(gridfs_id)
        else:
            # Store inline
            gridfs_id_str = None
            inline_content = content

            # Clean up any existing GridFS reference
            existing = await vfs_nodes_collection.find_one(
                {"path": path, "user_id": user_id}
            )
            if existing and existing.get("gridfs_id"):
                try:
                    bucket = await self._get_gridfs()
                    await bucket.delete(ObjectId(existing["gridfs_id"]))
                except Exception:
                    pass  # nosec B110

        # Upsert the file node - MUST include user_id in query for security
        await vfs_nodes_collection.update_one(
            {"path": path, "user_id": user_id},
            {
                "$set": {
                    "name": name,
                    "node_type": VFSNodeType.FILE.value,
                    "parent_path": parent,
                    "content": inline_content,
                    "gridfs_id": gridfs_id_str,
                    "content_type": self._detect_content_type(name),
                    "size_bytes": size_bytes,
                    "metadata": metadata,
                    "updated_at": now,
                    "accessed_at": now,
                },
                "$setOnInsert": {
                    "user_id": user_id,
                    "created_at": now,
                },
            },
            upsert=True,
        )

        logger.debug(f"VFS: Wrote file {path} ({size_bytes} bytes) for user {user_id}")
        return path

    async def append(self, path: str, content: str, user_id: str) -> str:
        """
        Append content to an existing file.

        Creates the file if it doesn't exist.

        Args:
            path: Target file path
            content: Content to append
            user_id: The user ID (REQUIRED for security)

        Returns:
            The file path

        Raises:
            VFSAccessError: If user doesn't have access to the path
        """
        path = self._auto_prefix_path(path, user_id)
        path = self._validate_access(path, user_id)

        existing = await self.read(path, user_id)
        if existing is None:
            return await self.write(path, content, user_id)

        new_content = existing + content
        # Preserve existing metadata
        node = await vfs_nodes_collection.find_one({"path": path, "user_id": user_id})
        metadata = node.get("metadata", {}) if node else {}
        return await self.write(path, new_content, user_id, metadata)

    async def mkdir(self, path: str, user_id: str) -> str:
        """
        Create a directory (and all parent directories).

        Args:
            path: Directory path to create
            user_id: The user ID (REQUIRED for security)

        Returns:
            The normalized directory path

        Raises:
            VFSAccessError: If user doesn't have access to the path
        """
        path = self._auto_prefix_path(path, user_id)
        path = self._validate_access(path, user_id)

        await self._ensure_directories(path, user_id)
        logger.debug(f"VFS: Created directory {path} for user {user_id}")
        return path

    # ==================== Read Operations ====================

    async def read(self, path: str, user_id: str) -> Optional[str]:
        """
        Read file content.

        Args:
            path: File path to read
            user_id: The user ID (REQUIRED for security)

        Returns:
            File content as string, or None if not found

        Raises:
            VFSAccessError: If user doesn't have access to the path
        """
        path = self._auto_prefix_path(path, user_id)
        path = self._validate_access(path, user_id)

        # Query MUST include user_id for security
        node = await vfs_nodes_collection.find_one({"path": path, "user_id": user_id})
        if not node or node.get("node_type") != VFSNodeType.FILE.value:
            return None

        # Update accessed_at
        await vfs_nodes_collection.update_one(
            {"path": path, "user_id": user_id},
            {"$set": {"accessed_at": datetime.now(timezone.utc)}},
        )

        # Check inline first
        if node.get("content") is not None:
            return node["content"]

        # Load from GridFS
        if node.get("gridfs_id"):
            try:
                bucket = await self._get_gridfs()
                stream = await bucket.open_download_stream(ObjectId(node["gridfs_id"]))
                content_bytes = await stream.read()
                return content_bytes.decode("utf-8")
            except Exception as e:
                logger.error(f"VFS: Error reading GridFS file {path}: {e}")
                return None

        return None

    async def exists(self, path: str, user_id: str) -> bool:
        """
        Check if a path (file or folder) exists.

        Args:
            path: Path to check
            user_id: The user ID (REQUIRED for security)

        Returns:
            True if exists, False otherwise

        Raises:
            VFSAccessError: If user doesn't have access to the path
        """
        path = self._auto_prefix_path(path, user_id)
        path = self._validate_access(path, user_id)

        # Query MUST include user_id for security
        node = await vfs_nodes_collection.find_one(
            {"path": path, "user_id": user_id}, {"_id": 1}
        )
        return node is not None

    async def info(self, path: str, user_id: str) -> Optional[VFSNodeResponse]:
        """
        Get file/folder metadata.

        Args:
            path: Path to get info for
            user_id: The user ID (REQUIRED for security)

        Returns:
            VFSNodeResponse or None if not found

        Raises:
            VFSAccessError: If user doesn't have access to the path
        """
        path = self._auto_prefix_path(path, user_id)
        path = self._validate_access(path, user_id)

        # Query MUST include user_id for security
        node = await vfs_nodes_collection.find_one(
            {"path": path, "user_id": user_id}, {"content": 0, "gridfs_id": 0}
        )

        if not node:
            return None

        return VFSNodeResponse(
            path=node["path"],
            name=node["name"],
            node_type=VFSNodeType(node["node_type"]),
            size_bytes=node.get("size_bytes", 0),
            content_type=node.get("content_type", "text/plain"),
            created_at=node.get("created_at"),
            updated_at=node.get("updated_at"),
            metadata=node.get("metadata", {}),
        )

    # ==================== List Operations ====================

    async def list_dir(
        self,
        path: str,
        user_id: str,
        recursive: bool = False,
    ) -> VFSListResponse:
        """
        List directory contents.

        Args:
            path: Directory path to list
            user_id: The user ID (REQUIRED for security)
            recursive: If True, list all descendants

        Returns:
            VFSListResponse with items and count

        Raises:
            VFSAccessError: If user doesn't have access to the path
        """
        path = self._auto_prefix_path(path, user_id)
        path = self._validate_access(path, user_id)
        path = path.rstrip("/")

        # Query MUST include user_id for security
        if recursive:
            query = {"path": {"$regex": f"^{path}/"}, "user_id": user_id}
        else:
            query = {"parent_path": path, "user_id": user_id}

        cursor = vfs_nodes_collection.find(query, {"content": 0, "gridfs_id": 0}).sort(
            "name", 1
        )

        nodes = await cursor.to_list(length=1000)

        items = [
            VFSNodeResponse(
                path=n["path"],
                name=n["name"],
                node_type=VFSNodeType(n["node_type"]),
                size_bytes=n.get("size_bytes", 0),
                content_type=n.get("content_type", "text/plain"),
                created_at=n.get("created_at"),
                updated_at=n.get("updated_at"),
                metadata=n.get("metadata", {}),
            )
            for n in nodes
        ]

        return VFSListResponse(
            path=path,
            items=items,
            total_count=len(items),
        )

    async def tree(self, path: str, user_id: str, depth: int = 3) -> VFSTreeNode:
        """
        Get a directory tree representation.

        Args:
            path: Root path for the tree
            user_id: The user ID (REQUIRED for security)
            depth: Maximum depth to traverse

        Returns:
            VFSTreeNode with nested children

        Raises:
            VFSAccessError: If user doesn't have access to the path
        """
        path = self._auto_prefix_path(path, user_id)
        path = self._validate_access(path, user_id)

        # Query MUST include user_id for security
        node = await vfs_nodes_collection.find_one({"path": path, "user_id": user_id})

        if not node:
            # Create a virtual root node
            return VFSTreeNode(
                name=get_filename(path) or "root",
                path=path,
                node_type=VFSNodeType.FOLDER,
                children=[],
            )

        return await self._build_tree_node(node, user_id, depth)

    async def _build_tree_node(
        self, node: dict, user_id: str, depth: int
    ) -> VFSTreeNode:
        """Recursively build tree nodes."""
        tree_node = VFSTreeNode(
            name=node["name"],
            path=node["path"],
            node_type=VFSNodeType(node["node_type"]),
            size_bytes=node.get("size_bytes", 0),
            children=[],
        )

        if depth > 0 and node["node_type"] == VFSNodeType.FOLDER.value:
            # Query MUST include user_id for security
            children = await vfs_nodes_collection.find(
                {"parent_path": node["path"], "user_id": user_id},
                {"content": 0, "gridfs_id": 0},
            ).to_list(length=100)

            for child in children:
                child_tree = await self._build_tree_node(child, user_id, depth - 1)
                tree_node.children.append(child_tree)

        return tree_node

    async def search(
        self,
        pattern: str,
        user_id: str,
        base_path: Optional[str] = None,
    ) -> VFSSearchResult:
        """
        Search for files matching a glob pattern.

        Args:
            pattern: Glob pattern (e.g., "*.json", "**/*.txt")
            user_id: The user ID (REQUIRED for security)
            base_path: Optional base path to search from (defaults to user root)

        Returns:
            VFSSearchResult with matching files

        Raises:
            VFSAccessError: If user doesn't have access to the path
        """
        if not user_id:
            raise ValueError("user_id is required for VFS search")

        # Default to user's root if no base_path provided
        if base_path is None:
            base_path = f"/users/{user_id}"
        else:
            base_path = self._auto_prefix_path(base_path, user_id)
            base_path = self._validate_access(base_path, user_id)

        # Query MUST include user_id for security
        query: Dict[str, Any] = {
            "path": {"$regex": f"^{base_path}"},
            "user_id": user_id,  # CRITICAL: Always filter by user
        }

        cursor = vfs_nodes_collection.find(query, {"content": 0, "gridfs_id": 0})
        nodes = await cursor.to_list(length=1000)

        # Filter by glob pattern
        matches = []
        for node in nodes:
            relative_path = node["path"][len(base_path) :].lstrip("/")
            if fnmatch.fnmatch(relative_path, pattern) or fnmatch.fnmatch(
                node["name"], pattern
            ):
                matches.append(
                    VFSNodeResponse(
                        path=node["path"],
                        name=node["name"],
                        node_type=VFSNodeType(node["node_type"]),
                        size_bytes=node.get("size_bytes", 0),
                        content_type=node.get("content_type", "text/plain"),
                        created_at=node.get("created_at"),
                        updated_at=node.get("updated_at"),
                        metadata=node.get("metadata", {}),
                    )
                )

        return VFSSearchResult(
            matches=matches,
            total_count=len(matches),
            pattern=pattern,
            base_path=base_path,
        )

    # ==================== Modify Operations ====================

    async def delete(self, path: str, user_id: str, recursive: bool = False) -> bool:
        """
        Delete a file or directory.

        Args:
            path: Path to delete
            user_id: The user ID (REQUIRED for security)
            recursive: If True, delete non-empty directories

        Returns:
            True if deleted, False if not found

        Raises:
            VFSAccessError: If user doesn't have access to the path
        """
        path = self._auto_prefix_path(path, user_id)
        path = self._validate_access(path, user_id)

        # Query MUST include user_id for security
        node = await vfs_nodes_collection.find_one({"path": path, "user_id": user_id})
        if not node:
            return False

        if node["node_type"] == VFSNodeType.FOLDER.value:
            if not recursive:
                # Check if empty
                child = await vfs_nodes_collection.find_one(
                    {"parent_path": path, "user_id": user_id}
                )
                if child:
                    raise ValueError("Directory not empty. Use recursive=True.")

            # Delete all children - MUST include user_id
            children = await vfs_nodes_collection.find(
                {"path": {"$regex": f"^{path}/"}, "user_id": user_id}
            ).to_list(length=None)

            bucket = await self._get_gridfs()
            for child in children:
                if child.get("gridfs_id"):
                    try:
                        await bucket.delete(ObjectId(child["gridfs_id"]))
                    except Exception:
                        pass  # nosec B110

            await vfs_nodes_collection.delete_many(
                {"path": {"$regex": f"^{path}/"}, "user_id": user_id}
            )

        # Delete the node itself
        if node.get("gridfs_id"):
            try:
                bucket = await self._get_gridfs()
                await bucket.delete(ObjectId(node["gridfs_id"]))
            except Exception:
                pass  # nosec B110

        await vfs_nodes_collection.delete_one({"path": path, "user_id": user_id})
        logger.debug(f"VFS: Deleted {path} for user {user_id}")
        return True

    async def move(self, source: str, dest: str, user_id: str) -> str:
        """
        Move/rename a file or directory.

        Args:
            source: Source path
            dest: Destination path
            user_id: The user ID (REQUIRED for security)

        Returns:
            The new path

        Raises:
            VFSAccessError: If user doesn't have access to source or dest
        """
        source = self._auto_prefix_path(source, user_id)
        dest = self._auto_prefix_path(dest, user_id)
        source = self._validate_access(source, user_id)
        dest = self._validate_access(dest, user_id)

        # Query MUST include user_id for security
        node = await vfs_nodes_collection.find_one({"path": source, "user_id": user_id})
        if not node:
            raise FileNotFoundError(f"Source not found: {source}")

        # Ensure destination parent exists
        dest_parent = get_parent_path(dest)
        await self._ensure_directories(dest_parent, user_id)

        now = datetime.now(timezone.utc)

        if node["node_type"] == VFSNodeType.FOLDER.value:
            # Move all children - MUST include user_id
            children = await vfs_nodes_collection.find(
                {"path": {"$regex": f"^{source}/"}, "user_id": user_id}
            ).to_list(length=None)

            for child in children:
                new_child_path = dest + child["path"][len(source) :]
                new_parent = get_parent_path(new_child_path)
                await vfs_nodes_collection.update_one(
                    {"_id": child["_id"], "user_id": user_id},
                    {
                        "$set": {
                            "path": new_child_path,
                            "parent_path": new_parent,
                            "updated_at": now,
                        }
                    },
                )

        # Update the node itself
        await vfs_nodes_collection.update_one(
            {"path": source, "user_id": user_id},
            {
                "$set": {
                    "path": dest,
                    "name": get_filename(dest),
                    "parent_path": dest_parent,
                    "updated_at": now,
                }
            },
        )

        logger.debug(f"VFS: Moved {source} -> {dest} for user {user_id}")
        return dest

    async def copy(self, source: str, dest: str, user_id: str) -> str:
        """
        Copy a file.

        Note: Directory copy is not supported.

        Args:
            source: Source file path
            dest: Destination path
            user_id: The user ID (REQUIRED for security)

        Returns:
            The destination path

        Raises:
            VFSAccessError: If user doesn't have access to source or dest
        """
        source = self._auto_prefix_path(source, user_id)
        dest = self._auto_prefix_path(dest, user_id)
        source = self._validate_access(source, user_id)
        dest = self._validate_access(dest, user_id)

        # Query MUST include user_id for security
        node = await vfs_nodes_collection.find_one({"path": source, "user_id": user_id})
        if not node:
            raise FileNotFoundError(f"Source not found: {source}")

        if node["node_type"] == VFSNodeType.FOLDER.value:
            raise ValueError("Directory copy not supported")

        # Read content and write to new location
        content = await self.read(source, user_id)
        if content is None:
            raise FileNotFoundError(f"Could not read source: {source}")

        metadata = dict(node.get("metadata", {}))
        metadata["copied_from"] = source

        return await self.write(dest, content, user_id, metadata)

    # ==================== Analysis Operations ====================

    async def analyze(
        self,
        path: str,
        user_id: str,
        include_schema: bool = True,
        include_stats: bool = True,
        sample_size: int = 3,
    ) -> VFSAnalysisResult:
        """
        Analyze file content and return structured metadata.

        Args:
            path: File path to analyze
            user_id: The user ID (REQUIRED for security)
            include_schema: Whether to infer JSON schema
            include_stats: Whether to include size stats
            sample_size: Number of sample values to include

        Returns:
            VFSAnalysisResult with analysis data

        Raises:
            VFSAccessError: If user doesn't have access to the path
        """
        path = self._auto_prefix_path(path, user_id)
        path = self._validate_access(path, user_id)

        content = await self.read(path, user_id)

        if content is None:
            raise FileNotFoundError(f"File not found: {path}")

        ext = get_extension(path)
        file_type = self._classify_file_type(ext, content)

        result = VFSAnalysisResult(
            path=path,
            file_type=file_type,
            size_bytes=len(content.encode("utf-8")),
            size_human=self._format_size(len(content.encode("utf-8"))),
            character_count=len(content),
            line_count=content.count("\n") + 1,
        )

        if file_type == "json" and include_schema:
            try:
                data = json.loads(content)
                schema_info = self._analyze_json(data, sample_size)
                result.json_schema = schema_info.get("schema")
                result.array_lengths = schema_info.get("array_lengths")
                result.nested_depth = schema_info.get("nested_depth", 0)
                result.field_count = schema_info.get("field_count", 0)
                result.sample_values = schema_info.get("sample_values")
                result.value_types = schema_info.get("value_types")
            except json.JSONDecodeError:
                pass

        if file_type == "text" and include_stats:
            result.word_count = len(content.split())

        return result

    async def get_session_info(
        self, user_id: str, conversation_id: str
    ) -> VFSSessionInfo:
        """
        Get information about a conversation session's files.

        Args:
            user_id: The user ID (REQUIRED for security)
            conversation_id: The conversation ID

        Returns:
            VFSSessionInfo with session file details
        """
        if not user_id:
            raise ValueError("user_id is required for VFS operations")

        from app.services.vfs.path_resolver import get_session_path

        session_path = get_session_path(user_id, conversation_id)

        # Query MUST include user_id for security
        query = {
            "path": {"$regex": f"^{session_path}/"},
            "node_type": VFSNodeType.FILE.value,
            "user_id": user_id,  # CRITICAL: Always filter by user
        }
        cursor = vfs_nodes_collection.find(query, {"path": 1, "size_bytes": 1})
        files = await cursor.to_list(length=1000)

        # Extract unique agent names
        agents = set()
        total_size = 0
        for f in files:
            # Path format: .../sessions/{conv_id}/{agent_name}/...
            path_parts = f["path"].split("/")
            try:
                session_idx = path_parts.index("sessions")
                if len(path_parts) > session_idx + 2:
                    agents.add(path_parts[session_idx + 2])
            except ValueError:
                pass
            total_size += f.get("size_bytes", 0)

        return VFSSessionInfo(
            conversation_id=conversation_id,
            path=session_path,
            agents=sorted(agents),
            file_count=len(files),
            total_size_bytes=total_size,
        )

    # ==================== Helper Methods ====================

    async def _ensure_directories(self, path: str, user_id: str) -> None:
        """Create all directories in path if they don't exist."""
        if path == "/" or not path:
            return

        path = normalize_path(path)
        parts = [p for p in path.split("/") if p]
        current = ""

        for part in parts:
            current += "/" + part

            # Query MUST include user_id for security
            exists = await vfs_nodes_collection.find_one(
                {"path": current, "user_id": user_id}
            )
            if not exists:
                now = datetime.now(timezone.utc)
                await vfs_nodes_collection.insert_one(
                    {
                        "path": current,
                        "name": part,
                        "node_type": VFSNodeType.FOLDER.value,
                        "parent_path": get_parent_path(current),
                        "content": None,
                        "gridfs_id": None,
                        "content_type": "inode/directory",
                        "size_bytes": 0,
                        "metadata": {},
                        "user_id": user_id,  # CRITICAL: Set user ownership
                        "created_at": now,
                        "updated_at": now,
                        "accessed_at": now,
                    }
                )

    def _detect_content_type(self, filename: str) -> str:
        """Detect MIME type from filename."""
        ext = get_extension(filename)
        return {
            "json": "application/json",
            "txt": "text/plain",
            "md": "text/markdown",
            "csv": "text/csv",
            "html": "text/html",
            "xml": "application/xml",
            "yaml": "application/yaml",
            "yml": "application/yaml",
            "py": "text/x-python",
            "js": "text/javascript",
            "ts": "text/typescript",
        }.get(ext, "text/plain")

    def _classify_file_type(self, ext: str, content: str) -> str:
        """Classify file type based on extension and content."""
        if ext == "json":
            return "json"
        if ext in ("yaml", "yml"):
            return "yaml"
        if ext == "csv":
            return "csv"
        if ext in ("md", "markdown"):
            return "markdown"

        # Try to detect JSON
        stripped = content.strip()
        if stripped.startswith(("{", "[")):
            try:
                json.loads(content)
                return "json"
            except json.JSONDecodeError:
                pass

        return "text"

    def _format_size(self, size_bytes: int) -> str:
        """Format bytes to human-readable string."""
        size = float(size_bytes)
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    def _analyze_json(self, data: Any, sample_size: int = 3) -> Dict[str, Any]:
        """Analyze JSON structure."""
        result: Dict[str, Any] = {
            "schema": {},
            "array_lengths": {},
            "nested_depth": 0,
            "field_count": 0,
            "sample_values": {},
            "value_types": {},
        }

        def get_type(val: Any) -> str:
            if val is None:
                return "null"
            if isinstance(val, bool):
                return "boolean"
            if isinstance(val, int):
                return "integer"
            if isinstance(val, float):
                return "number"
            if isinstance(val, str):
                return "string"
            if isinstance(val, list):
                return "array"
            if isinstance(val, dict):
                return "object"
            return "unknown"

        def analyze_value(val: Any, path: str = "", depth: int = 0) -> Dict[str, Any]:
            result["nested_depth"] = max(result["nested_depth"], depth)

            if isinstance(val, dict):
                schema: Dict[str, Any] = {"type": "object", "properties": {}}
                for key, v in val.items():
                    field_path = f"{path}.{key}" if path else key
                    result["field_count"] += 1
                    schema["properties"][key] = analyze_value(v, field_path, depth + 1)
                return schema

            elif isinstance(val, list):
                array_path = path or "root"
                result["array_lengths"][array_path] = len(val)

                if not val:
                    return {"type": "array", "items": {}}

                # Analyze first few items
                item_schemas = [
                    analyze_value(item, f"{path}[]", depth + 1) for item in val[:3]
                ]
                # Use first item's schema as representative
                return {
                    "type": "array",
                    "items": item_schemas[0] if item_schemas else {},
                }

            else:
                val_type = get_type(val)
                if path and sample_size > 0:
                    if path not in result["sample_values"]:
                        result["sample_values"][path] = []
                    if len(result["sample_values"][path]) < sample_size:
                        result["sample_values"][path].append(val)
                    result["value_types"][path] = val_type
                return {"type": val_type}

        result["schema"] = analyze_value(data)
        return result
