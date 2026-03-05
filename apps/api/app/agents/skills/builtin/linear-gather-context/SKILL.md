---
name: linear-gather-context
description: Gather comprehensive Linear context — my tasks, sprint progress, blockers, team workload, prioritized status report
target: linear_agent
---

# Linear: Gather Context & Status Report

## When to Activate
User wants to know what's happening in Linear — their tasks, sprint progress, blockers, team status, or needs a daily standup summary.

## Step 1: My Tasks & Priorities

Get the user's assigned issues:
```
LINEAR_CUSTOM_GET_MY_TASKS → assigned issues with status, priority, due dates
```

Or use the standard tool with user filter:
```
LINEAR_GET_CURRENT_USER → my user ID
LINEAR_LIST_LINEAR_ISSUES(assignee_id="me", first=30)
```

**Categorize by urgency:**
```
OVERDUE / URGENT (priority 1):
  - GEN-142: Fix auth bug (due: yesterday!)
  - GEN-98: Deploy hotfix (priority: Urgent)

DUE THIS WEEK (priority 2-3):
  - GEN-201: API redesign (due: Friday)
  - GEN-187: Update docs (due: Thursday)

BACKLOG / LOW PRIORITY:
  - GEN-250: Refactor utils (no due date)
```

## Step 2: Sprint Progress

Get active sprint/cycle status:
```
LINEAR_CUSTOM_GET_ACTIVE_SPRINT → current cycle with progress
```

Or manually:
```
LINEAR_GET_ALL_LINEAR_TEAMS → team_id
LINEAR_LIST_LINEAR_ISSUES(first=50) → filter by cycle
```

**Sprint summary:**
```
Sprint: "Sprint 23" (Jan 20 - Feb 3)
  Progress: 14/22 issues done (64%)
  Todo: 3 | In Progress: 5 | Done: 14
  
  Velocity: On track (avg 70% at this point)
  
  At Risk:
  - GEN-142: Blocked for 3 days (needs review)
  - GEN-201: Large scope, only 30% done
```

## Step 3: Blockers & Dependencies

Identify blocked issues:
```
LINEAR_CUSTOM_SEARCH_ISSUES(query="blocked") → blocked issues
```

For specific issue context:
```
LINEAR_CUSTOM_GET_ISSUE_FULL_CONTEXT(issue_identifier="GEN-142")
→ Comments, history, sub-issues, relations
```

### Using spawn_subagent for Multiple Issues

When you need to get full context for multiple issues in parallel:

```
spawn_subagent(task="Get full context for issue GEN-142", context="Extract: comments, history, sub-issues, relations")
spawn_subagent(task="Get full context for issue GEN-201", context="Extract: comments, history, sub-issues, relations")
spawn_subagent(task="Get full context for issue GEN-98", context="Extract: comments, history, sub-issues, relations")
```

This parallelizes fetching details for multiple issues.

## Step 4: Team Context

Get workspace-level view:
```
LINEAR_CUSTOM_GET_WORKSPACE_CONTEXT → teams, projects, members
```

**Team workload:**
```
LINEAR_LIST_LINEAR_ISSUES(first=50) → all team issues  
```

## Step 5: Synthesize Report

**Standup format:**
```
Linear Status — Feb 23, 2025

Your Tasks:
  Completed yesterday: GEN-190 (Auth migration)
  In progress: GEN-201 (API redesign, 30%)
  Starting today: GEN-215 (Cache layer)

Sprint 23 (64% complete, 5 days left):
  On track: 14/22 done
  At risk: GEN-142 (blocked), GEN-201 (large)

Blockers:
  - GEN-142: Waiting on review from @alex (3 days)
  
Suggest: Focus on GEN-142 blocker first (overdue), then GEN-201.
```

## Context Resolution

When user references issues by name or vague description:
```
LINEAR_CUSTOM_RESOLVE_CONTEXT(text="that auth bug") → resolves to GEN-142
LINEAR_CUSTOM_SEARCH_ISSUES(query="authentication error") → search results
```

## Anti-Patterns
- Listing all issues without prioritization
- Not checking sprint context (user needs timeline awareness)
- Ignoring blockers and dependencies
- Raw data dump without actionable synthesis
- Not resolving vague references to specific issues
