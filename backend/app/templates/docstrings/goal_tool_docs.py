CREATE_GOAL = """
    Create a new goal with title and description.

    This tool creates a new goal for the user that can be broken down into a roadmap
    with tasks and milestones. Goals help users track long-term objectives and projects.

    When to use:
    - When user wants to set a new goal or objective
    - When user mentions wanting to achieve something specific
    - When user asks to create a goal for planning purposes
    - When user wants to track progress on a long-term project

    Input:
    - title: Required, the goal title (clear and specific)
    - description: Optional, detailed description of what the goal entails

    Output:
    - GoalResponse with created goal details including ID
    - Error message if creation fails

    Note: After creating a goal, users can generate a roadmap to break it down into actionable tasks.
    """

LIST_GOALS = """
    Retrieve all goals for the authenticated user.

    This tool fetches all goals that the user has created, providing an overview
    of their objectives and progress.

    When to use:
    - When user asks to see their goals
    - When user wants to review their objectives
    - When user asks about their progress on goals
    - When user needs to reference existing goals

    Input:
    - No parameters required

    Output:
    - List of GoalResponse objects with goal details
    - Empty list if no goals exist
    - Error message if retrieval fails

    Note: Each goal includes progress information and roadmap status.
    """

GET_GOAL = """
    Retrieve a specific goal by its ID with full details.

    This tool fetches detailed information about a specific goal, including
    its roadmap if available.

    When to use:
    - When user wants to see details of a specific goal
    - When user references a goal by name or asks about progress
    - When user wants to view the roadmap for a goal
    - When user asks about tasks related to a specific goal

    Input:
    - goal_id: Required, the unique identifier of the goal

    Output:
    - GoalResponse with full goal details and roadmap
    - Error message if goal not found or access denied

    Note: If the goal doesn't have a roadmap, it will suggest generating one.
    """

DELETE_GOAL = """
    Delete a specific goal and its associated data.

    This tool removes a goal and cleans up any associated todos and project data.
    Use with caution as this action cannot be undone.

    When to use:
    - When user explicitly asks to delete a goal
    - When user wants to remove a goal they no longer need
    - When user asks to clean up old or completed goals

    Input:
    - goal_id: Required, the unique identifier of the goal to delete

    Output:
    - Success confirmation with deleted goal details
    - Error message if goal not found or deletion fails

    Warning: This will also remove any associated todos and project data.
    """

GENERATE_ROADMAP = """
    Generate an AI-powered roadmap for a goal with streaming progress updates.

    This tool uses AI to break down a goal into actionable tasks and milestones,
    creating a visual roadmap that can be tracked and managed.

    When to use:
    - When user asks to create a plan for their goal
    - When user wants to break down a goal into steps
    - When user asks how to achieve a specific goal
    - When user wants a roadmap or action plan

    Input:
    - goal_id: Required, the goal to generate a roadmap for
    - regenerate: Optional boolean, whether to overwrite existing roadmap

    Output:
    - Streaming progress updates during generation
    - Complete roadmap with nodes (tasks) and connections
    - Associated todo project with subtasks for each roadmap item
    - Error message if generation fails

    Note: This creates both a visual roadmap and actionable todos for tracking progress.
    """

UPDATE_GOAL_NODE = """
    Update the completion status of a specific task in a goal's roadmap.

    This tool marks roadmap tasks as complete or incomplete, automatically syncing
    with associated todo items for consistent tracking.

    When to use:
    - When user completes a step in their goal roadmap
    - When user wants to mark a task as done
    - When user asks to update progress on a goal
    - When user mentions completing a specific milestone

    Input:
    - goal_id: Required, the goal containing the task
    - node_id: Required, the specific task/node to update
    - is_complete: Required boolean, the new completion status

    Output:
    - Updated goal with modified roadmap
    - Synced todo item completion status
    - Error message if update fails

    Note: Changes are automatically synced with associated todo items.
    """

SEARCH_GOALS = """
    Search for goals using natural language queries.

    This tool performs semantic search across goal titles and descriptions
    to help users find relevant goals quickly.

    When to use:
    - When user asks to find goals related to a topic
    - When user wants to search their goals
    - When user references a goal but doesn't remember the exact name
    - When user asks about goals containing specific keywords

    Input:
    - query: Required, natural language search query
    - limit: Optional, maximum number of results (default: 10)

    Output:
    - List of matching goals with relevance scores
    - Empty list if no matches found
    - Error message if search fails

    Note: Uses semantic search for natural language understanding.
    """

GET_GOAL_STATISTICS = """
    Get comprehensive statistics about user's goals and progress.

    This tool provides an overview of goal completion rates, active goals,
    and progress metrics to help users understand their achievement patterns.

    When to use:
    - When user asks about their goal progress
    - When user wants to see goal statistics
    - When user asks how they're doing with their goals
    - When user wants a progress overview

    Input:
    - No parameters required

    Output:
    - Statistics including total goals, completed goals, completion rate
    - Active goals with progress information
    - Goal creation and completion trends
    - Error message if retrieval fails

    Note: Provides insights into goal achievement patterns and progress.
    """
