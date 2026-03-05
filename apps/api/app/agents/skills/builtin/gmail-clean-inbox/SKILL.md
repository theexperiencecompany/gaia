---
name: gmail-clean-inbox
description: Intelligently clean Gmail inbox - audit labels, identify patterns, batch categorize, archive old messages, present cleanup summary
target: gmail_agent
---

# Gmail: Clean & Organize Inbox

## When to Activate
User wants inbox zero, wants to clean up, organize, or manage their Gmail inbox.

## Step 1: Audit Current State

Understand what's in the inbox:
```
GMAIL_FETCH_EMAILS(query="is:unread", max_results=50, include_payload=false) → unread count/preview
GMAIL_FETCH_EMAILS(query="in:inbox", max_results=100, include_payload=false) → total inbox size
GMAIL_LIST_LABELS() → existing labels/categories
```

**Assess:**
- How many unread emails?
- What categories dominate? (promotions, updates, social, primary)
- Any emails older than 30 days sitting in inbox?

## Step 2: Identify Cleanup Patterns

Search for bulk cleanup opportunities:

**Promotions & newsletters:**
```
GMAIL_FETCH_EMAILS(query="category:promotions is:unread", max_results=50)
```

**Old unread:**
```
GMAIL_FETCH_EMAILS(query="is:unread before:2025/01/01", max_results=50)
```

**Large threads:**
```
GMAIL_LIST_THREADS(query="is:unread", max_results=30, verbose=false)
```

**From common senders:**
```
GMAIL_FETCH_EMAILS(query="from:notifications@github.com is:unread", max_results=50)
```

### Using spawn_subagent for Parallel Search

When searching multiple categories in parallel (Gmail responses can be large):

```
spawn_subagent(task="Search unread promotions", context="query: category:promotions is:unread, max_results: 50")
spawn_subagent(task="Search GitHub notifications", context="query: from:github.com is:unread, max_results: 50")
spawn_subagent(task="Search old unread emails", context="query: is:unread before:2025/01/01, max_results: 50")
```

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
