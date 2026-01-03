CREATE_TODO = """
    Create a new todo item with optional details.

    This tool creates a new task in the user's todo list with support for various
    attributes like priority, due date, labels, and project assignment.

    When to use:
    - When user asks to create a new task or todo
    - When adding items to a specific project
    - When setting reminders with due dates
    - When organizing tasks with labels/tags
    - When creating tasks with priority levels

    Input:
    - title: Required, the task title (1-200 characters)
    - description: Optional, detailed description (up to 2000 characters)
    - labels: Optional list of tags for categorization (max 10)
    - due_date: Optional, when the task should be completed (datetime)
    - due_date_timezone: Optional, timezone for the due date
    - priority: Optional, task priority (high/medium/low/none)
    - project_id: Optional, assign to specific project (defaults to Inbox)

    Output:
    - TodoResponse with created task details including ID
    - Error message if creation fails

    Note: If no project is specified, the task is added to the default Inbox.
    """

LIST_TODOS = """
    Retrieve todos with flexible filtering options.

    This tool fetches todos with support for filtering by project, completion status,
    priority, due dates, and more. Supports pagination for large lists.

    When to use:
    - When user wants to see their tasks/todos
    - When checking tasks for a specific project
    - When filtering by completion status or priority
    - When looking for overdue tasks
    - When user asks about their todo list or tasks

    Input:
    - project_id: Optional, filter by specific project
    - completed: Optional boolean, filter by completion status
    - priority: Optional, filter by priority level
    - has_due_date: Optional boolean, filter tasks with/without due dates
    - overdue: Optional boolean, get overdue uncompleted tasks
    - skip: Optional, pagination offset (default: 0)
    - limit: Optional, max results (default: 50, max: 100)

    Output:
    - List of TodoResponse objects matching filters
    - Empty list if no todos match
    - Error message if retrieval fails

    Note: Results are sorted by creation date (newest first).
    """

UPDATE_TODO = """
    Update an existing todo item.

    This tool modifies any attribute of an existing todo, including marking as
    complete, changing priority, updating due dates, or moving between projects.

    When to use:
    - When marking tasks as complete/incomplete
    - When changing task priority or due date
    - When moving tasks between projects
    - When updating task details or descriptions
    - When modifying labels or subtasks

    Input:
    - todo_id: Required, the ID of the todo to update
    - title: Optional, new title
    - description: Optional, new description
    - labels: Optional, new list of labels
    - due_date: Optional, new due date
    - due_date_timezone: Optional, new timezone
    - priority: Optional, new priority level
    - project_id: Optional, move to different project
    - completed: Optional boolean, mark complete/incomplete
    - subtasks: Optional, update subtask list

    Output:
    - Updated TodoResponse with new values
    - Error if todo not found or update fails

    Note: Only provided fields are updated; others remain unchanged.
    """

DELETE_TODO = """
    Delete a todo item permanently.

    This tool removes a todo from the user's list. This action cannot be undone.

    When to use:
    - When user explicitly asks to delete/remove a task
    - When cleaning up completed or obsolete tasks
    - When user wants to permanently remove a todo

    Input:
    - todo_id: Required, the ID of the todo to delete

    Output:
    - Success confirmation (no content returned)
    - Error if todo not found or deletion fails

    Warning: This permanently deletes the todo and all its subtasks.
    """

SEARCH_TODOS = """
    Search todos by title, description, or labels.

    This tool performs text search across todo items to find tasks matching
    the search query. Useful for finding specific tasks quickly.

    When to use:
    - When user searches for tasks by keyword
    - When looking for todos with specific text
    - When finding tasks by label names
    - When user can't remember exact task details

    Input:
    - query: Required, search text to match against todos

    Output:
    - List of TodoResponse objects matching the search
    - Empty list if no matches found
    - Error if search fails

    Note: Search is case-insensitive and matches partial text.
    """

GET_TODO_STATS = """
    Get statistics about user's todos.

    This tool provides an overview of todo metrics including counts by status,
    priority distribution, and project breakdown.

    When to use:
    - When user asks for todo statistics or overview
    - When providing productivity insights
    - When user wants to know task completion rates
    - When summarizing todo list status

    Output:
    - Dictionary with statistics including:
      - Total todo count
      - Completed vs pending counts
      - Priority distribution
      - Project-wise breakdown
      - Overdue task count
    - Error if statistics retrieval fails

    Note: Useful for productivity tracking and overview dashboards.
    """

GET_TODAY_TODOS = """
    Get todos due today.

    This tool retrieves all tasks scheduled for the current day, helping users
    focus on immediate priorities.

    When to use:
    - When user asks "What's on my plate today?"
    - When showing daily task list
    - When user wants to see today's agenda
    - For daily planning or review

    Output:
    - List of TodoResponse objects due today
    - Empty list if no todos due today
    - Error if retrieval fails

    Note: Uses user's timezone if specified in todos.
    """

GET_UPCOMING_TODOS = """
    Get todos due in the upcoming days.

    This tool fetches tasks due within a specified number of days, useful for
    planning and reviewing upcoming work.

    When to use:
    - When user wants to see upcoming tasks
    - When planning for the week ahead
    - When reviewing future deadlines
    - When user asks about upcoming todos

    Input:
    - days: Optional, number of days to look ahead (default: 7)

    Output:
    - List of TodoResponse objects due within the period
    - Empty list if no upcoming todos
    - Error if retrieval fails

    Note: Helps with forward planning and deadline awareness.
    """

CREATE_PROJECT = """
    Create a new project for organizing todos.

    This tool creates a project container for grouping related tasks, with
    customizable name, description, and color coding.

    When to use:
    - When user wants to create a new project/category
    - When organizing todos into groups
    - When starting a new initiative or area
    - When user needs better task organization

    Input:
    - name: Required, project name (1-100 characters)
    - description: Optional, project description (up to 500 chars)
    - color: Optional, hex color code (e.g., #FF5733)

    Output:
    - ProjectResponse with created project details
    - Error if project creation fails

    Note: Each user has a default "Inbox" project that cannot be deleted.
    """

LIST_PROJECTS = """
    Get all projects for the current user.

    This tool retrieves all project containers used for organizing todos,
    including the default Inbox and any custom projects.

    When to use:
    - When user wants to see all projects
    - Before assigning todos to projects
    - When organizing task structure
    - When user asks about available projects/categories

    Output:
    - List of ProjectResponse objects with todo counts
    - Always includes at least the Inbox project
    - Error if retrieval fails

    Note: Projects show todo count for quick overview.
    """

UPDATE_PROJECT = """
    Update an existing project.

    This tool modifies project properties like name, description, or color.
    Useful for reorganizing or rebranding project containers.

    When to use:
    - When renaming projects
    - When updating project descriptions
    - When changing project colors
    - When refining project organization

    Input:
    - project_id: Required, ID of project to update
    - name: Optional, new project name
    - description: Optional, new description
    - color: Optional, new hex color code

    Output:
    - Updated ProjectResponse with new values
    - Error if project not found or update fails

    Note: Cannot update the default Inbox project name.
    """

DELETE_PROJECT = """
    Delete a project and move its todos to Inbox.

    This tool removes a project container. All todos in the deleted project
    are automatically moved to the default Inbox to prevent data loss.

    When to use:
    - When user wants to delete/remove a project
    - When consolidating projects
    - When cleaning up unused projects

    Input:
    - project_id: Required, ID of project to delete

    Output:
    - Success confirmation (no content)
    - Error if project not found or is default Inbox

    Warning: Cannot delete the default Inbox project. Todos are preserved.
    """

GET_TODOS_BY_LABEL = """
    Get all todos with a specific label.

    This tool filters todos by a single label/tag, useful for cross-project
    task organization and thematic grouping.

    When to use:
    - When user wants tasks with a specific tag
    - When filtering by context or category
    - When viewing todos across projects by theme
    - When user mentions a specific label

    Input:
    - label: Required, the label to filter by

    Output:
    - List of TodoResponse objects with the specified label
    - Empty list if no todos have the label
    - Error if retrieval fails

    Note: Label search is case-sensitive.
    """

GET_ALL_LABELS = """
    Get all unique labels used across todos.

    This tool retrieves a list of all labels/tags in use, with counts showing
    how many todos use each label. Useful for tag management and overview.

    When to use:
    - When user wants to see all available tags
    - When organizing or consolidating labels
    - When getting an overview of categorization
    - Before applying labels to new todos

    Output:
    - List of label objects with name and usage count
    - Empty list if no labels exist
    - Error if retrieval fails

    Note: Helps identify duplicate or similar labels for cleanup.
    """

BULK_COMPLETE_TODOS = """
    Mark multiple todos as completed at once.

    This tool efficiently completes multiple tasks in a single operation,
    useful for bulk task management and cleanup.

    When to use:
    - When user wants to complete multiple tasks
    - When marking a group of tasks as done
    - When clearing completed project phases
    - For bulk task status updates

    Input:
    - todo_ids: Required, list of todo IDs to complete

    Output:
    - List of updated TodoResponse objects
    - Error if any todo not found or update fails

    Note: More efficient than individual updates for multiple todos.
    """

BULK_MOVE_TODOS = """
    Move multiple todos to a different project.

    This tool relocates multiple tasks to a new project in one operation,
    useful for reorganizing task structure.

    When to use:
    - When reorganizing todos between projects
    - When moving related tasks together
    - When consolidating project structures
    - For bulk project reassignment

    Input:
    - todo_ids: Required, list of todo IDs to move
    - project_id: Required, target project ID

    Output:
    - List of updated TodoResponse objects in new project
    - Error if any todo or project not found

    Note: Validates project exists before moving todos.
    """

BULK_DELETE_TODOS = """
    Delete multiple todos permanently.

    This tool removes multiple tasks in a single operation. This action
    cannot be undone and should be used carefully.

    When to use:
    - When user wants to delete multiple tasks
    - When cleaning up old or completed todos
    - When removing batches of obsolete tasks
    - For bulk cleanup operations

    Input:
    - todo_ids: Required, list of todo IDs to delete

    Output:
    - Success confirmation (no content)
    - Error if any todo not found

    Warning: Permanently deletes todos and their subtasks.
    """

ADD_SUBTASK = """
    Add a subtask to an existing todo.

    This tool creates a new subtask within a parent todo, useful for breaking
    down complex tasks into smaller, manageable steps.

    When to use:
    - When breaking down a complex task into multiple related subtasks
    - When a parent task requires sequential steps to complete
    - When creating a checklist of related items under a main task
    - When a task has multiple components that should be tracked separately
    - When organizing work that logically belongs under a single parent task
    - Only use for tasks that need multiple different components tracked individually

    Input:
    - todo_id: Required, parent todo ID
    - title: Required, subtask title

    Output:
    - Updated TodoResponse with new subtask
    - Error if todo not found or limit exceeded

    Note: Each todo can have up to 50 subtasks. For completely independent tasks, create separate todos instead.
    """

UPDATE_SUBTASK = """
    Update a specific subtask within a todo.

    This tool modifies subtask properties like title or completion status,
    enabling granular task progress tracking.

    When to use:
    - When marking subtasks as complete
    - When renaming subtasks
    - When updating subtask details
    - For subtask progress tracking

    Input:
    - todo_id: Required, parent todo ID
    - subtask_id: Required, subtask ID to update
    - title: Optional, new subtask title
    - completed: Optional boolean, completion status

    Output:
    - Updated TodoResponse with modified subtask
    - Error if todo or subtask not found

    Note: Subtask completion doesn't affect parent todo status.
    """

DELETE_SUBTASK = """
    Delete a subtask from a todo.

    This tool removes a subtask from its parent todo, useful for cleaning up
    or reorganizing task breakdown structures.

    When to use:
    - When removing unnecessary subtasks
    - When consolidating subtasks
    - When cleaning up task details
    - When user wants to delete a subtask

    Input:
    - todo_id: Required, parent todo ID
    - subtask_id: Required, subtask ID to delete

    Output:
    - Updated TodoResponse without the deleted subtask
    - Error if todo or subtask not found

    Note: Only removes the subtask, parent todo remains unchanged.
    """

SEMANTIC_SEARCH_TODOS = """
    Perform semantic search on todos using vector embeddings.

    This tool uses AI-powered semantic understanding to find todos that match
    the intent and meaning of the search query, not just exact keyword matches.
    It can understand context, synonyms, and related concepts.

    When to use:
    - When user searches with natural language queries
    - When looking for todos by concept rather than exact keywords
    - When traditional search doesn't find relevant results
    - When user describes what they're looking for conceptually
    - For finding related or similar tasks

    Input:
    - query: Required, natural language search query
    - limit: Optional, maximum results (default: 20)
    - project_id: Optional, filter by specific project
    - completed: Optional, filter by completion status
    - priority: Optional, filter by priority level

    Output:
    - List of TodoResponse objects ranked by semantic similarity
    - Empty list if no matches found
    - Falls back to traditional search if semantic search fails

    Examples:
    - "tasks about meetings" finds todos with meeting-related content
    - "urgent work items" finds high-priority work tasks
    - "shopping and errands" finds personal task categories
    """

GET_TODOS_SUMMARY = """
    Get a comprehensive summary of the user's todos in a single call.

    This tool provides a complete productivity snapshot including today's tasks,
    upcoming deadlines, overdue items, priority breakdown, project status, and
    recent completions. Perfect for daily briefings and quick status checks.

    When to use:
    - When user asks "What's my day look like?" or "Give me a summary"
    - For morning briefings or daily standups
    - When user wants a quick productivity overview
    - When checking overall task status at a glance
    - For "How am I doing?" type questions

    Output:
    A comprehensive summary dictionary containing:
    - today: List of todos due today with priorities
    - overdue: List of overdue todos needing attention
    - upcoming_week: Todos due in the next 7 days
    - high_priority: All high priority incomplete todos
    - stats: Quick stats (total, completed today, completion rate)
    - by_project: Task counts grouped by project
    - recently_completed: Tasks completed in last 24 hours
    - next_deadline: The nearest upcoming deadline

    Note: This is the go-to tool for any "summary", "overview", or "briefing" request.
    """
