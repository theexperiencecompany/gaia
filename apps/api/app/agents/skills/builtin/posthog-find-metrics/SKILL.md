---
name: posthog-find-metrics
description: Find, query, and analyze PostHog metrics — trends, funnels, retention, feature flags, experiments, errors, and custom HogQL/SQL queries. Uses parallel subagents for multi-metric investigations.
target: posthog_agent
---

# PostHog: Find Metrics

## When to Activate
User wants analytics data, event trends, user behavior, conversion funnels, A/B test results, feature flag status, error rates, or any quantitative product metric from PostHog.

## Available Tools

**Querying & Analytics**
- `query-run` — execute trends, funnels, retention, lifecycle queries
- `insight-query` — query an existing saved insight
- `insight-get` / `insights-get-all` — fetch saved insights
- `insight-create-from-query` — save a new insight
- `query-generate-hogql-from-question` — last resort: scaffold HogQL from natural language

**Events & Properties**
- `event-definitions-list` — list all tracked event names
- `properties-list` — list properties for a specific event
- `property-definitions` — all property definitions in the project

**Feature Flags & Experiments**
- `feature-flag-get-all` / `feature-flag-get-definition` — list or inspect flags
- `experiment-get-all` / `experiment-get` — list or fetch experiments
- `experiment-results-get` — statistical results of an A/B test

**Errors & Logs**
- `list-errors` — top errors grouped by type, sorted by count
- `error-details` — full details + stack trace for a specific error group
- `logs-query` — query log entries by severity, service, time range
- `logs-list-attributes` / `logs-list-attribute-values` — discover log attribute keys/values

**Search & Organization**
- `entity-search` — search across insights, dashboards, feature flags, actions
- `dashboards-get-all` / `dashboard-get` — list or fetch dashboards
- `actions-get-all` / `action-get` — list or fetch actions

## Step 1: Understand What the User Wants

**Before calling any tool**, map intent to tool:
- **Trend / volume** → `query-run` with `TrendsQuery`
- **Funnel / conversion** → `query-run` with `FunnelsQuery`
- **Retention** → `query-run` with `RetentionQuery`
- **Custom SQL** → `query-run` with `HogQLQuery` (write directly; see patterns below)
- **Saved metrics** → `entity-search` then `insight-query`
- **Flag status** → `feature-flag-get-definition`
- **A/B results** → `experiment-results-get`
- **Errors** → `list-errors`

## Step 2: Discover Available Events (When Needed)

If event names are unknown, resolve them first:
```
event-definitions-list()               → all tracked event names
properties-list(event="event_name")    → filterable properties
```
Never guess event names.

## Step 3: Execute Queries

### Trend Query
```
query-run({
  "kind": "TrendsQuery",
  "series": [{"event": "user_signed_up", "kind": "EventsNode", "math": "dau"}],
  "dateRange": {"date_from": "-7d"}
})
```

### Funnel Query
```
query-run({
  "kind": "FunnelsQuery",
  "series": [
    {"event": "viewed_pricing", "kind": "EventsNode"},
    {"event": "started_checkout", "kind": "EventsNode"},
    {"event": "purchase_completed", "kind": "EventsNode"}
  ],
  "dateRange": {"date_from": "-30d"}
})
```

### HogQL / Custom SQL
Write HogQL directly — it's faster and more predictable:
```
query-run({
  "kind": "HogQLQuery",
  "query": "SELECT uniq(distinct_id) as users, toStartOfDay(timestamp) as day FROM events WHERE event = '$pageview' AND timestamp >= now() - interval 7 day GROUP BY day ORDER BY day"
})
```

> Only use `query-generate-hogql-from-question` if you're stuck on syntax — treat its output as a draft to edit, not a final query.

### Common HogQL Patterns
```sql
-- DAU over time
SELECT toStartOfDay(timestamp) as day, uniq(distinct_id) as dau
FROM events WHERE event = '$pageview' AND timestamp >= now() - interval 30 day
GROUP BY day ORDER BY day

-- Top events by volume
SELECT event, count() as cnt FROM events
WHERE timestamp >= now() - interval 7 day
GROUP BY event ORDER BY cnt DESC LIMIT 20

-- Users who did A but not B (drop-off)
SELECT uniq(a.distinct_id) FROM events a
WHERE a.event = 'step_A' AND a.timestamp >= now() - interval 30 day
AND a.distinct_id NOT IN (
  SELECT distinct_id FROM events WHERE event = 'step_B'
  AND timestamp >= now() - interval 30 day
)

-- Cohort retention
SELECT cohort_day, uniq(distinct_id) as retained_users
FROM (
  SELECT distinct_id, dateDiff('day', min(timestamp), timestamp) as cohort_day
  FROM events WHERE event = 'app_opened'
  GROUP BY distinct_id
)
WHERE cohort_day <= 30 GROUP BY cohort_day ORDER BY cohort_day
```

## Step 4: Parallel Execution

### Two simple metrics → call tools in parallel directly

User: "Give me today's signups and current error count."
```
# One turn, no subagents needed:
query-run({"kind": "TrendsQuery", "series": [{"event": "user_signed_up"}], "dateRange": {"date_from": "-1d"}})
list-errors()
```

### Multi-step tasks → spawn subagents in parallel

User: "Investigate this week's errors and tell me how the checkout experiment is going."

Each thread requires multiple tool calls internally:
```
spawn_subagent(
  task="Get top errors from PostHog this week using list-errors. For the top 2, fetch full details with error-details.",
  context="Return: error name, occurrence count, affected user count, one-line summary"
)

spawn_subagent(
  task="Find the checkout A/B experiment using experiment-get-all (look for 'checkout'), then get results with experiment-results-get.",
  context="Return: variant names, conversion rates, statistical significance, winner if declared"
)
```
Both run concurrently. First does `list-errors` → `error-details ×2`. Second does `experiment-get-all` → `experiment-results-get`. Synthesize once both return.

### Full product health check → multiple subagents
```
spawn_subagent(
  task="Query PostHog for new signups over 30 days by day using query-run TrendsQuery on 'user_signed_up'.",
  context="Return: total, day-by-day, notable spikes or drops"
)

spawn_subagent(
  task="Query signup → activation funnel (user_signed_up → onboarding_completed → first_action) over 30 days with FunnelsQuery.",
  context="Return: conversion rate at each step, biggest drop-off"
)

spawn_subagent(
  task="Get top 5 errors this week with list-errors, then fetch error-details for the top 2.",
  context="Return: name, count, affected users per error"
)

spawn_subagent(
  task="Get all experiments with experiment-get-all, then call experiment-results-get for any that are running.",
  context="Return: name, status, winner or current lift per experiment"
)
```

**Write subagent tasks that are self-contained:** name the exact tools, include event names and date ranges, one clear objective per subagent.
```
# Good:
"Get PostHog trends for 'payment_failed' over 14 days using query-run TrendsQuery,
 filtered by property plan='pro'. Return daily counts and total."

# Bad:
"Find payment metrics" ← subagent has to guess everything
```

## Step 5: Synthesize & Present

Present findings in well-structured markdown with sections per metric type (growth, funnel, errors, experiments). Always include absolute numbers, % change vs prior period, time range, and one actionable call-out.

## Anti-Patterns
- **Guessing event names** — always call `event-definitions-list` when unsure
- **Sequential when parallel is possible** — independent metrics should run concurrently
- **Arbitrary date ranges** — use user's range; default to `-30d` if unspecified
- **Over-querying** — check `insights-get-all` first; reuse saved insights when they already answer the question
