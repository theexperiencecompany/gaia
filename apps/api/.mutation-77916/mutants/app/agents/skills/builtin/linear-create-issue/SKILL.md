---
name: linear-create-issue
description: Create Linear issues intelligently - search for duplicates, learn team patterns, evaluate sub-issue breakdown, then create with proper context.
target: linear_agent
---

# Linear Create Issue

## When to Use
- User asks to "create an issue" or "file a bug"
- User asks to "add a ticket" or "track this"
- User describes a problem, task, or feature to be tracked
- User wants to create issues with sub-tasks

## Tools

### Discovery & Context
- **LINEAR_CUSTOM_GET_WORKSPACE_CONTEXT** — Get teams, projects, labels, states
- **LINEAR_CUSTOM_RESOLVE_CONTEXT** — Map fuzzy names → IDs (team, user, labels, project, state)
- **LINEAR_CUSTOM_SEARCH_ISSUES** — Search issues by keyword
- **LINEAR_CUSTOM_GET_ISSUE_FULL_CONTEXT** — Get full issue details
- **LINEAR_CUSTOM_GET_ACTIVE_SPRINT** — Get current sprint/cycle info
- **LINEAR_CUSTOM_GET_MY_TASKS** — Get authenticated user's assigned issues

### Creation
- **LINEAR_CUSTOM_CREATE_ISSUE** — Create issue with all fields
  - Required: team_id, title
  - Optional: description, assignee_id, priority (0-4), state_id, label_ids, project_id, cycle_id, due_date, estimate, parent_id
  - Sub-issues: sub_issues array [{title, description, assignee_id, priority}]

## Workflow

### Step 1: Search for Duplicates (MANDATORY)

Before creating anything, search for existing issues:

```
LINEAR_CUSTOM_SEARCH_ISSUES(query="<keywords from user request>")
```

If similar issues exist:
- Show them to the user: "I found these existing issues that look similar..."
- Ask if they want to proceed or update an existing one
- Only continue to creation after user confirms no duplicate

### Step 2: Learn Team Patterns

Understand how the team structures issues:

1. **Get workspace context:**
   ```
   LINEAR_CUSTOM_GET_WORKSPACE_CONTEXT()
   ```
   This reveals team names, available states, labels, and projects.

2. **Read recent team issues (2-3):**
   ```
   LINEAR_CUSTOM_SEARCH_ISSUES(query="recent")
   ```
   Study the results to learn:
   - Title format (e.g., "[Component] Description" vs plain descriptions)
   - Description structure (bullet points? acceptance criteria? steps to reproduce?)
   - Common labels used
   - Priority conventions

3. **Match the team's style** when writing the title and description.

### Step 3: Evaluate Sub-Issue Potential

If the user's request is broad or multi-faceted:

- **Break it down:** Suggest logical sub-issues
  - Example: "Implement auth" → "Design login flow", "Implement OAuth", "Add MFA", "Write tests"
- **Ask the user:** "This looks like it could be broken into sub-tasks. Want me to create sub-issues?"
- **Keep it practical:** Only suggest 2-5 sub-issues; too many is unhelpful

If the request is specific and focused, skip sub-issues entirely.

### Step 4: Resolve All Entities

Use RESOLVE_CONTEXT to convert names to IDs:

```
LINEAR_CUSTOM_RESOLVE_CONTEXT(
    team_name="engineering",
    user_name="john",
    label_names=["bug", "critical"],
    project_name="Q1 Sprint",
    state_name="backlog"
)
```

This returns: team_id, user_id, label_ids, project_id, state_id

**For cycle_id** (adding to current sprint):
```
LINEAR_CUSTOM_GET_ACTIVE_SPRINT()
```

### Step 5: Create the Issue

```
LINEAR_CUSTOM_CREATE_ISSUE(
    team_id=resolved_team_id,
    title="Formatted like team's convention",
    description="Structured like team's existing issues",
    assignee_id=resolved_user_id,
    priority=2,
    label_ids=resolved_label_ids,
    project_id=resolved_project_id,
    state_id=resolved_state_id,
    cycle_id=sprint_cycle_id,
    sub_issues=[
        {"title": "Sub-task 1", "priority": 2},
        {"title": "Sub-task 2", "priority": 2}
    ]
)
```

### Step 6: Confirm Results

Report back clearly:
- Issue identifier (e.g., "ENG-456")
- URL to the issue
- What was set (assignee, labels, project, sprint)
- Sub-issues created (if any)
- Anything that needs follow-up

## Priority Mapping
- 0 = No priority
- 1 = Urgent
- 2 = High
- 3 = Medium
- 4 = Low

## Important Rules
1. **Always search first** — Never create without checking for duplicates
2. **Learn before creating** — Read team patterns to match style
3. **Never guess IDs** — Always use RESOLVE_CONTEXT to convert names
4. **Suggest structure** — Offer sub-issues for broad tasks
5. **Confirm results** — Show what was created with identifiers and URLs
