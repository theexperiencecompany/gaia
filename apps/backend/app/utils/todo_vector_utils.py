from datetime import datetime, timezone
from typing import List, Optional

from bson import ObjectId

from app.config.loggers import todos_logger as logger
from app.db.chromadb import ChromaClient
from app.db.mongodb.collections import todos_collection
from app.db.utils import serialize_document
from app.models.todo_models import TodoResponse


def create_todo_content_for_embedding(todo_data: dict) -> str:
    """
    Create a comprehensive text representation of a todo for embedding generation.

    Args:
        todo_data: The todo document from MongoDB

    Returns:
        str: Formatted text representation for embedding
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
            subtask.get("title", "")
            for subtask in todo_data["subtasks"]
            if subtask.get("title")
        ]
        if subtask_titles:
            parts.append(f"Subtasks: {', '.join(subtask_titles)}")

    return " | ".join(parts)


async def store_todo_embedding(todo_id: str, todo_data: dict, user_id: str) -> bool:
    """
    Generate and store embedding for a todo in ChromaDB.

    Args:
        todo_id: The todo ID
        todo_data: The todo document data
        user_id: The user ID

    Returns:
        bool: True if successful, False otherwise
    """
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
                todo_data.get("created_at", datetime.now(timezone.utc)).isoformat()
                if isinstance(todo_data.get("created_at"), datetime)
                else str(todo_data.get("created_at", ""))
            ),
            "updated_at": (
                todo_data.get("updated_at", datetime.now(timezone.utc)).isoformat()
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
        chroma_collection.add_texts(
            texts=[content], metadatas=[metadata], ids=[str(todo_id)]
        )

        logger.info(f"Stored embedding for todo {todo_id}")
        return True

    except Exception as e:
        logger.error(f"Error storing embedding for todo {todo_id}: {str(e)}")
        return False


async def update_todo_embedding(todo_id: str, todo_data: dict, user_id: str) -> bool:
    """
    Update existing todo embedding in ChromaDB.

    Args:
        todo_id: The todo ID
        todo_data: The updated todo document data
        user_id: The user ID

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Delete existing embedding
        await delete_todo_embedding(todo_id)

        # Store new embedding
        return await store_todo_embedding(todo_id, todo_data, user_id)

    except Exception as e:
        logger.error(f"Error updating embedding for todo {todo_id}: {str(e)}")
        return False


async def delete_todo_embedding(todo_id: str) -> bool:
    """
    Delete todo embedding from ChromaDB.

    Args:
        todo_id: The todo ID

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Get ChromaDB collection
        chroma_collection = await ChromaClient.get_langchain_client(
            collection_name="todos", create_if_not_exists=True
        )

        # Delete the embedding
        chroma_collection.delete(ids=[str(todo_id)])

        logger.info(f"Deleted embedding for todo {todo_id}")
        return True

    except Exception as e:
        logger.error(f"Error deleting embedding for todo {todo_id}: {str(e)}")
        return False


async def semantic_search_todos(
    query: str,
    user_id: str,
    top_k: int = 10,
    completed: Optional[bool] = None,
    priority: Optional[str] = None,
    project_id: Optional[str] = None,
    include_traditional_search: bool = True,
) -> List[TodoResponse]:
    """
    Perform semantic search on todos using ChromaDB.

    Args:
        query: The search query
        user_id: The user ID
        top_k: Maximum number of results to return
        completed: Filter by completion status
        priority: Filter by priority
        project_id: Filter by project
        include_traditional_search: Whether to fallback to traditional search if no vector results

    Returns:
        List[TodoResponse]: List of matching todos
    """
    try:
        # Get ChromaDB collection
        chroma_collection = await ChromaClient.get_langchain_client(
            collection_name="todos", create_if_not_exists=True
        )

        # Build filters using ChromaDB operators (combine into single dict)
        where_filter = {"user_id": str(user_id)}

        if completed is not None:
            where_filter["completed"] = str(
                completed
            ).lower()  # Convert to "true" or "false"

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
        for doc, score in results:
            if hasattr(doc, "metadata") and "todo_id" in doc.metadata:
                todo_ids.append(ObjectId(doc.metadata["todo_id"]))

        if not todo_ids:
            # No vector results found
            logger.info(f"No vector results for query '{query}'")
            return []

        # Fetch full todo documents from MongoDB in the order of similarity
        todos = []
        for todo_id in todo_ids:
            todo_doc = await todos_collection.find_one(
                {"_id": todo_id, "user_id": user_id}
            )
            if todo_doc:
                todos.append(TodoResponse(**serialize_document(todo_doc)))

        logger.info(f"Semantic search returned {len(todos)} todos for query '{query}'")
        return todos

    except Exception as e:
        logger.error(f"Error in semantic search for todos: {str(e)}")

        # Fallback to traditional search on error
        if include_traditional_search:
            logger.info("Falling back to traditional search due to error")
            from app.services.todos.todo_service import search_todos

            return await search_todos(query, user_id)

        return []


async def bulk_index_todos(user_id: str, batch_size: int = 100) -> int:
    """
    Bulk index all todos for a user in ChromaDB.

    Args:
        user_id: The user ID
        batch_size: Number of todos to process in each batch

    Returns:
        int: Number of todos successfully indexed
    """
    try:
        indexed_count = 0
        skip = 0

        while True:
            # Fetch batch of todos
            cursor = (
                todos_collection.find({"user_id": user_id}).skip(skip).limit(batch_size)
            )
            todos = await cursor.to_list(length=batch_size)

            if not todos:
                break

            # Index each todo
            for todo in todos:
                success = await store_todo_embedding(str(todo["_id"]), todo, user_id)
                if success:
                    indexed_count += 1

            skip += batch_size

            # Break if we got less than batch_size (last batch)
            if len(todos) < batch_size:
                break

        logger.info(f"Bulk indexed {indexed_count} todos for user {user_id}")
        return indexed_count

    except Exception as e:
        logger.error(f"Error in bulk indexing todos for user {user_id}: {str(e)}")
        return 0


async def hybrid_search_todos(
    query: str, user_id: str, top_k: int = 10, semantic_weight: float = 0.7, **filters
) -> List[TodoResponse]:
    """
    Perform hybrid search combining semantic and traditional search.

    Args:
        query: The search query
        user_id: The user ID
        top_k: Maximum number of results to return
        semantic_weight: Weight for semantic results (0.0 to 1.0)
        **filters: Additional filters (completed, priority, project_id)

    Returns:
        List[TodoResponse]: Combined and ranked results
    """
    try:
        # Get semantic results
        semantic_results = await semantic_search_todos(
            query=query,
            user_id=user_id,
            top_k=top_k,
            include_traditional_search=False,
            **filters,
        )

        # Get traditional search results
        from app.services.todos.todo_service import search_todos

        traditional_results = await search_todos(query, user_id)

        # Apply filters to traditional results
        if filters.get("completed") is not None:
            traditional_results = [
                t for t in traditional_results if t.completed == filters["completed"]
            ]
        if filters.get("priority"):
            traditional_results = [
                t for t in traditional_results if t.priority == filters["priority"]
            ]
        if filters.get("project_id"):
            traditional_results = [
                t for t in traditional_results if t.project_id == filters["project_id"]
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

        logger.info(f"Hybrid search returned {len(result)} todos for query '{query}'")
        return result

    except Exception as e:
        logger.error(f"Error in hybrid search: {str(e)}")
        # Fallback to semantic search only
        return await semantic_search_todos(query, user_id, top_k, **filters)
