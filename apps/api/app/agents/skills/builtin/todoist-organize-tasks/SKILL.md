---
name: todoist-organize-tasks
description: Intelligently organize Todoist projects, tasks, labels and sections — search before creating, learn user patterns, smart decomposition
target: todo_agent
---

# Todoist: Organize Tasks & Projects

## When to Activate
User wants to create a project, organize tasks, set up a task structure, or batch-manage their Todoist workspace.

## Step 1: Understand Current Workspace

Before creating anything, gather context:

```
TODOIST_LIST_PROJECTS → existing projects, hierarchy, colors
TODOIST_LIST_LABELS → existing labels
```

**Think:**
- Does a similar project already exist? (search by name with `TODOIST_SEARCH_PROJECTS`)
- What naming conventions does the user follow? (capitalization, emojis, prefixes)
- What labels exist? Can we reuse them?

## Step 2: Search Before Creating

**Always search first:**
```
TODOIST_SEARCH_PROJECTS(query="<project name>") → check for duplicates
TODOIST_SEARCH_LABELS(query="<label>") → check if label exists
```

If a matching project exists:
- Ask user: "I found a project called 'X'. Should I add tasks there or create a new one?"
- Don't silently create duplicates

## Step 3: Create Project Structure

When creating a new project:
```
TODOIST_CREATE_PROJECT(
  name="Project Name",
  color="blue",           # Match user's color patterns
  view_style="list",      # or "board" for kanban
  parent_id="..."         # For sub-projects
)
```

Then add sections for logical groupings:
```
TODOIST_CREATE_SECTION(project_id, name="Planning")
TODOIST_CREATE_SECTION(project_id, name="In Progress")
TODOIST_CREATE_SECTION(project_id, name="Done")
```

## Step 4: Smart Task Decomposition

Break down the user's request into tasks intelligently:

**Priority mapping:**
- 4 = Urgent (p1 in Todoist UI)
- 3 = High (p2)
- 2 = Normal (p3)
- 1 = Low (p4)

**Date intelligence:**
- Use `due_string` for natural language: "tomorrow", "next Monday at 3pm", "every Friday"
- Use `due_date` for specific dates: "2025-03-15"
- Set `duration` + `duration_unit` for time estimates

```
TODOIST_CREATE_TASK(
  content="Task title",
  project_id="...",
  section_id="...",
  priority=3,
  due_string="next Monday",
  labels=["existing-label"],
  description="Additional context"
)
```

**Sub-tasks:** Use `parent_id` to create hierarchy:
```
TODOIST_CREATE_TASK(content="Parent task", project_id=...) → get task_id
TODOIST_CREATE_TASK(content="Sub-task 1", parent_id=task_id)
TODOIST_CREATE_TASK(content="Sub-task 2", parent_id=task_id)
```

## Step 5: Labels & Organization

Create labels only if they don't exist:
```
TODOIST_SEARCH_LABELS(query="urgent") → not found
TODOIST_CREATE_LABEL(name="urgent", color=30)  # berry_red
```

**Label strategy:**
- Use existing labels when possible
- Follow user's naming: lowercase, kebab-case, etc.
- Don't create redundant labels (e.g., "important" when "priority" exists)

## Step 6: Confirm Structure

After creating, present the structure:
```
Project: "Q1 Marketing Plan" (blue)
  Planning (3 tasks)
    - Research competitors (due: Mon, p2)
    - Define target audience (due: Tue, p2)
    - Set budget (due: Wed, p1)
  Execution (2 tasks)
    - Launch campaign (due: next Fri, p1)
    - Monitor metrics (recurring: every Mon, p3)
  Labels used: marketing, q1
```

## Anti-Patterns
- Creating projects without checking existing ones
- Creating new labels when matching ones exist
- Setting all tasks to the same priority
- Omitting due dates when the user implied a timeline
- Flat task lists when hierarchy would be clearer
