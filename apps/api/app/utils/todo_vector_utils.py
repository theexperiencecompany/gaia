from dataclasses import dataclass

from langchain_core.documents import Document
from pydantic import BaseModel, ConfigDict

from app.constants.log_tags import LogTag
from app.db.chroma.chromadb import ChromaClient
from app.db.repositories.todos import todo_repository
from app.models.todo_models import Priority, TodoDocument, TodoResponse
from shared.py.wide_events import log


@dataclass(frozen=True, slots=True)
class TodoSearchFilters:
    """Optional narrowing applied to a todo search."""

    completed: bool | None = None
    priority: str | None = None
    project_id: str | None = None


_NO_FILTERS = TodoSearchFilters()


class _IndexedTodoId(BaseModel):
    """The one key of a todo embedding's Chroma metadata that search reads back."""

    model_config = ConfigDict(extra="ignore")

    todo_id: str | None = None


def create_todo_content_for_embedding(todo: TodoDocument) -> str:
    """Build a text representation of a todo for embedding generation."""
    parts = []

    # Add title (most important)
    if todo.title:
        parts.append(f"Title: {todo.title}")

    # Add description if available
    if todo.description:
        parts.append(f"Description: {todo.description}")

    # Add labels for context
    if todo.labels:
        labels_text = ", ".join(todo.labels)
        parts.append(f"Labels: {labels_text}")

    # Add priority information
    if todo.priority != Priority.NONE:
        parts.append(f"Priority: {todo.priority.value}")

    # Add project context if available (we'll need to fetch project name)
    if todo.project_id:
        parts.append(f"Project ID: {todo.project_id}")

    # Add completion status
    status = "completed" if todo.completed else "pending"
    parts.append(f"Status: {status}")

    # Add subtasks information
    if todo.subtasks:
        subtask_titles = [subtask.title for subtask in todo.subtasks if subtask.title]
        if subtask_titles:
            parts.append(f"Subtasks: {', '.join(subtask_titles)}")

    return " | ".join(parts)


async def store_todo_embedding(todo_id: str, todo: TodoDocument, user_id: str) -> bool:
    """Generate and store a todo's embedding in ChromaDB. Returns success."""
    log.set(operation="store_todo_embedding", todo_id=todo_id, user_id=user_id)
    try:
        content = create_todo_content_for_embedding(todo)

        chroma_collection = await ChromaClient.get_langchain_client(
            collection_name="todos", create_if_not_exists=True
        )

        # Prepare metadata (ChromaDB requires booleans as lowercase strings)
        metadata = {
            "user_id": str(user_id),
            "todo_id": str(todo_id),
            "title": todo.title,
            "priority": todo.priority.value,
            "completed": str(todo.completed).lower(),  # Convert to "true" or "false"
            "created_at": todo.created_at.isoformat() if todo.created_at else "",
            "updated_at": todo.updated_at.isoformat() if todo.updated_at else "",
            "has_due_date": str(bool(todo.due_date)).lower(),  # Convert to "true" or "false"
            "labels_count": str(len(todo.labels)),
            "subtasks_count": str(len(todo.subtasks)),
        }

        # Add optional fields to metadata
        if todo.project_id:
            metadata["project_id"] = str(todo.project_id)

        if todo.labels:
            metadata["labels"] = ", ".join(todo.labels)

        if todo.due_date:
            metadata["due_date"] = todo.due_date.isoformat()

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


async def update_todo_embedding(todo_id: str, todo: TodoDocument, user_id: str) -> bool:
    """Replace a todo's embedding in ChromaDB. Returns success."""
    try:
        # Delete existing embedding
        await delete_todo_embedding(todo_id)

        # Store new embedding
        return await store_todo_embedding(todo_id, todo, user_id)

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


def _matched_todo_ids(results: list[tuple[Document, float]]) -> list[str]:
    """Return the todo ids a similarity search matched, in rank order."""
    todo_ids: list[str] = []
    for doc, _score in results:
        if hasattr(doc, "metadata"):
            todo_id = _IndexedTodoId.model_validate(doc.metadata).todo_id
            if todo_id is not None:
                todo_ids.append(todo_id)
    return todo_ids


async def semantic_search_todos(
    query: str,
    user_id: str,
    top_k: int = 10,
    filters: TodoSearchFilters = _NO_FILTERS,
    include_traditional_search: bool = True,
) -> list[TodoResponse]:
    """Semantic-search todos via ChromaDB, with optional filters.

    Falls back to traditional search on error when
    include_traditional_search is set.
    """
    log.set(
        operation="semantic_search_todos",
        user_id=user_id,
        search_query=query,
        top_k=top_k,
        filter_completed=filters.completed,
        filter_priority=filters.priority,
        filter_project_id=filters.project_id,
    )
    try:
        # Get ChromaDB collection
        chroma_collection = await ChromaClient.get_langchain_client(
            collection_name="todos", create_if_not_exists=True
        )

        # Build filters using ChromaDB operators (combine into single dict)
        where_filter = {"user_id": str(user_id)}

        if filters.completed is not None:
            # Convert to "true" or "false"
            where_filter["completed"] = str(filters.completed).lower()

        if filters.priority and filters.priority != "none":
            where_filter["priority"] = filters.priority

        if filters.project_id:
            where_filter["project_id"] = str(filters.project_id)

        # Perform semantic search
        results = chroma_collection.similarity_search_with_score(
            query=query, k=top_k, filter=where_filter
        )

        todo_ids = _matched_todo_ids(results)

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
    filters: TodoSearchFilters = _NO_FILTERS,
) -> list[TodoResponse]:
    """Hybrid search combining semantic and traditional results.

    semantic_weight (0.0-1.0) weights the semantic ranking.
    """
    try:
        # Get semantic results
        semantic_results = await semantic_search_todos(
            query=query,
            user_id=user_id,
            top_k=top_k,
            filters=filters,
            include_traditional_search=False,
        )

        # Get traditional search results
        from app.services.todos.todo_service import (  # noqa: PLC0415 -- todo_service imports this module at module level, so a top-level import back would be circular
            search_todos,
        )

        traditional_results = await search_todos(query, user_id)

        # Apply filters to traditional results
        if filters.completed is not None:
            traditional_results = [
                t for t in traditional_results if t.completed == filters.completed
            ]
        if filters.priority:
            traditional_results = [t for t in traditional_results if t.priority == filters.priority]
        if filters.project_id:
            traditional_results = [
                t for t in traditional_results if t.project_id == filters.project_id
            ]

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
            filters=filters,
        )
