---
name: gmail-create-filters
description: Create high-value Gmail filters safely using strict matching and minimal-risk actions.
target: gmail_agent
---

# Gmail: Create Filters

## When to Activate
- User asks to set up Gmail filters/rules
- User wants recurring inbox automation

## Goal
Create useful, low-risk filters that reduce inbox noise without hiding important
emails.

## Tools to Use
- `GMAIL_LIST_FILTERS`
- `GMAIL_GET_FILTER`
- `GMAIL_CREATE_FILTER`
- `GMAIL_DELETE_FILTER` (only when user explicitly asks to remove a rule)
- `GMAIL_LIST_LABELS`
- `GMAIL_CREATE_LABEL` (only when needed)
- `GMAIL_FETCH_EMAILS` (for pattern validation)

## Filter Design Principles
- Prefer exact sender/domain matches over broad subject-only rules
- Reuse existing labels first
- Keep rules narrow and explainable
- No destructive actions in filters
- No auto-forwarding unless explicitly requested

## Label Policy

### Preserve mode (default)
If user already has a label system, reuse it.

### Fallback mode
If no usable structure exists, create minimal labels:
- `GAIA/Newsletters`
- `GAIA/Receipts`
- `GAIA/Notifications`
- `GAIA/Priority`

## Execution Strategy

### Step 1: Audit existing setup
1. Call `GMAIL_LIST_LABELS`
2. Call `GMAIL_LIST_FILTERS`
3. Identify duplicates/conflicts before creating anything new

### Step 2: Discover recurring patterns
Use `GMAIL_FETCH_EMAILS` to validate that a pattern is recurring (not one-off).
Target patterns that appear repeatedly and are low risk:
- newsletters/promotions
- receipts/order confirmations
- routine automated notifications

### Step 3: Build filter plan
For each proposed filter define:
- criteria (sender/domain/keywords)
- target label
- archive or keep-in-inbox behavior
- read-state behavior

### Step 4: Create filters conservatively
Create only high-confidence filters.

Recommended defaults:
- Newsletters: label + archive + mark read
- Receipts (non-actionable): label + archive + mark read
- Routine notifications: label + archive + mark read
- Priority senders: label + keep in inbox (no auto-archive)

### Step 5: Verify
Re-list filters and return a concise change summary.

## Safety Rules
- Never create broad catch-all rules that can hide important email
- Never auto-delete via filters
- Never auto-forward without explicit user instruction
- Never archive emails from VIP/protected senders by default

## Final Output
Return:
- filters created
- labels used/created
- rationale per filter
- any risky filters intentionally skipped
