---
name: gmail-draft-send
description: Create and send Gmail emails using draft-first workflow. Always draft first, get user approval, then send.
subagent_id: gmail
---

# Gmail Draft & Send

## When to Use
- User wants to send an email
- User wants to compose a new email
- User asks to email someone
- User wants to follow up on previous conversation

## Tools

### GMAIL_CREATE_DRAFT
Create a new email draft.

**Required parameters:**
- `to`: Recipient email address(es), comma-separated for multiple
- `subject`: Email subject line
- `body`: Email body content (plain text or HTML)

**Optional parameters:**
- `cc`: CC recipients
- `bcc`: BCC recipients
- `from`: Sender alias (if multiple accounts)

### GMAIL_SEND_MESSAGE
Send an already-created draft.

**Required parameters:**
- `draft_id`: The ID from GMAIL_CREATE_DRAFT response

### GMAIL_SEARCH_EMAILS
Search existing emails before composing.

**Useful for:**
- Finding context for follow-up emails
- Getting email addresses of recipients
- Checking previous correspondence

## Workflow

### Step 1: Check Context (Optional but Recommended)
Before composing, consider:
- Search for previous emails with this person
- Look for relevant context to include
- Check if there's an existing thread

### Step 2: Create Draft First (NEVER auto-send)
Always create a draft first using `GMAIL_CREATE_DRAFT`.
- This allows user to review before sending
- User can make changes
- Prevents accidental sends

**Draft creation response includes:**
- `draft_id`: Needed for sending
- `thread_id`: If replying to thread

### Step 3: Present Draft to User
Show the draft with all details:
```
To: john@example.com
Subject: Meeting Follow-up
Body: Hi John,

Following up on our discussion yesterday...

Best regards
```

**Always ask for confirmation:**
- "Would you like me to send this?"
- "Shall I proceed with sending?"
- "Does this look good?"

### Step 4: Send Only After Approval
Use `GMAIL_SEND_MESSAGE` with the draft_id **only after** user explicitly confirms.

### Step 5: Handle Feedback
If user wants changes:
- Ask what to modify
- Create new draft with changes
- Present again for approval

## Important Rules
1. **NEVER auto-send** - Always wait for explicit confirmation
2. **Verify recipients** - Confirm email addresses are correct
3. **Show full draft** - Subject, body, recipients all visible
4. **Handle errors gracefully** - If send fails, explain and offer retry
5. **Check before replying** - Search for context when replying to threads

## Tips
- Use clear, concise subject lines
- Keep body focused and actionable
- Use paragraphs for readability
- Include relevant context from previous emails
- Be professional but friendly in tone
