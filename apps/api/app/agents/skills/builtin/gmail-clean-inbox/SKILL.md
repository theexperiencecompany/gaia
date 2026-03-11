---
name: gmail-clean-inbox
description: Intelligently clean Gmail inbox - audit labels, identify patterns, batch categorize, archive old messages, present cleanup summary
target: gmail_agent
---

# Gmail: Clean & Organize Inbox

## When to Activate
User wants inbox zero, wants to clean up, organize, or manage their Gmail inbox.

## Step 1: Audit Current State

Use lightweight counting first to avoid large message payloads.
`GMAIL_LIST_LABELS` and `GMAIL_GET_UNREAD_COUNT` are safe to call directly.

```
GMAIL_LIST_LABELS()

# Per-label unread + total counts
GMAIL_GET_UNREAD_COUNT(
  label_ids=["INBOX", "CATEGORY_PROMOTIONS", "CATEGORY_UPDATES", "CATEGORY_SOCIAL"]
)

# Inbox unread via query estimate
GMAIL_GET_UNREAD_COUNT(query="is:unread", label_ids=["INBOX"])
```

## Step 2: Identify Cleanup Patterns

Use query-based counting to identify opportunities without fetching full email
lists:

```
GMAIL_GET_UNREAD_COUNT(
  query="category:promotions is:unread",
  label_ids=["INBOX"]
)

GMAIL_GET_UNREAD_COUNT(
  query="from:notifications@github.com is:unread",
  label_ids=["INBOX"]
)

GMAIL_GET_UNREAD_COUNT(
  query="is:unread before:2025/01/01",
  label_ids=["INBOX"]
)

GMAIL_GET_UNREAD_COUNT(
  query="is:unread category:updates",
  label_ids=["INBOX"]
)
```

If query counting is unavailable in a specific environment, fallback to
`GMAIL_FETCH_EMAILS(query="...", include_payload=false)` in parent context.

## Step 3: Present Cleanup Plan

Before acting, present findings and get consent:
```
Inbox Audit:
  Total in inbox: 847
  Unread: 234

  Cleanup opportunities:
  1. 78 unread promotions → Archive all? (saves 78 emails)
  2. 45 GitHub notifications older than 7 days → Archive? (saves 45)
  3. 32 newsletter emails → Archive + create filter? (saves 32)
  4. 28 old calendar notifications → Trash? (saves 28)
  
  Estimated cleanup: 183 emails (78% of unread)
  
  Which actions should I proceed with? (all/specific numbers)
```

## Step 4: Execute Cleanup

**Only after user confirms**, batch process:

- **Audit labels first**: Use `GMAIL_LIST_LABELS` to find the correct label IDs (especially for custom labels).
- **Count first, fetch IDs only for approved actions**: After user confirms,
  call `GMAIL_FETCH_EMAILS(query="...", include_payload=false)` for each
  selected cleanup query and paginate with `next_page_token` to collect all
  `message_id`s.
- **Prefer batch operations**: Use `GMAIL_BATCH_MODIFY_MESSAGES` whenever you are modifying many emails at once (archive, mark read/unread, apply/remove labels). Chunk large operations (up to 1,000 message IDs per call).
- **Single-message label changes**: Use `GMAIL_ADD_LABEL_TO_EMAIL` when you only need to adjust one message.
- **Thread-wide label changes**: Use `GMAIL_MODIFY_THREAD_LABELS` to label/unlabel an entire thread.
- **Delete carefully**: Prefer `GMAIL_MOVE_TO_TRASH` for reversible cleanup; use `GMAIL_BATCH_DELETE_MESSAGES` only for permanent deletion and only with explicit user confirmation.

## Step 5: Summary Report

```
Inbox Cleanup Complete:
  Before: 847 emails (234 unread)
  After:  664 emails (51 unread)
  
  Actions taken:
  - Archived 78 promotions
  - Archived 45 old GitHub notifications
  - Trashed 28 calendar notifications
  - Labeled 32 newsletters as "newsletters"
  
  Tip: I can help set up Gmail filters to auto-archive these in the future.
```

## Safety Rules
- NEVER delete/trash without explicit user consent
- NEVER touch starred or important emails
- NEVER auto-process emails less than 24h old
- Always present plan first, act second
- Use archive (remove INBOX) over trash when possible
- Report exactly what was done after cleanup
