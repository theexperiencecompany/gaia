---
name: gmail-draft-send
description: Create and send Gmail emails using draft-first workflow. Always draft first, get user approval, then send.
target: gmail_agent
---

# Gmail Draft & Send

## When to Use
- User wants to send an email
- User wants to compose a new email
- User asks to email someone
- User wants to follow up on previous conversation

## Tools

### GMAIL_CREATE_EMAIL_DRAFT
Create a new email draft.

**Required parameters:**
- `recipient_email`: Recipient email address(es)
- `subject`: Email subject line
- `body`: Email body content

**Optional parameters:**
- `cc`: CC recipients
- `bcc`: BCC recipients
- `thread_id`: Reply within existing thread
- `attachments`: Files to attach (see below)

**Attachments:**
- `attachments` is a list. Each item references ONE file by EITHER `workspace_path` (a file in the current session workspace, e.g. one the user uploaded or that a tool saved there) OR `url` (a fetchable link). Optionally add `name` to set the attachment filename.
- To attach a **Google Drive** file: hand off to the Google Drive agent to find and download it (`GOOGLEDRIVE_DOWNLOAD_FILE`), then pass the download URL it returns as the attachment's `url`.
- Example: `attachments: [{ "workspace_path": "sessions/<conv>/uploads/report.pdf" }, { "url": "<drive download url>", "name": "Deck.pdf" }]`.
- Keep the total message under 25 MB. If a file cannot be read or uploaded, the draft is NOT created and you get an error — surface it to the user instead of pretending the draft was made.

**Body formatting:**
- Write the body as Markdown. The backend converts it to HTML before Gmail sends, so `**bold**`, `### headings`, `- lists`, and `[links](url)` all render correctly in the recipient's inbox.
- Draft beautiful, readable emails: short paragraphs, blank lines between sections, meaningful subject lines.
- Do not emit raw HTML (`<p>`, `<div>`, etc.) — write Markdown and let the pipeline handle it.

**Signature:**
- Use the user's proper name from context (`User Name:`) in the sign-off.
- Default sign-off: "Best regards," then the user's name.

### GMAIL_SEND_DRAFT
Send an already-created draft.

**Required parameters:**
- `draft_id`: The ID from GMAIL_CREATE_EMAIL_DRAFT response

### GMAIL_DELETE_DRAFT
Delete a draft. Gmail has no in-place draft edit, so this is how you remove a
superseded draft before creating the revised one. Deletion is permanent.

**Required parameters:**
- `draft_id`: The ID of the draft to delete (from the GMAIL_CREATE_EMAIL_DRAFT response)

### GMAIL_FETCH_MESSAGES
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
Always create a draft first using `GMAIL_CREATE_EMAIL_DRAFT`.
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
Use `GMAIL_SEND_DRAFT` with the draft_id **only after** user explicitly confirms.

### Step 5: Handle Change Requests
Gmail drafts cannot be edited in place. When the user wants changes to an
existing draft, replace it, don't add another:
1. Delete the current draft with `GMAIL_DELETE_DRAFT` (pass its `draft_id`).
2. Create the revised draft via `GMAIL_CREATE_EMAIL_DRAFT`.
3. Present the new draft for approval.

Never skip the delete. Creating a new draft without removing the old one leaves
duplicate drafts piling up in the user's Gmail Drafts folder. Keep exactly one
live draft per email at a time.

## Important Rules
1. **NEVER auto-send** - Always wait for explicit confirmation
2. **Verify recipients** - Confirm email addresses are correct
3. **Show full draft** - Subject, body, recipients all visible
4. **Handle errors gracefully** - If send fails, explain and offer retry
5. **Check before replying** - Search for context when replying to threads
6. **One live draft per email** - To revise, delete the old draft (GMAIL_DELETE_DRAFT with its draft_id) before creating the new one; never leave stale drafts behind

## Writing Style
- If the user context includes a **Learned Writing Style** section, use it as the primary guide for tone, voice, and phrasing when composing the email body.
- Match the style profile description (formality, length, greeting/sign-off patterns).
- Use the reference snippets as examples of how the user naturally writes.
- The user-selected writing style (e.g. "Formal", "Casual") from the UI takes precedence if it conflicts with the learned style.

## Tips
- Use clear, concise subject lines
- Keep body focused and actionable
- Use paragraphs for readability
- Include relevant context from previous emails
- Be professional but friendly in tone
