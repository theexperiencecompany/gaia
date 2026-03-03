---
name: gmail-find-contacts
description: Find contacts in Gmail - search for specific people or email addresses from email history.
target: gmail_agent
---

# Gmail Find Contacts

## When to Use
- User asks "What's John's email?"
- User asks "Find contact information for..."
- User asks "Who have I emailed recently?"
- User asks for contacts from a company/domain
- User needs recipient disambiguation before sending email

## Tool Priority (Critical)

### 1) GMAIL_GET_CONTACT_LIST (PRIMARY)
Optimized custom tool for contact lookup from real Gmail message history.

**Use this first for contact search.**

**Parameters:**
- `query` (required): name, email, or domain
- `max_results` (optional, default: 30): number of messages to scan

**Best query patterns:**
- `john` (name)
- `john@company.com` (exact email)
- `company.com` (domain)
- `@` (broad sweep for a general contact list)

**Scaling:**
- Start with `max_results=30`
- If needed, retry with `60`, then `100`

### 2) GMAIL_SEARCH_PEOPLE
Searches people/contact records by name, email, phone, and organization.

**Best for:**
- Person may exist in contacts but not in recent email history
- User wants people-directory style matches

### 3) GMAIL_GET_CONTACTS
Lists Google contact connections from the account contacts dataset.

**Best for:**
- User explicitly asks for saved contacts/address book style data
- Inbox-history lookup is not enough

### 4) GMAIL_FETCH_EMAILS
Search emails directly for context when contact tools are inconclusive.

## Workflow

### Step 1: Convert request to a search token
- Name lookup -> `query="john"`
- Email lookup -> `query="john@company.com"` or `query="@company.com"`
- Company lookup -> `query="company.com"`

### Step 2: Run primary lookup first
```
GMAIL_GET_CONTACT_LIST(query="john", max_results=30)
```

### Step 3: Broaden if results are weak
```
GMAIL_GET_CONTACT_LIST(query="john", max_results=60)
GMAIL_GET_CONTACT_LIST(query="john", max_results=100)
```

If still empty, retry with alternate token (last name, domain, exact email
fragment).

### Step 4: Use fallbacks
- Try `GMAIL_SEARCH_PEOPLE(query="john")`
- If user wants saved contacts, call `GMAIL_GET_CONTACTS`
- If still unclear, use `GMAIL_FETCH_EMAILS` for recent sender/recipient context

### Step 5: Present and disambiguate
Show concise matches (name + email). If multiple strong matches remain, ask one
focused question.

Example:
```
I found 3 likely matches for "john":
1. John Smith - john.smith@company.com
2. John Doe - john.doe@other.com
3. Johnny Lee - johnny@startup.io

Which one should I use?
```

## Important Rules
1. Prefer `GMAIL_GET_CONTACT_LIST` before other contact tools.
2. Do not stop after one failed lookup; broaden query or `max_results`.
3. If multiple matches, ask one clarifying question before taking action.
4. Respect privacy; share only contact details needed for the task.
5. If nothing is found, state what you tried and suggest the next best query.

