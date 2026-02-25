---
name: gmail-search-context
description: Search Gmail intelligently — construct precise queries, resolve threads, handle attachments, synthesize findings
target: gmail_agent
---

# Gmail: Search & Gather Context

## When to Activate
User wants to find specific emails, search for information in their inbox, or gather email context on a topic.

## Step 1: Construct Smart Query

Gmail supports powerful search operators:

**People:**
- `from:user@example.com` — emails from
- `to:user@example.com` — emails to
- `cc:user@example.com` — CC'd to

**Status:**
- `is:unread` / `is:read` / `is:starred` / `is:important` / `is:snoozed`

**Categories:**
- `category:primary` / `category:social` / `category:promotions` / `category:updates`
- `label:custom-label` — user-created labels only

**Time:**
- `after:2025/01/01` / `before:2025/02/01`
- `newer_than:7d` / `older_than:30d`

**Content:**
- `subject:meeting` — in subject line
- `"exact phrase"` — exact match
- `has:attachment` / `filename:pdf` / `filename:xlsx`
- `larger:5M` / `smaller:1M` — by size

**Logic:** AND (default), OR, `-exclude`

## Step 2: Execute Search

**Find specific emails:**
```
GMAIL_FETCH_EMAILS(
  query="from:sarah@company.com subject:Q1 after:2025/01/01",
  max_results=20
)
```

**Find contacts:**
```
GMAIL_SEARCH_PEOPLE(query="Sarah", pageSize=10)
```

**Thread-based search:**
```
GMAIL_LIST_THREADS(
  query="project proposal from:alex",
  max_results=10,
  verbose=true   # Get full thread content
)
```

## Step 3: Progressive Search

1. **Start specific:** `"quarterly report from:finance@company.com after:2025/01/01 has:attachment"`
2. **Broaden if empty:** `"quarterly report from:finance@company.com"`
3. **Broaden more:** `"quarterly report has:attachment"`
4. **Last resort:** `"quarterly report"`

## Step 4: Read Full Context

When you find relevant messages, get full details:
```
GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID(message_id="<msg_id>", format="full")
```

For thread context:
```
GMAIL_LIST_THREADS(query="...", verbose=true) → full thread with all replies
```

### Using spawn_subagent for Multiple Threads

When reading multiple email threads (Gmail responses can be large - use spawn_subagent to keep context clean):

```
spawn_subagent(task="Read thread ID xyz123 and extract key points", context="Focus on action items and decisions")
spawn_subagent(task="Read thread ID abc456 and extract key points", context="Focus on action items and decisions")
spawn_subagent(task="Read thread ID def789 and extract key points", context="Focus on action items and decisions")
```

## Step 5: Synthesize Findings

Present organized results:
```
Found 8 emails about "Q1 budget proposal":

Thread: "Q1 Budget Review" (5 messages)
   From: Sarah → Finance Team | Jan 15-22
   Summary: Initial proposal → revision → final approval
   Attachment: Q1_Budget_Final.xlsx (in latest message)
   Status: Approved (Sarah's last message: "Looks good, approved.")

Thread: "Budget Follow-up" (3 messages)  
   From: Alex → Sarah, You | Jan 25
   Summary: Questions about marketing allocation
   Status: Awaiting your response
```

## Anti-Patterns
- Using `label:snoozed` (wrong — use `is:snoozed`)
- Not using `include_payload=true` when content is needed
- Searching with very long natural language (use operators)
- Giving up after one search (use progressive strategy)
- Raw message dumps without synthesis
