---
name: google-meet-create-invite
description: Create Google Meet video conferences and invite participants via Slack or email.
target: executor
---

# Google Meet: Create & Invite

## When to Use
- User asks to "create a Google Meet"
- User asks to "start a video call"
- User wants to "schedule a meeting with a Meet link"
- User asks to "set up a video conference"

## Tools

### GOOGLEMEET_CREATE_SPACE
Create a new Google Meet space.

**Returns:**
- Meeting link (URI)
- Space details

### GOOGLECALENDAR_CUSTOM_CREATE_EVENT
Add the meeting to calendar with the Meet link.

### SLACK_FIND_USERS
Find participants on Slack to invite.

### SLACK_SEND_MESSAGE
Send meeting link to participants on Slack.

### GMAIL_GET_CONTACTS
Get email addresses for participants.

### GMAIL_CREATE_DRAFT
Create email with meeting details to send manually.

## Workflow

### Step 1: Create the Meet Space

```
GOOGLEMEET_CREATE_SPACE()
```

Extract the meeting URI from the response.

### Step 2: Find Participants

**From Slack:**
```
SLACK_FIND_USERS(search_query="[Name]")
```

**From Contacts:**
```
GMAIL_GET_CONTACTS()
```

### Step 3: Share the Meeting Link

**Option A: Send via Slack**
```
SLACK_SEND_MESSAGE(
    channel=user_id,
    text="Here's the meeting link: [MEET_LINK]"
)
```

**Option B: Create email draft**
```
GMAIL_CREATE_DRAFT(
    to="email@example.com",
    subject="Meeting: [Topic]",
    body="Join the meeting: [MEET_LINK]"
)
```

### Step 4: Confirm to User

Report:
- Meeting link created
- Who was invited
- How the link was shared

## Important Rules
1. Always create the Meet space first, then share the link
2. Verify participant identity before sending invites
3. Include meeting topic in the invitation
4. Confirm success to the user

## Notes
- The meeting link is immediate and can be shared right away
- For scheduled meetings, also add to calendar with the Meet link in the description
