---
name: gmail-clean-inbox
description: Structured inbox cleanup with clear label strategy, safe batching, and conservative actions.
target: gmail_agent
---

# Gmail: Clean Inbox

## When to Activate
- User asks to clean, organize, or reduce inbox noise
- Scheduled inbox-maintenance runs (for example: last 6 hours)

## Goal
Keep important/actionable emails visible and reduce low-value clutter using
labels, archive, star, and read-state updates safely.

## Tools to Use
- `GMAIL_LIST_LABELS`
- `GMAIL_GET_UNREAD_COUNT_WINDOW`
- `GMAIL_GET_UNREAD_COUNT`
- `GMAIL_FETCH_EMAILS`
- `GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID`
- `GMAIL_BATCH_MODIFY_MESSAGES`
- `GMAIL_ADD_LABEL_TO_EMAIL`
- `GMAIL_MODIFY_THREAD_LABELS`
- `GMAIL_CREATE_LABEL` (fallback mode only)
- `GMAIL_ARCHIVE_EMAIL`
- `GMAIL_MARK_AS_READ`
- `GMAIL_STAR_EMAIL`

## Label Strategy

### 1) Preserve mode (default)
If the user already has a meaningful label system, reuse it.
- Do not rename/delete labels.
- Do not create new labels unless required.

### 2) Fallback mode (no usable structure found)
Create and use only this minimal set:
- `GAIA/Action Required`
- `GAIA/Priority`
- `GAIA/Waiting`
- `GAIA/Newsletters`
- `GAIA/Receipts`
- `GAIA/Notifications`

## Execution Strategy

### Step 1: Load policy + detect label mode
1. Read memory for VIP senders, protected senders, protected labels, and archive
   preferences.
2. Call `GMAIL_LIST_LABELS`.
3. Choose preserve mode or fallback mode.

### Step 2: Measure scope first
Preferred for 6-hour run:
```
GMAIL_GET_UNREAD_COUNT_WINDOW(hours=6, label_ids=["INBOX"])
```

Fallback:
```
GMAIL_GET_UNREAD_COUNT(
  query="in:inbox is:unread after:<unix_timestamp_for_now_minus_6h>",
  label_ids=["INBOX"]
)
```

### Step 3: Build batches using pagination (real API behavior)
Do NOT invent index slicing. Build batches from paginated fetch results.

Use:
```
GMAIL_FETCH_EMAILS(
  query="in:inbox is:unread after:<since_timestamp>",
  include_payload=false,
  ids_only=true,
  max_results=20,
  page_token=<optional>
)
```

Batch creation rule:
- Each API page (`max_results=20`) is one batch.
- Next batch comes from `next_page_token`.
- This guarantees non-overlapping batches.

### Step 4: Spawn one subagent per batch
Each batch subagent must do all actions for its own messages:
- classify
- label
- star if needed
- archive/mark read if needed

Do not spawn separate subagents for separate actions.

Subagent contract:
```
Batch task
- batch_id: <n>
- message_ids: [<up to 20 ids>]
- mode: preserve|fallback
- vip_senders: [...]
- protected_senders: [...]
- protected_labels: [...]
- rules:
  - never_delete: true
  - keep_important_in_inbox: true
  - mark_read_only_for_low_value: true
```

## Action Policy (Concrete)

### Priority / Action-required
Apply when email has direct ask, approval request, hard deadline, or high-risk
topic.
- Apply label: `Priority` or `Action Required` (preserve-mode equivalent)
- Keep in inbox
- Keep unread
- Star only if urgency is high (deadline <= 24h, blocker, security/legal/finance risk)

### Newsletters / Promotions
Apply when clearly bulk, recurring, or marketing content.
- Apply label: `Newsletters`
- Archive
- Mark as read

### Receipts / Routine Finance confirmations
Apply for receipts, order confirmations, payment confirmations with no action
needed.
- Apply label: `Receipts`
- Archive
- Mark as read

### Automated Notifications
If no user action required:
- Apply label: `Notifications`
- Archive
- Mark as read

If action is required, treat as `Action Required` instead.

### Uncertain emails
- Keep in inbox
- Keep unread
- Do not archive aggressively

## Rules for Star / Archive / Read

### Star
Star only when truly urgent/high-impact.

### Archive
Archive only low-value or clearly non-actionable messages.

### Mark as read
Mark as read only when clearly non-actionable (newsletters, receipts, routine
notifications).

Never mark read for important/action-required/uncertain emails.

## Safety Rules
- Never delete or permanently remove emails in this skill
- Never remove existing user stars
- Never remove protected labels
- Preserve mode must not disturb user label architecture

## Final Output
Return concise summary:
- total processed
- count by class
- labels applied
- starred count
- archived count
- marked-read count
- skipped/protected count
