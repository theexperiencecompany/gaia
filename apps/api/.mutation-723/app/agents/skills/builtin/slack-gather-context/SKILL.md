---
name: slack-gather-context
description: Gather comprehensive Slack context — search messages, identify what needs attention (mentions, DMs, urgent), read channel pulse, synthesize findings
target: slack_agent
---

# Slack: Gather Context & Attention Triage

## When to Activate
User asks what's happening in Slack, what needs their attention, searches for specific information, or wants a summary of activity.

## Step 1: Identify What the User Needs

**Attention triage** (what needs me?):
→ Go to Step 2: Attention Scan

**Specific search** (what did X say about Y?):
→ Go to Step 3: Smart Search

**Channel pulse** (what's happening in #channel?):
→ Go to Step 4: Channel Pulse

## Step 2: Attention Scan

Gather everything that needs the user's attention:

**DMs and mentions:**
```
SLACK_SEARCH_MESSAGES(query="to:me", sort="timestamp", sort_dir="desc", count=20)
```

**Urgent/important signals — search for keywords:**
```
SLACK_SEARCH_MESSAGES(query="urgent OR ASAP OR blocked OR critical OR help after:today", sort="timestamp", sort_dir="desc", count=20)
```

**Channels with activity — check key channels:**
```
SLACK_FIND_CHANNELS(query="general") → channel_id
SLACK_FETCH_CONVERSATION_HISTORY(channel=channel_id, limit=10)
```

**Synthesize into priority buckets:**
```
URGENT (needs response now):
  - @mention from Sarah in #engineering about prod issue (2m ago)
  - DM from Mike: "Can you review my PR ASAP?"

IMPORTANT (respond today):
  - Thread in #product about Q2 planning (you were mentioned)
  - DM from Alex about meeting reschedule

FYI (can wait):
  - #announcements: New onboarding doc shared
  - #random: Team lunch poll
```

## Step 3: Smart Search

Construct precise queries using Slack search modifiers:

**Query modifiers:**
- `in:#channel` — search within specific channel
- `from:@user` — search by sender
- `to:me` or `to:@user` — messages directed to someone
- `before:YYYY-MM-DD` / `after:YYYY-MM-DD` — time range
- `on:YYYY-MM-DD` — specific date
- `has:link` / `has:file` / `has:reaction` — content filters
- `is:thread` — only threaded messages

**Example queries:**
```
# Find deployment discussions this week
SLACK_SEARCH_MESSAGES(query="deployment after:2025-01-20 in:#engineering", sort="timestamp", sort_dir="desc")

# Find what a specific person said
SLACK_FIND_USERS(search_query="Sarah") → get user display name
SLACK_SEARCH_MESSAGES(query="from:@sarah project update", sort="timestamp", sort_dir="desc")
```

**Progressive search:**
1. Start specific: `"deployment error in:#production from:@ops after:today"`
2. If no results, broaden: `"deployment error after:today"`
3. If still empty, broaden more: `"deployment error"`

## Step 4: Channel Pulse

Read what's happening in a channel:

```
SLACK_FIND_CHANNELS(query="product") → channel_id
SLACK_FETCH_CONVERSATION_HISTORY(channel=channel_id, limit=30)
```

**For threads, always expand:**
```
SLACK_FETCH_MESSAGE_THREAD_FROM_A_CONVERSATION(channel=channel_id, thread_ts=message_ts)
```

### Using spawn_subagent for Multiple Channels

When gathering context from multiple channels in parallel:

```
spawn_subagent(task="Get recent messages from #engineering channel", context="Limit: 20 messages, focus on technical discussions")
spawn_subagent(task="Get recent messages from #product channel", context="Limit: 20 messages, focus on roadmap updates")
spawn_subagent(task="Get recent messages from #general channel", context="Limit: 20 messages, focus on announcements")
```

This allows parallel context gathering from multiple channels.

**Summarize by topic, not chronology:**
```
#product channel — last 24h:
  Topics discussed:
  1. Q2 Roadmap (3 threads, 15 messages) — Decision: Focus on mobile
  2. Bug triage (1 thread) — 4 Critical bugs assigned to eng
  3. Customer feedback (2 threads) — NPS survey results shared
  
  Pinned: Product roadmap doc (updated yesterday)
```

## Step 5: Synthesize & Present

Always provide:
- **Source**: channel name + timestamp for each finding
- **Context**: thread summary, not just individual messages
- **Action items**: What the user should respond to
- **Links**: Message permalinks when relevant

## Anti-Patterns
- Searching without using date filters (gets stale results)
- Not expanding threads (miss critical context)
- Dumping raw messages without synthesis
- Ignoring DMs when user asks "what needs my attention"
- Using sort="score" when user wants recent (use sort="timestamp")
