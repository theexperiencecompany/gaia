import math
import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional

from app.config.loggers import todos_logger
from app.db.mongodb.collections import projects_collection, todos_collection
from app.db.redis import (
    CACHE_TTL,
    STATS_CACHE_TTL,
    delete_cache,
    delete_cache_by_pattern,
    get_cache,
    set_cache,
)
from app.db.utils import serialize_document
from app.models.todo_models import (
    BulkMoveRequest,
    BulkOperationResponse,
    BulkUpdateRequest,
    PaginationMeta,
    Priority,
    ProjectCreate,
    ProjectResponse,
    SearchMode,
    SubTask,
    TodoListResponse,
    TodoModel,
    TodoResponse,
    TodoSearchParams,
    TodoStats,
    TodoUpdateRequest,
    UpdateProjectRequest,
)
from app.models.workflow_models import (
    CreateWorkflowRequest,
    TriggerConfig,
    TriggerType,
)
from app.services.workflow.service import WorkflowService
from app.utils.todo_vector_utils import (
    bulk_index_todos,
    delete_todo_embedding,
    store_todo_embedding,
    update_todo_embedding,
)
from app.utils.todo_vector_utils import (
    hybrid_search_todos as vector_hybrid_search,
)
from app.utils.todo_vector_utils import (
    semantic_search_todos as vector_search,
)
from bson import ObjectId
from pymongo import ReturnDocument

# Special constants
INBOX_PROJECT_ID = "inbox"


class TodoService:
    """Service class for todo operations with consistent error handling and caching."""

    @staticmethod
    async def _invalidate_cache(
        user_id: str,
        project_id: Optional[str] = None,
        todo_id: Optional[str] = None,
        operation: Optional[str] = None,
    ):
        """Invalidate relevant caches based on the operation context."""
        try:
            # Always invalidate stats since they might change
            await delete_cache(f"stats:{user_id}")

            # For specific todo operations, invalidate only affected caches
            if todo_id and operation in ["update", "delete"]:
                await delete_cache(f"todo:{user_id}:{todo_id}")

                # Only invalidate list caches if the operation affects list visibility
                # (e.g., completion status change, project change, priority change)
                if operation == "delete" or operation == "update":
                    # Invalidate project-specific caches
                    if project_id:
                        await delete_cache_by_pattern(
                            f"todos:{user_id}:project:{project_id}:*"
                        )
                    # Invalidate main list cache
                    await delete_cache_by_pattern(f"todos:{user_id}:page:*")
            else:
                # For create or bulk operations, invalidate broader caches
                await delete_cache_by_pattern(f"todos:{user_id}*")
                await delete_cache_by_pattern(f"todo:{user_id}:*")

            # Project cache invalidation
            if project_id:
                await delete_cache(f"projects:{user_id}")
                await delete_cache_by_pattern(f"*:project:{project_id}*")
        except Exception as e:
            todos_logger.warning(f"Cache invalidation failed: {str(e)}")

    @staticmethod
    async def _get_or_create_inbox(user_id: str) -> str:
        """Get or create the default inbox project for a user."""
        existing = await projects_collection.find_one(
            {"user_id": user_id, "is_default": True}
        )

        if existing:
            return str(existing["_id"])

        inbox = {
            "user_id": user_id,
            "name": "Inbox",
            "description": "Default project for new todos",
            "color": "#6B7280",
            "is_default": True,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        result = await projects_collection.insert_one(inbox)
        return str(result.inserted_id)

    @staticmethod
    async def _build_query(user_id: str, params: TodoSearchParams) -> dict[str, Any]:
        """Build MongoDB query from search parameters."""
        query: dict[str, Any] = {"user_id": user_id}

        # Text search
        if params.q and params.mode == SearchMode.TEXT:
            query["$or"] = [
                {"title": {"$regex": params.q, "$options": "i"}},
                {"description": {"$regex": params.q, "$options": "i"}},
                {"labels": {"$in": [params.q]}},
            ]

        # Filters
        if params.project_id is not None:
            query["project_id"] = params.project_id
        elif (
            not params.q
            and params.completed is None
            and not params.priority
            and not params.labels
        ):
            # Default to inbox when no filters are specified (main /todos page)
            inbox_id = await TodoService._get_or_create_inbox(user_id)
            query["project_id"] = inbox_id

        if params.completed is not None:
            query["completed"] = params.completed
        if params.priority:
            query["priority"] = params.priority.value
        if params.labels:
            query["labels"] = {"$in": params.labels}

        # Date filters
        if params.has_due_date is True:
            query["due_date"] = {"$ne": None}
        elif params.has_due_date is False:
            query["due_date"] = None

        if params.due_date_start or params.due_date_end:
            date_query = {}
            if params.due_date_start:
                date_query["$gte"] = params.due_date_start
            if params.due_date_end:
                date_query["$lte"] = params.due_date_end
            query["due_date"] = date_query

        # Overdue filter
        if params.overdue is True:
            query["due_date"] = {"$lt": datetime.now(timezone.utc)}
            query["completed"] = False
        elif params.overdue is False and params.has_due_date is not False:
            query["$or"] = [
                {"due_date": None},
                {"due_date": {"$gte": datetime.now(timezone.utc)}},
            ]

        return query

    @staticmethod
    async def _calculate_stats(user_id: str) -> TodoStats:
        """Calculate todo statistics for a user."""
        cache_key = f"stats:{user_id}"
        cached = await get_cache(cache_key)
        if cached:
            return TodoStats(**cached)

        # Use aggregation pipeline for efficient calculation
        pipeline = [
            {"$match": {"user_id": user_id}},
            {
                "$facet": {
                    "total": [{"$count": "count"}],
                    "completed": [{"$match": {"completed": True}}, {"$count": "count"}],
                    "overdue": [
                        {
                            "$match": {
                                "completed": False,
                                "due_date": {"$lt": datetime.now(timezone.utc)},
                            }
                        },
                        {"$count": "count"},
                    ],
                    "by_priority": [
                        {"$group": {"_id": "$priority", "count": {"$sum": 1}}}
                    ],
                    "by_project": [
                        {"$group": {"_id": "$project_id", "count": {"$sum": 1}}}
                    ],
                    "labels": [
                        {
                            "$match": {"completed": False}
                        },  # Only count labels from non-completed todos
                        {"$unwind": "$labels"},
                        {"$group": {"_id": "$labels", "count": {"$sum": 1}}},
                        {"$sort": {"count": -1}},
                        {"$limit": 50},  # Limit to top 50 labels
                    ],
                }
            },
        ]

        result = await todos_collection.aggregate(pipeline).to_list(1)
        if not result:
            return TodoStats()

        facets = result[0]
        total = facets["total"][0]["count"] if facets["total"] else 0
        completed = facets["completed"][0]["count"] if facets["completed"] else 0
        overdue = facets["overdue"][0]["count"] if facets["overdue"] else 0

        by_priority = {item["_id"]: item["count"] for item in facets["by_priority"]}
        by_project = {item["_id"]: item["count"] for item in facets["by_project"]}

        stats = TodoStats(
            total=total,
            completed=completed,
            pending=total - completed,
            overdue=overdue,
            by_priority=by_priority,
            by_project=by_project,
            completion_rate=round((completed / total * 100) if total > 0 else 0, 2),
        )

        # Add labels if available
        if "labels" in facets:
            stats.labels = [
                {"name": item["_id"], "count": item["count"]}
                for item in facets["labels"]
            ]

        await set_cache(cache_key, stats.model_dump(), STATS_CACHE_TTL)
        return stats

    # CRUD Operations
    @classmethod
    async def create_todo(cls, todo: TodoModel, user_id: str) -> TodoResponse:
        """Create a new todo with automatic inbox assignment."""
        # Ensure project exists or use inbox
        if not todo.project_id:
            todo.project_id = await cls._get_or_create_inbox(user_id)
        else:
            project = await projects_collection.find_one(
                {"_id": ObjectId(todo.project_id), "user_id": user_id}
            )
            if not project:
                raise ValueError(f"Project {todo.project_id} not found")

        todo_dict = todo.model_dump()

        # Handle subtasks: ensure they have IDs
        if todo.subtasks:
            todo_dict["subtasks"] = [
                subtask.model_dump() if isinstance(subtask, SubTask) else subtask
                for subtask in todo.subtasks
            ]
            for subtask in todo_dict["subtasks"]:
                if not subtask.get("id"):
                    subtask["id"] = str(uuid.uuid4())
        else:
            todo_dict["subtasks"] = []

        todo_dict.update(
            {
                "user_id": user_id,
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
                "completed": False,
                "workflow_activated": True,  # Start activated by default
            }
        )

        result = await todos_collection.insert_one(todo_dict)
        created_todo = await todos_collection.find_one({"_id": result.inserted_id})

        # Create standalone workflow instead of queuing embedded workflow generation
        try:
            # Create workflow using standalone workflow system
            workflow_request = CreateWorkflowRequest(
                title=f"Todo: {todo.title}",
                description=todo.description or f"Workflow for todo: {todo.title}",
                trigger_config=TriggerConfig(type=TriggerType.MANUAL, enabled=True),
                generate_immediately=False,  # Generate in background
            )

            workflow = await WorkflowService.create_workflow(workflow_request, user_id)

            # Update the todo with the workflow_id
            await todos_collection.update_one(
                {"_id": result.inserted_id}, {"$set": {"workflow_id": workflow.id}}
            )

            todos_logger.info(
                f"Created standalone workflow {workflow.id} for todo '{todo.title}' (ID: {result.inserted_id})"
            )
        except Exception as e:
            todos_logger.warning(
                f"Failed to create workflow for todo '{todo.title}': {str(e)}"
            )

        # Index for search
        try:
            if created_todo:
                await store_todo_embedding(
                    str(result.inserted_id), created_todo, user_id
                )
        except Exception as e:
            todos_logger.warning(f"Failed to index todo: {str(e)}")

        await cls._invalidate_cache(
            user_id, todo.project_id, str(result.inserted_id), "create"
        )

        # Return todo response without workflow (will be generated in background)
        if not created_todo:
            raise ValueError("Failed to create todo")
        todo_response_data = serialize_document(created_todo)
        return TodoResponse(**todo_response_data)

    @classmethod
    async def get_todo(cls, todo_id: str, user_id: str) -> TodoResponse:
        """Get a single todo by ID."""
        # Try cache first
        cache_key = f"todo:{user_id}:{todo_id}"
        cached = await get_cache(cache_key)
        if cached:
            return TodoResponse(**cached)

        todo = await todos_collection.find_one(
            {"_id": ObjectId(todo_id), "user_id": user_id}
        )

        if not todo:
            raise ValueError(f"Todo {todo_id} not found")

        response = TodoResponse(**serialize_document(todo))

        # Cache the response
        await set_cache(cache_key, response.model_dump(), CACHE_TTL)

        return response

    @classmethod
    async def list_todos(
        cls, user_id: str, params: TodoSearchParams
    ) -> TodoListResponse:
        """List todos with filtering, pagination, and optional stats."""
        # Handle search modes
        if params.q and params.mode in [SearchMode.SEMANTIC, SearchMode.HYBRID]:
            return await cls._search_todos(user_id, params)

        # Generate cache key for this specific query
        cache_key_parts = [f"todos:{user_id}"]
        if params.project_id:
            cache_key_parts.append(f"project:{params.project_id}")
        if params.completed is not None:
            cache_key_parts.append(f"completed:{params.completed}")
        if params.priority:
            cache_key_parts.append(f"priority:{params.priority.value}")
        cache_key_parts.append(f"page:{params.page}")
        cache_key = ":".join(cache_key_parts)

        # Try to get from cache
        cached_response = await get_cache(cache_key)
        if cached_response and not params.include_stats:
            return TodoListResponse(**cached_response)

        # Build query
        query = await cls._build_query(user_id, params)

        # Count total
        total = await todos_collection.count_documents(query)

        # Calculate pagination
        skip = (params.page - 1) * params.per_page
        pages = math.ceil(total / params.per_page)

        # Fetch todos
        cursor = todos_collection.find(query).sort("created_at", -1)
        cursor = cursor.skip(skip).limit(params.per_page)
        todos = await cursor.to_list(params.per_page)

        # Build response
        data = [TodoResponse(**serialize_document(todo)) for todo in todos]
        meta = PaginationMeta(
            total=total,
            page=params.page,
            per_page=params.per_page,
            pages=pages,
            has_next=params.page < pages,
            has_prev=params.page > 1,
        )

        response = TodoListResponse(data=data, meta=meta)

        # Cache the response (without stats)
        if not params.include_stats:
            await set_cache(cache_key, response.model_dump(), CACHE_TTL)

        # Include stats if requested
        if params.include_stats:
            response.stats = await cls._calculate_stats(user_id)

        return response

    @classmethod
    async def update_todo(
        cls, todo_id: str, updates: TodoUpdateRequest, user_id: str
    ) -> TodoResponse:
        """Update a todo."""
        # Prepare updates
        update_dict = {k: v for k, v in updates.model_dump().items() if v is not None}

        # Validate project if changing
        if "project_id" in update_dict:
            project = await projects_collection.find_one(
                {"_id": ObjectId(update_dict["project_id"]), "user_id": user_id}
            )
            if not project:
                raise ValueError(f"Project {update_dict['project_id']} not found")

        # Handle subtasks
        if "subtasks" in update_dict:
            update_dict["subtasks"] = [
                subtask.model_dump() if isinstance(subtask, SubTask) else subtask
                for subtask in update_dict["subtasks"]
            ]
            for subtask in update_dict["subtasks"]:
                if not subtask.get("id"):
                    subtask["id"] = str(uuid.uuid4())

        update_dict["updated_at"] = datetime.now(timezone.utc)

        # Update and return - this also verifies ownership atomically
        updated = await todos_collection.find_one_and_update(
            {"_id": ObjectId(todo_id), "user_id": user_id},
            {"$set": update_dict},
            return_document=ReturnDocument.AFTER,
        )

        # If todo not found, updated will be None
        if not updated:
            raise ValueError(f"Todo {todo_id} not found")

        # Update search index
        try:
            await update_todo_embedding(todo_id, updated, user_id)
        except Exception as e:
            todos_logger.warning(f"Failed to update index: {str(e)}")

        # Sync subtask changes back to goals if this is a goal-related todo
        if "subtasks" in update_dict:
            try:
                # Get the original subtasks to compare
                # Note: We need the old state for comparison, but we optimized away the pre-fetch
                # For subtask sync, we'll need to check if completion changed
                for new_subtask_dict in update_dict["subtasks"]:
                    new_subtask_id = new_subtask_dict.get("id")
                    new_completed = new_subtask_dict.get("completed", False)

                    if not new_subtask_id:
                        continue  # Skip subtasks without IDs

                    # Since we don't have the old state anymore, we sync all subtasks
                    # The sync service will handle checking if state actually changed
                    from app.services.todos.sync_service import (
                        sync_subtask_to_goal_completion,
                    )

                    await sync_subtask_to_goal_completion(
                        todo_id, new_subtask_id, new_completed, user_id
                    )
            except Exception as e:
                todos_logger.warning(
                    f"Failed to sync subtask completion to goal: {str(e)}"
                )

        # Determine if this update affects list visibility
        affects_visibility = any(
            [
                "completed" in update_dict,
                "project_id" in update_dict,
                "priority" in update_dict,
                "due_date" in update_dict,
                "labels" in update_dict,
            ]
        )

        await cls._invalidate_cache(
            user_id,
            updated.get("project_id"),
            todo_id,
            "update" if affects_visibility else "update_minor",
        )

        return TodoResponse(**serialize_document(updated))

    @classmethod
    async def delete_todo(cls, todo_id: str, user_id: str) -> None:
        """Delete a todo."""
        # Single atomic delete with ownership verification
        result = await todos_collection.delete_one(
            {"_id": ObjectId(todo_id), "user_id": user_id}
        )

        if result.deleted_count == 0:
            raise ValueError(f"Todo {todo_id} not found")

        # Remove from search index
        try:
            await delete_todo_embedding(todo_id)
        except Exception as e:
            todos_logger.warning(f"Failed to remove from index: {str(e)}")

        # Invalidate cache broadly since we don't know the project_id
        await cls._invalidate_cache(user_id, None, todo_id, "delete")

    # Bulk Operations
    @classmethod
    async def bulk_update_todos(
        cls, request: BulkUpdateRequest, user_id: str
    ) -> BulkOperationResponse:
        """Bulk update multiple todos."""
        # Prepare updates - only include non-None fields
        update_dict = {
            k: v for k, v in request.updates.model_dump().items() if v is not None
        }

        if not update_dict:
            return BulkOperationResponse(
                success=[],
                failed=[],
                total=len(request.todo_ids),
                message="No updates provided",
            )

        # Validate project if changing
        if "project_id" in update_dict:
            project = await projects_collection.find_one(
                {"_id": ObjectId(update_dict["project_id"]), "user_id": user_id}
            )
            if not project:
                raise ValueError(f"Project {update_dict['project_id']} not found")

        # Handle subtasks conversion
        if "subtasks" in update_dict:
            update_dict["subtasks"] = [
                subtask.model_dump() if isinstance(subtask, SubTask) else subtask
                for subtask in update_dict["subtasks"]
            ]
            for subtask in update_dict["subtasks"]:
                if not subtask.get("id"):
                    subtask["id"] = str(uuid.uuid4())

        update_dict["updated_at"] = datetime.now(timezone.utc)

        # Single atomic update operation for all todos
        result = await todos_collection.update_many(
            {
                "_id": {"$in": [ObjectId(tid) for tid in request.todo_ids]},
                "user_id": user_id,
            },
            {"$set": update_dict},
        )

        # Update search index for modified todos
        if result.modified_count > 0:
            try:
                # Fetch updated todos to reindex
                updated_todos = await todos_collection.find(
                    {
                        "_id": {"$in": [ObjectId(tid) for tid in request.todo_ids]},
                        "user_id": user_id,
                    }
                ).to_list(None)

                for todo in updated_todos:
                    try:
                        await update_todo_embedding(str(todo["_id"]), todo, user_id)
                    except Exception as e:
                        todos_logger.warning(
                            f"Failed to update index for todo {todo['_id']}: {str(e)}"
                        )
            except Exception as e:
                todos_logger.warning(f"Failed to update search index: {str(e)}")

        await cls._invalidate_cache(user_id, operation="bulk_update")

        return BulkOperationResponse(
            success=request.todo_ids[: result.modified_count],  # Approximation
            failed=[],
            total=len(request.todo_ids),
            message=f"Updated {result.modified_count} todos",
        )

    @classmethod
    async def bulk_delete_todos(
        cls, todo_ids: List[str], user_id: str
    ) -> BulkOperationResponse:
        """Bulk delete multiple todos."""
        # Get todos before deletion for cleanup operations
        todos_to_delete = await todos_collection.find(
            {
                "_id": {"$in": [ObjectId(tid) for tid in todo_ids]},
                "user_id": user_id,
            }
        ).to_list(None)

        # Single atomic delete operation for all todos
        result = await todos_collection.delete_many(
            {
                "_id": {"$in": [ObjectId(tid) for tid in todo_ids]},
                "user_id": user_id,
            }
        )

        # Remove from search index
        if result.deleted_count > 0:
            try:
                for todo in todos_to_delete:
                    try:
                        await delete_todo_embedding(str(todo["_id"]))
                    except Exception as e:
                        todos_logger.warning(
                            f"Failed to remove todo {todo['_id']} from index: {str(e)}"
                        )
            except Exception as e:
                todos_logger.warning(f"Failed to cleanup search index: {str(e)}")

        return BulkOperationResponse(
            success=todo_ids[: result.deleted_count],  # Approximation
            failed=[],
            total=len(todo_ids),
            message=f"Deleted {result.deleted_count} todos",
        )

    @classmethod
    async def bulk_move_todos(
        cls, request: BulkMoveRequest, user_id: str
    ) -> BulkOperationResponse:
        """Bulk move todos to another project."""
        # Verify project exists
        project = await projects_collection.find_one(
            {"_id": ObjectId(request.project_id), "user_id": user_id}
        )

        if not project:
            raise ValueError(f"Project {request.project_id} not found")

        result = await todos_collection.update_many(
            {
                "_id": {"$in": [ObjectId(tid) for tid in request.todo_ids]},
                "user_id": user_id,
            },
            {
                "$set": {
                    "project_id": request.project_id,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )

        await cls._invalidate_cache(
            user_id, project_id=request.project_id, operation="bulk_move"
        )

        return BulkOperationResponse(
            success=request.todo_ids if result.modified_count > 0 else [],
            failed=[],
            total=len(request.todo_ids),
            message=f"Moved {result.modified_count} todos",
        )

    # Search Operations
    @classmethod
    async def _search_todos(
        cls, user_id: str, params: TodoSearchParams
    ) -> TodoListResponse:
        """Perform semantic or hybrid search."""
        if not params.q:
            # No query provided, return empty results
            return TodoListResponse(
                data=[],
                meta=PaginationMeta(
                    total=0,
                    page=params.page,
                    per_page=params.per_page,
                    pages=0,
                    has_next=False,
                    has_prev=False,
                ),
            )

        if params.mode == SearchMode.SEMANTIC:
            results = await vector_search(
                query=params.q,
                user_id=user_id,
                top_k=params.per_page * params.page,  # Get enough for pagination
                completed=params.completed,
                priority=params.priority.value if params.priority else None,
                project_id=params.project_id,
                include_traditional_search=False,
            )
        else:  # HYBRID
            results = await vector_hybrid_search(
                query=params.q,
                user_id=user_id,
                top_k=params.per_page * params.page,
                semantic_weight=0.7,
                completed=params.completed,
                priority=params.priority.value if params.priority else None,
                project_id=params.project_id,
            )

        # Apply pagination to results
        total = len(results)
        start = (params.page - 1) * params.per_page
        end = start + params.per_page
        paginated_results = results[start:end]

        pages = math.ceil(total / params.per_page)
        meta = PaginationMeta(
            total=total,
            page=params.page,
            per_page=params.per_page,
            pages=pages,
            has_next=params.page < pages,
            has_prev=params.page > 1,
        )

        response = TodoListResponse(data=paginated_results, meta=meta)

        if params.include_stats:
            response.stats = await cls._calculate_stats(user_id)

        return response

    @classmethod
    async def reindex_todos(cls, user_id: str, batch_size: int = 100) -> dict:
        """Reindex all todos for vector search."""
        indexed = await bulk_index_todos(user_id, batch_size)
        return {"indexed": indexed, "user_id": user_id, "status": "completed"}


# Project Operations (kept separate as they're less complex)
class ProjectService:
    """Service for project operations."""

    @staticmethod
    async def create_project(project: ProjectCreate, user_id: str) -> ProjectResponse:
        """Create a new project."""
        # Ensure user has inbox
        await TodoService._get_or_create_inbox(user_id)

        project_dict = project.model_dump()
        project_dict.update(
            {
                "user_id": user_id,
                "is_default": False,
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            }
        )

        result = await projects_collection.insert_one(project_dict)
        created = await projects_collection.find_one({"_id": result.inserted_id})

        if not created:
            raise ValueError("Failed to create project")

        # Get todo count
        todo_count = await todos_collection.count_documents(
            {"user_id": user_id, "project_id": str(result.inserted_id)}
        )

        await TodoService._invalidate_cache(
            user_id, project_id=str(result.inserted_id), operation="project_create"
        )

        return ProjectResponse(**serialize_document(created), todo_count=todo_count)

    @staticmethod
    async def list_projects(user_id: str) -> List[ProjectResponse]:
        """List all projects with todo counts."""
        # Try cache first
        cache_key = f"projects:{user_id}"
        cached = await get_cache(cache_key)
        if cached:
            return [ProjectResponse(**project) for project in cached]

        # Ensure inbox exists
        await TodoService._get_or_create_inbox(user_id)

        # Aggregation to get projects with counts
        pipeline = [
            {"$match": {"user_id": user_id}},
            {"$sort": {"created_at": -1}},
            {
                "$lookup": {
                    "from": "todos",
                    "let": {"project_id": {"$toString": "$_id"}},
                    "pipeline": [
                        {
                            "$match": {
                                "$expr": {
                                    "$and": [
                                        {"$eq": ["$user_id", user_id]},
                                        {"$eq": ["$project_id", "$$project_id"]},
                                    ]
                                }
                            }
                        },
                        {"$count": "count"},
                    ],
                    "as": "todo_stats",
                }
            },
            {
                "$addFields": {
                    "todo_count": {"$ifNull": [{"$first": "$todo_stats.count"}, 0]}
                }
            },
        ]

        projects = await projects_collection.aggregate(pipeline).to_list(None)
        response = [
            ProjectResponse(**serialize_document(project)) for project in projects
        ]

        # Cache the response
        await set_cache(cache_key, [p.model_dump() for p in response], CACHE_TTL)

        return response

    @staticmethod
    async def update_project(
        project_id: str, updates: UpdateProjectRequest, user_id: str
    ) -> ProjectResponse:
        """Update a project."""
        existing = await projects_collection.find_one(
            {"_id": ObjectId(project_id), "user_id": user_id}
        )

        if not existing:
            raise ValueError(f"Project {project_id} not found")

        if existing.get("is_default"):
            raise ValueError("Cannot update default Inbox project")

        update_dict = {k: v for k, v in updates.model_dump().items() if v is not None}
        update_dict["updated_at"] = datetime.now(timezone.utc)

        updated = await projects_collection.find_one_and_update(
            {"_id": ObjectId(project_id)},
            {"$set": update_dict},
            return_document=ReturnDocument.AFTER,
        )

        # Get todo count
        todo_count = await todos_collection.count_documents(
            {"user_id": user_id, "project_id": project_id}
        )

        await TodoService._invalidate_cache(
            user_id, project_id=project_id, operation="project_update"
        )

        return ProjectResponse(**serialize_document(updated), todo_count=todo_count)

    @staticmethod
    async def delete_project(project_id: str, user_id: str) -> None:
        """Delete a project and move todos to inbox."""
        project = await projects_collection.find_one(
            {"_id": ObjectId(project_id), "user_id": user_id}
        )

        if not project:
            raise ValueError(f"Project {project_id} not found")

        if project.get("is_default"):
            raise ValueError("Cannot delete default Inbox project")

        # Move todos to inbox
        inbox_id = await TodoService._get_or_create_inbox(user_id)
        await todos_collection.update_many(
            {"user_id": user_id, "project_id": project_id},
            {
                "$set": {
                    "project_id": inbox_id,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )

        # Delete project
        await projects_collection.delete_one({"_id": ObjectId(project_id)})

        await TodoService._invalidate_cache(
            user_id, project_id=project_id, operation="project_delete"
        )


# Compatibility functions for old API
async def create_todo(todo: TodoModel, user_id: str) -> TodoResponse:
    """Compatibility wrapper for old create_todo function."""
    return await TodoService.create_todo(todo, user_id)


async def get_todo(todo_id: str, user_id: str) -> TodoResponse:
    """Compatibility wrapper for old get_todo function."""
    return await TodoService.get_todo(todo_id, user_id)


async def get_all_todos(
    user_id: str,
    project_id=None,
    completed=None,
    priority=None,
    has_due_date=None,
    overdue=None,
    skip=0,
    limit=50,
) -> List[TodoResponse]:
    """Compatibility wrapper for old get_all_todos function."""

    params = TodoSearchParams(
        q=None,
        mode=SearchMode.TEXT,
        project_id=project_id,
        completed=completed,
        priority=Priority(priority) if priority else None,
        has_due_date=has_due_date,
        overdue=overdue,
        page=(skip // limit) + 1 if limit > 0 else 1,
        per_page=limit,
        include_stats=False,
    )

    response = await TodoService.list_todos(user_id, params)
    return response.data


async def update_todo(
    todo_id: str, updates: TodoUpdateRequest, user_id: str
) -> TodoResponse:
    """Compatibility wrapper for old update_todo function."""
    return await TodoService.update_todo(todo_id, updates, user_id)


async def delete_todo(todo_id: str, user_id: str) -> None:
    """Compatibility wrapper for old delete_todo function."""
    await TodoService.delete_todo(todo_id, user_id)


async def create_project(project: ProjectCreate, user_id: str) -> ProjectResponse:
    """Compatibility wrapper for old create_project function."""
    return await ProjectService.create_project(project, user_id)


async def get_all_projects(user_id: str) -> List[ProjectResponse]:
    """Compatibility wrapper for old get_all_projects function."""
    return await ProjectService.list_projects(user_id)


async def update_project(
    project_id: str, updates: UpdateProjectRequest, user_id: str
) -> ProjectResponse:
    """Compatibility wrapper for old update_project function."""
    return await ProjectService.update_project(project_id, updates, user_id)


async def delete_project(project_id: str, user_id: str) -> None:
    """Compatibility wrapper for old delete_project function."""
    await ProjectService.delete_project(project_id, user_id)


async def search_todos(
    query: str,
    user_id: str,
    completed: Optional[bool] = None,
    priority: Optional[str] = None,
    project_id: Optional[str] = None,
) -> List[TodoResponse]:
    """Compatibility wrapper for old search_todos function."""
    params = TodoSearchParams(
        q=query,
        mode=SearchMode.TEXT,
        project_id=project_id,
        completed=completed,
        priority=Priority(priority) if priority else None,
        page=1,
        per_page=100,
        include_stats=False,
    )

    response = await TodoService.list_todos(user_id, params)
    return response.data


# Additional compatibility functions that might be used elsewhere
async def get_todo_stats(user_id: str) -> dict:
    """Get statistics about user's todos."""
    stats = await TodoService._calculate_stats(user_id)
    return stats.model_dump()


async def get_todos_by_date_range(
    user_id: str, start_date: datetime, end_date: datetime
) -> List[TodoResponse]:
    """Get todos within a date range."""
    params = TodoSearchParams(
        q=None,
        mode=SearchMode.TEXT,
        due_date_start=start_date,
        due_date_end=end_date,
        completed=False,
        page=1,
        per_page=1000,
        include_stats=False,
    )

    response = await TodoService.list_todos(user_id, params)
    return response.data


async def get_all_labels(user_id: str) -> List[dict]:
    """Get all unique labels used by the user with counts."""
    # Get stats which includes label info
    stats = await TodoService._calculate_stats(user_id)

    # Return labels from stats if available
    if hasattr(stats, "labels") and stats.labels:
        return stats.labels

    return []


async def get_todos_by_label(user_id: str, label: str) -> List[TodoResponse]:
    """Get all todos that have a specific label."""
    params = TodoSearchParams(
        q=None,
        mode=SearchMode.TEXT,
        labels=[label],
        page=1,
        per_page=1000,
        include_stats=False,
    )

    response = await TodoService.list_todos(user_id, params)
    return response.data


async def semantic_search_todos(
    query: str,
    user_id: str,
    limit: int = 20,
    project_id: Optional[str] = None,
    completed: Optional[bool] = None,
    priority: Optional[str] = None,
) -> List[TodoResponse]:
    """Perform semantic search on todos."""
    params = TodoSearchParams(
        q=query,
        mode=SearchMode.SEMANTIC,
        project_id=project_id,
        completed=completed,
        priority=Priority(priority) if priority else None,
        page=1,
        per_page=limit,
        include_stats=False,
    )

    response = await TodoService.list_todos(user_id, params)
    return response.data


async def hybrid_search_todos(
    query: str,
    user_id: str,
    limit: int = 20,
    project_id: Optional[str] = None,
    completed: Optional[bool] = None,
    priority: Optional[str] = None,
    semantic_weight: float = 0.7,
) -> List[TodoResponse]:
    """Perform hybrid search on todos."""
    params = TodoSearchParams(
        q=query,
        mode=SearchMode.HYBRID,
        project_id=project_id,
        completed=completed,
        priority=Priority(priority) if priority else None,
        page=1,
        per_page=limit,
        include_stats=False,
    )

    response = await TodoService.list_todos(user_id, params)
    return response.data


async def bulk_index_existing_todos(user_id: str, batch_size: int = 100) -> dict:
    """Bulk index all existing todos for a user."""
    return await TodoService.reindex_todos(user_id, batch_size)
