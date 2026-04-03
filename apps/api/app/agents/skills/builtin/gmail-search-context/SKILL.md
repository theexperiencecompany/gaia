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
- **Fetch all emails for a specific day:** use `after:YYYY/MM/DD before:YYYY/MM/DD+1` (e.g., all emails on Jan 15: `after:2025/01/15 before:2025/01/16`)

**Content:**
- `subject:meeting` — in subject line
- `"exact phrase"` — exact match
- `has:attachment` / `filename:pdf` / `filename:xlsx`
- `larger:5M` / `smaller:1M` — by size

**Logic:** AND (default), OR, `-exclude`

## Step 2: Execute Search

**Always use `spawn_subagent` for any Gmail fetch** — raw email responses are too large for the parent context regardless of result count. The subagent fetches, summarizes, and returns only a compact digest + `next_page_token`.

**CRITICAL: Always paginate until `next_page_token` is null.** A single page is almost never complete — you MUST keep spawning subagents for each subsequent page until no token is returned. Stopping early means silently missing emails.

**Find specific emails** (paginate until `next_page_token` is null):
```
result = spawn_subagent(
  task="""
    Call GMAIL_FETCH_EMAILS(query="from:sarah@company.com subject:Q1 after:2025/01/01", max_results=30)
    Summarize ALL emails: sender, subject, date, key points, action items.
    You MUST return: digest: <summary>, next_page_token: <token or null>
  """
)
# If next_page_token is not null, spawn another subagent with page_token=<token>.
# Keep paginating until next_page_token is null — only then is the result complete.
```

**Find contacts** (lightweight — safe to call directly):
```
GMAIL_SEARCH_PEOPLE(query="Sarah", pageSize=10)
```

**Thread-based search** (paginate until `next_page_token` is null):
```
result = spawn_subagent(
  task="""
    Call GMAIL_LIST_THREADS(query="project proposal from:alex", max_results=30, verbose=true)
    For each thread extract: participants, timeline, key decisions, action items.
    You MUST return: digest: <summary>, next_page_token: <token or null>
  """
)
# If next_page_token is not null, spawn another subagent with page_token=<token>.
# Keep paginating until next_page_token is null — only then is the result complete.
```

**Fetch ALL emails for a specific day:**

Use `after:YYYY/MM/DD before:YYYY/MM/DD+1`. Parent orchestrates pagination — spawn a subagent per page, each returning a digest + token. **You MUST keep spawning until `next_page_token` is null** — any earlier stop silently drops emails:

```
# Page 1
result_1 = spawn_subagent(
  task="""
    Call GMAIL_FETCH_EMAILS(query="after:2025/01/15 before:2025/01/16", max_results=30)
    Summarize ALL emails: sender, subject, date, key points, action items.
    You MUST return: digest: <summary>, next_page_token: <token or null>
  """
)

# Page 2 — only if token returned
if result_1.next_page_token:
  result_2 = spawn_subagent(
    task="""
      Call GMAIL_FETCH_EMAILS(query="after:2025/01/15 before:2025/01/16", max_results=30, page_token="<token>")
      Summarize ALL emails on this page: sender, subject, date, key points, action items.
      You MUST return: digest: <summary>, next_page_token: <token or null>
    """
  )

# CRITICAL: Repeat until next_page_token is null. Only then synthesize all digests.
# Stopping before null means the search is incomplete.
```

## Step 3: Progressive Search

1. **Start specific:** `"quarterly report from:finance@company.com after:2025/01/01 has:attachment"`
2. **Broaden if empty:** `"quarterly report from:finance@company.com"`
3. **Broaden more:** `"quarterly report has:attachment"`
4. **Last resort:** `"quarterly report"`

## Persistence & Disambiguation (Critical)

- Do not stop after a small sample (e.g., first 5-10 results). Broaden queries and increase max_results when needed.
- If multiple strong candidates remain, present the best 2-3 with sender + date + subject, then ask ONE focused question to disambiguate.
- If no results, list the queries you tried (briefly) and ask ONE clarifying question (sender? timeframe? attachment type?).

## Step 4: Synthesize Findings

Parent collects all subagent digests and presents organized results:
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
- Calling `GMAIL_FETCH_EMAILS` or `GMAIL_LIST_THREADS` in the parent context — always use `spawn_subagent`
- **Stopping pagination early** — you MUST fetch pages until `next_page_token` is null; stopping sooner silently omits emails
- **Not summarizing every page** — each subagent must summarize its page's emails before returning; never return raw message data
- Using `label:snoozed` (wrong — use `is:snoozed`)
- Searching with very long natural language (use operators)
- Giving up after one search (use progressive strategy)
- Raw message dumps without synthesis
