---
name: posthog-find-metrics
description: Find, query, and analyze PostHog metrics — trends, funnels, retention, feature flags, experiments, errors, and custom HogQL/SQL queries. Uses parallel subagents for multi-metric investigations.
target: posthog_agent
---

# PostHog: Find Metrics

## When to Activate
User wants analytics data, event trends, user behavior, conversion funnels, A/B test results, feature flag status, error rates, or any quantitative product metric from PostHog.

## The Only Tool: `exec`

PostHog's MCP runs in CLI mode: one `exec` tool wraps every PostHog tool, and you
reach them by passing a CLI-style string in `command`. There are hundreds of tools
across dozens of categories, so nothing is loaded upfront — you discover what you
need per task.

```text
exec({"command": "search <regex>"})              # find tools by name/description
exec({"command": "tools"})                       # fallback: list all
exec({"command": "info <tool_name>"})            # full or summarized schema
exec({"command": "schema <tool_name> <path>"})   # drill into one field
exec({"command": "call <tool_name> <json>"})     # run it
exec({"command": "call --json <tool_name> <json>"})
```

Rules the server itself states:
- Find unknown tools with `search` (or `tools` as a fallback). **Never guess a tool name.**
- Run `info` **once** per tool when its schema isn't already in context. Reuse it
  unless the tool changes or you hit a schema error. Never run `info` before every call.
- **Never guess a schema.** Any field `info` marks with a `hint` must be drilled with
  `schema <tool> <field.path>` before you call.

`schema` paths descend through object `properties` (`query.source`), array `items`
(`events.0.properties`, or `events.id` to jump to a property on the item type), and
`anyOf`/`oneOf` variants (by index, or by a property name that identifies a variant).
An unknown path returns the available child paths — read them rather than guessing again.

`search` matches tool metadata only, not input schemas, and there is no field
projection: drill one path at a time.

## Step 1: Map Intent, Then Discover

Decide what you need, then search for the tool that does it:

| User wants | Search for |
|---|---|
| Trend / volume, funnel, retention, custom SQL | `query` |
| Saved metrics | `insight` |
| Flag status | `feature.flag` |
| A/B results | `experiment` |
| Errors | `error` |
| Logs | `log` |
| Dashboards | `dashboard` |
| Event names / properties | `event.definition|propert` |

Example:
```text
exec({"command": "search query"})
exec({"command": "info query-run"})
exec({"command": "call query-run {\"query\": {\"kind\": \"TrendsQuery\", ...}}"})
```

## Step 2: Resolve Event Names First

If event names are unknown, discover them before querying — search for the event
definition tool, then list properties for the event you picked. Never guess event names.

## Step 3: Query Payloads

The query shapes below are PostHog's, independent of tool naming — pass them to
whichever query tool `search` surfaced, after confirming its schema with `info`.

### Trends
```json
{"kind": "TrendsQuery",
 "series": [{"event": "user_signed_up", "kind": "EventsNode", "math": "dau"}],
 "dateRange": {"date_from": "-7d"}}
```

### Funnel
```json
{"kind": "FunnelsQuery",
 "series": [{"event": "viewed_pricing", "kind": "EventsNode"},
            {"event": "started_checkout", "kind": "EventsNode"},
            {"event": "purchase_completed", "kind": "EventsNode"}],
 "dateRange": {"date_from": "-30d"}}
```

### HogQL / Custom SQL
Write HogQL directly — faster and more predictable than generating it:
```json
{"kind": "HogQLQuery",
 "query": "SELECT uniq(distinct_id) as users, toStartOfDay(timestamp) as day FROM events WHERE event = '$pageview' AND timestamp >= now() - interval 7 day GROUP BY day ORDER BY day"}
```

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

### Two simple metrics → two `exec` calls in one turn
Once both tools' schemas are known, issue the calls together — no subagents needed.

### Multi-step tasks → spawn subagents in parallel

Each thread needs its own discover-then-call sequence, so give each subagent a
self-contained objective:
```
spawn_subagent(
  task="In PostHog, search for the errors tool with exec search error, inspect it with info, then call it for this week's top errors. Fetch full details for the top 2.",
  context="Return: error name, occurrence count, affected user count, one-line summary"
)

spawn_subagent(
  task="In PostHog, search for the experiments tools with exec search experiment, list experiments, find the one matching 'checkout', then call the results tool for it.",
  context="Return: variant names, conversion rates, statistical significance, winner if declared"
)
```

Name the intent, the search term, the event names and the date range — one clear
objective per subagent:
```
# Good:
"Search PostHog for the query tool, then run a TrendsQuery for 'payment_failed'
 over 14 days filtered by property plan='pro'. Return daily counts and total."

# Bad:
"Find payment metrics" ← subagent has to guess everything
```

## Step 5: Synthesize & Present

Present findings in well-structured markdown with sections per metric type (growth,
funnel, errors, experiments). Always include absolute numbers, % change vs prior
period, time range, and one actionable call-out.

## Anti-Patterns
- **Guessing tool names** — `search` first; the tool list is large and changes
- **Guessing schemas** — `info` once per tool, and `schema` for every `hint` field
- **Running `info` before every call** — reuse the schema you already have
- **Guessing event names** — discover them before querying
- **Sequential when parallel is possible** — independent metrics should run concurrently
- **Arbitrary date ranges** — use the user's range; default to `-30d` if unspecified
- **Over-querying** — check saved insights first; reuse ones that already answer the question
