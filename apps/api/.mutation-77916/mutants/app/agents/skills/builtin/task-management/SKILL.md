---
name: task-management
description: Manage and create tasks across various integrations (Gaia Todos, Todoist, Google Tasks, Asana, ClickUp, Linear, Trello, etc.)
target: executor
---

# Task Management

## When to Use
- User asks to "create a task", "add a todo", "list my tasks"
- User mentions specific task apps like Todoist, Google Tasks, Asana, ClickUp, Linear, Trello, etc.

## Strategy / Important Rules
1. **Determine User Preference:**
   - First, run `search_memory` to check if the user has a preferred default task management app.
   - If the user specifies an app in their request (e.g. "add this to todoist"), use that app.
   - If no app is specified and no preference is in memory, run `list_integrations` to check available/connected task integrations.
   - If there are multiple task integrations connected and it is still ambiguous, **ask the user for clarification** on which task app to use, and ask if they want to save it as their default in memory.
2. **Supported Integrations:**
   Look for operations related to the following connected tool spaces (refer to oauth_config integrations):
   - `todos` (Gaia Todos built-in)
   - `todoist`
   - `googletasks`
   - `asana`
   - `clickup`
   - `linear`
   - `trello`

## Workflow

### Step 1: Identify Target Integration
- Run `search_memory` for preferred task app.
- Run `list_integrations` if needed to check active connections.
- Ask user for clarification if ambiguous.

### Step 2: Execute Task Operation
- Create, list, or update the task using the respective tools for the chosen integration.
- Rely on the connected provider's specific task management tools to fulfill the request.

### Step 3: Confirm to User
Report:
- The task action completed successfully.
- The platform where the task was created or managed.
