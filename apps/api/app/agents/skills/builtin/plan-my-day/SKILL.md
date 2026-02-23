---
name: plan-my-day
description: Cross-provider daily planner — gather context from calendar, todos, linear, GitHub, and more. Synthesize into a prioritized action plan.
target: executor
---

# Plan My Day

## When to Activate
User wants to plan their day, asks "what should I focus on today", wants a daily briefing, or says "plan my day".

## Overview

This skill orchestrates across multiple providers to build a complete picture of the user's day. It synthesizes calendar events, pending tasks, sprint issues, and pending reviews into one actionable plan.

## Tools Used
- **Google Calendar**: `GOOGLECALENDAR_CUSTOM_GET_DAY_SUMMARY`, `GOOGLECALENDAR_CUSTOM_FETCH_EVENTS`
- **Todoist**: `TODOIST_FILTER_TASKS`, `TODOIST_LIST_TASKS`
- **Linear**: `LINEAR_CUSTOM_GET_MY_TASKS`, `LINEAR_CUSTOM_GET_ACTIVE_SPRINT`
- **GitHub**: `GITHUB_SEARCH_ISSUES_AND_PULL_REQUESTS`

## Step 1: Gather Calendar Context

**Ask the calendar agent for today's schedule:**
```
Tool: GOOGLECALENDAR_CUSTOM_GET_DAY_SUMMARY
→ Today's meetings, free slots, conflicts
```

Or manually:
```
GOOGLECALENDAR_CUSTOM_FETCH_EVENTS(
  time_min="today 00:00",
  time_max="today 23:59"
)
```

**Extract:**
- Meeting count and total meeting hours
- Free time blocks (available for deep work)
- Any conflicts or back-to-back meetings

### Phase 1: Context Gathering
- **Calendar**: Call `GOOGLECALENDAR_CUSTOM_GET_DAY_SUMMARY` to get the user's schedule, next event, and busy hours for today.
- **Todos**: Call `TODOIST_FILTER_TASKS` with a query for "overdue | today" to get high-priority tasks.
- **Linear**: Call `LINEAR_CUSTOM_GET_MY_TASKS` to see active issues assigned to the user.
- **GitHub**: Call `GITHUB_SEARCH_ISSUES_AND_PULL_REQUESTS` with `q="assignee:me state:open"` if GitHub integration is active.

## Step 2: Gather Task Context

**Todoist/Todo tasks due today:**
```
TODOIST_FILTER_TASKS(query="today | overdue")
```

**Linear issues assigned to me:**
```
LINEAR_CUSTOM_GET_MY_TASKS → in-progress and upcoming issues
```

**GitHub PRs needing review (if available):**
- Check for assigned PRs or review requests

## Step 3: Identify Priorities

Score each item by urgency × importance:

| Signal | Score |
|--------|-------|
| Overdue task/issue | Critical |
| Due today | High |
| Blocked by others waiting on me | High |
| Sprint deadline approaching | Medium |
| Scheduled meeting prep needed | Medium |
| Due this week | Normal |
| No deadline | Low |

## Step 4: Build the Daily Plan

Structure by time blocks:

```
Your Day — Monday, Feb 24

Schedule:
  09:00-09:30  Morning routine + review this plan
  09:30-10:00  Fix auth bug (GEN-142) — overdue, blocking team
  10:00-11:00  Sprint Planning (meeting)
  11:00-12:30  API redesign (GEN-201) — deep work block
  12:30-13:30  Lunch
  13:30-14:00  Review Sarah's PR (#345) — requested 2 days ago
  14:00-15:00  1:1 with Alex (meeting)
  15:00-16:30  Todoist: Prepare Q1 report (due today)
  16:30-17:00  Process inbox + respond to messages

Summary:
  Meetings: 2 (1.5 hours)
  Deep work: 3 hours available
  Tasks due: 4 (2 overdue, 2 today)
  Reviews pending: 1

Top 3 Priorities:
  1. Fix auth bug GEN-142 (overdue, urgent)
  2. Todoist: Q1 report (due today)
  3. Review PR #345 (blocking Sarah)

Tip: Your 11:00-12:30 block is your longest uninterrupted time.
   Use it for the API redesign which needs focused attention.
```

## Step 5: Handle Gaps

If a provider isn't connected:
- Skip gracefully: "I couldn't access your GitHub — connect it for PR review tracking"
- Still provide value from available providers

If calendar is empty:
- Suggest time blocking based on task priorities

## Presentation Style
- Always organize by time (morning → afternoon → evening)
- Use text formatting for visual scanning
- Bold the top 3 priorities
- Include total meeting hours vs deep work hours
- End with an actionable tip

## Anti-Patterns
- Just listing tasks without time-blocking
- Ignoring meetings when suggesting focus blocks
- Not flagging overdue items prominently
- Creating a plan without considering available free time
- Listing 20+ items (focus on top priorities, group the rest)
