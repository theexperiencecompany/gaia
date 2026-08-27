from datetime import UTC, datetime
from typing import Any

from app.constants.log_tags import LogTag
from app.db.chroma.chromadb import ChromaClient
from app.db.repositories.todos import todo_repository
from app.models.todo_models import TodoResponse
from shared.py.wide_events import log


def create_todo_content_for_embedding(todo_data: dict[str, Any]) -> str:
    """Build a text representation of a todo for embedding generation.

    Takes a dict rather than the ``TodoResponse`` its callers dump, because
    every field is read defensively: the indexers are expected to cope with a
    partial todo (no title, no subtasks, a string ``created_at``) and still
    produce something embeddable. Narrowing to the model would delete that
    tolerance, not just describe it (Type Safety items 13/14).
    """
    parts = []

    # Add title (most important)
    if todo_data.get("title"):
        parts.append(f"Title: {todo_data['title']}")

    # Add description if available
    if todo_data.get("description"):
        parts.append(f"Description: {todo_data['description']}")

    # Add labels for context
    if todo_data.get("labels"):
        labels_text = ", ".join(todo_data["labels"])
        parts.append(f"Labels: {labels_text}")

    # Add priority information
    if todo_data.get("priority") and todo_data["priority"] != "none":
        parts.append(f"Priority: {todo_data['priority']}")

    # Add project context if available (we'll need to fetch project name)
    if todo_data.get("project_id"):
        parts.append(f"Project ID: {todo_data['project_id']}")

    # Add completion status
    status = "completed" if todo_data.get("completed", False) else "pending"
    parts.append(f"Status: {status}")

    # Add subtasks information
    if todo_data.get("subtasks"):
        subtask_titles = [
            subtask.get("title", "") for subtask in todo_data["subtasks"] if subtask.get("title")
        ]
        if subtask_titles:
            parts.append(f"Subtasks: {', '.join(subtask_titles)}")

    return " | ".join(parts)


async def store_todo_embedding(todo_id: str, todo_data: dict[str, Any], user_id: str) -> bool:
    """Generate and store a todo's embedding in ChromaDB. Returns success."""
    log.set(operation="store_todo_embedding", todo_id=todo_id, user_id=user_id)
    try:
        # Create content for embedding
        content = create_todo_content_for_embedding(todo_data)

        # Get ChromaDB collection
        chroma_collection = await ChromaClient.get_langchain_client(
            collection_name="todos", create_if_not_exists=True
        )

        # Prepare metadata (ChromaDB requires booleans as lowercase strings)
        metadata = {
            "user_id": str(user_id),
            "todo_id": str(todo_id),
            "title": todo_data.get("title", ""),
            "priority": todo_data.get("priority", "none"),
            "completed": str(
                todo_data.get("completed", False)
            ).lower(),  # Convert to "true" or "false"
            "created_at": (
                todo_data.get("created_at", datetime.now(UTC)).isoformat()
                if isinstance(todo_data.get("created_at"), datetime)
                else str(todo_data.get("created_at", ""))
            ),
            "updated_at": (
                todo_data.get("updated_at", datetime.now(UTC)).isoformat()
                if isinstance(todo_data.get("updated_at"), datetime)
                else str(todo_data.get("updated_at", ""))
            ),
            "has_due_date": str(
                bool(todo_data.get("due_date"))
            ).lower(),  # Convert to "true" or "false"
            "labels_count": str(len(todo_data.get("labels", []))),
            "subtasks_count": str(len(todo_data.get("subtasks", []))),
        }

        # Add optional fields to metadata
        if todo_data.get("project_id"):
            metadata["project_id"] = str(todo_data["project_id"])

        if todo_data.get("labels"):
            metadata["labels"] = ", ".join(todo_data["labels"])

        if todo_data.get("due_date"):
            metadata["due_date"] = (
                todo_data["due_date"].isoformat()
                if isinstance(todo_data["due_date"], datetime)
                else str(todo_data["due_date"])
            )

        # Store in ChromaDB (LangChain Chroma handles embedding generation automatically)
        chroma_collection.add_texts(texts=[content], metadatas=[metadata], ids=[str(todo_id)])

        log.info(f"{LogTag.CHROMA} Stored embedding for todo", todo_id=todo_id)
        return True

    except Exception as e:
        log.error(
            f"{LogTag.CHROMA} Error storing embedding for todo",
            todo_id=todo_id,
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )
        return False


async def update_todo_embedding(todo_id: str, todo_data: dict[str, Any], user_id: str) -> bool:
    """Replace a todo's embedding in ChromaDB. Returns success."""
    try:
        # Delete existing embedding
        await delete_todo_embedding(todo_id)

        # Store new embedding
        return await store_todo_embedding(todo_id, todo_data, user_id)

    except Exception as e:
        log.error(
            f"{LogTag.CHROMA} Error updating embedding for todo",
            todo_id=todo_id,
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )
        return False


async def delete_todo_embedding(todo_id: str) -> bool:
    """Delete a todo's embedding from ChromaDB. Returns success."""
    try:
        # Get ChromaDB collection
        chroma_collection = await ChromaClient.get_langchain_client(
            collection_name="todos", create_if_not_exists=True
        )

        # Delete the embedding
        chroma_collection.delete(ids=[str(todo_id)])

        log.info(f"{LogTag.CHROMA} Deleted embedding for todo", todo_id=todo_id)
        return True

    except Exception as e:
        log.error(
            f"{LogTag.CHROMA} Error deleting embedding for todo",
            todo_id=todo_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        return False


async def semantic_search_todos(
    query: str,
    user_id: str,
    top_k: int = 10,
    completed: bool | None = None,
    priority: str | None = None,
    project_id: str | None = None,
    include_traditional_search: bool = True,
) -> list[TodoResponse]:
    """Semantic-search todos via ChromaDB, with optional filters.

    Falls back to traditional search on error when
    ``include_traditional_search`` is set.
    """
    log.set(
        operation="semantic_search_todos",
        user_id=user_id,
        search_query=query,
        top_k=top_k,
        filter_completed=completed,
        filter_priority=priority,
        filter_project_id=project_id,
    )
    try:
        # Get ChromaDB collection
        chroma_collection = await ChromaClient.get_langchain_client(
            collection_name="todos", create_if_not_exists=True
        )

        # Build filters using ChromaDB operators (combine into single dict)
        where_filter = {"user_id": str(user_id)}

        if completed is not None:
            where_filter["completed"] = str(completed).lower()  # Convert to "true" or "false"

        if priority and priority != "none":
            where_filter["priority"] = priority

        if project_id:
            where_filter["project_id"] = str(project_id)

        # Perform semantic search
        results = chroma_collection.similarity_search_with_score(
            query=query, k=top_k, filter=where_filter
        )

        # Extract todo IDs from results
        todo_ids = []
        for doc, _score in results:
            if hasattr(doc, "metadata") and "todo_id" in doc.metadata:
                todo_ids.append(doc.metadata["todo_id"])

        if not todo_ids:
            # No vector results found
            log.info(f"{LogTag.CHROMA} No vector results for query", query=query)
            return []

        # Fetch full todo documents in the order of similarity
        todos = []
        for todo_id in todo_ids:
            todo_doc = await todo_repository.get(todo_id, user_id=user_id)
            if todo_doc:
                todos.append(TodoResponse.from_document(todo_doc))

        log.info(
            f"{LogTag.CHROMA} Semantic search returned todos", todo_count=len(todos), query=query
        )
        return todos

    except Exception as e:
        log.error(
            f"{LogTag.CHROMA} Error in semantic search for todos",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )

        # Fallback to traditional search on error
        if include_traditional_search:
            log.info(f"{LogTag.CHROMA} Falling back to traditional search due to error")
            # Deferred import: breaks circular dependency: todo_service imports this module
            from app.services.todos.todo_service import search_todos  # noqa: PLC0415 -- deferred

            return await search_todos(query, user_id)

        return []


async def hybrid_search_todos(
    query: str,
    user_id: str,
    top_k: int = 10,
    semantic_weight: float = 0.7,
    completed: bool | None = None,
    priority: str | None = None,
    project_id: str | None = None,
) -> list[TodoResponse]:
    """Hybrid search combining semantic and traditional results.

    ``semantic_weight`` (0.0-1.0) weights the semantic ranking.
    """
    try:
        # Get semantic results
        semantic_results = await semantic_search_todos(
            query=query,
            user_id=user_id,
            top_k=top_k,
            completed=completed,
            priority=priority,
            project_id=project_id,
            include_traditional_search=False,
        )

        # Get traditional search results
        from app.services.todos.todo_service import (  # noqa: PLC0415 -- todo_service imports this module at module level, so a top-level import back would be circular
            search_todos,
        )

        traditional_results = await search_todos(query, user_id)

        # Apply filters to traditional results
        if completed is not None:
            traditional_results = [t for t in traditional_results if t.completed == completed]
        if priority:
            traditional_results = [t for t in traditional_results if t.priority == priority]
        if project_id:
            traditional_results = [t for t in traditional_results if t.project_id == project_id]

        # Combine results with scoring
        combined_scores: dict[str, float] = {}

        # Score semantic results
        for i, todo in enumerate(semantic_results[:top_k]):
            score = semantic_weight * (1.0 - (i / len(semantic_results)))
            combined_scores[todo.id] = combined_scores.get(todo.id, 0) + score

        # Score traditional results
        traditional_weight = 1.0 - semantic_weight
        for i, todo in enumerate(traditional_results[:top_k]):
            score = traditional_weight * (1.0 - (i / len(traditional_results)))
            combined_scores[todo.id] = combined_scores.get(todo.id, 0) + score

        # Create combined result set
        all_todos = {todo.id: todo for todo in semantic_results + traditional_results}

        # Sort by combined score
        sorted_todo_ids = sorted(
            combined_scores.keys(), key=lambda x: combined_scores[x], reverse=True
        )

        # Return top results
        result = [all_todos[todo_id] for todo_id in sorted_todo_ids[:top_k]]

        log.info(
            f"{LogTag.CHROMA} Hybrid search returned todos", todo_count=len(result), query=query
        )
        return result

    except Exception as e:
        log.error(
            f"{LogTag.CHROMA} Error in hybrid search",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )
        # Fallback to semantic search only
        return await semantic_search_todos(
            query,
            user_id,
            top_k,
            completed=completed,
            priority=priority,
            project_id=project_id,
        )
