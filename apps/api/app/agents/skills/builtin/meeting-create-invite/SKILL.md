---
name: meeting-create-invite
description: Schedule meetings and generate video conferencing links (Google Meet, Zoom, Microsoft Teams) and invite participants.
target: executor
---

# Meeting: Create & Invite

## When to Use
- User asks to "create a meeting", "schedule a meeting", "set up a video conference", "start a video call"
- Applies to any supported video conferencing platform: Google Meet, Zoom, Microsoft Teams.

## Strategy / Important Rules
1. **Determine Platform Preference:** First, run `search_memory` to check if the user has a preferred default meeting platform. If unknown, run `list_integrations` to see which platforms (Google Calendar, Zoom, Microsoft Teams) are currently connected. If there are multiple and you are confused, ask the user for clarification.
2. **Google Meet (Preferred via Calendar):** If the meeting platform is Google Meet, create a Google Calendar event (`GOOGLECALENDAR_CUSTOM_CREATE_EVENT`) and include the participants as `attendees`. Google Calendar will automatically send them an invitation email. **Do not send a separate email manually.**
3. **Zoom or Microsoft Teams:** When creating a meeting for a platform *other* than Google Meet, do not attempt to "create a calendar event with attendees". Instead, use the exact platform tools to generate a meeting link:
   - For Zoom, use `ZOOM_CREATE_A_MEETING`
   - For Teams, use `MICROSOFT_TEAMS_CREATE_USER_ONLINE_MEETING` (or `MICROSOFT_TEAMS_CREATE_MEETING`)
4. **Drafting Emails for Links:** If sharing the link via email is requested or necessary (e.g., for Zoom/Teams links), use `GMAIL_CREATE_EMAIL_DRAFT` to draft an email with the generated link. **DO NOT send the email directly unless explicitly asked.** Wait for the user to review the draft.
5. Confirm participant identities before inviting.

## Tools
- `GOOGLECALENDAR_CUSTOM_CREATE_EVENT`: Create event and add attendees (for Google Meet).
- `ZOOM_CREATE_A_MEETING`: Generate a Zoom meeting link.
- `MICROSOFT_TEAMS_CREATE_USER_ONLINE_MEETING`: Generate a Teams meeting link.
- `MICROSOFT_TEAMS_CREATE_MEETING`: Alternate tool to generate a Teams meeting link.
- `GMAIL_GET_CONTACTS`: Get email addresses for participants.
- `GMAIL_CREATE_EMAIL_DRAFT`: Draft an email with the meeting details.
- `SLACK_FIND_USERS` / `SLACK_SEND_MESSAGE`: Share the meeting link via Slack if requested.

## Workflow

### Step 1: Identify Platform & Participants
- Run `search_memory` for preferred meeting app.
- If no preference is found, run `list_integrations` to check connected platforms and select an available one. Ask user for clarification if ambiguous.

### Step 2: Find Participants
**From Contacts:**
```
GMAIL_GET_CONTACTS()
```

**From Slack (If requested to share via Slack):**
```
SLACK_FIND_USERS(search_query="[Name]")
```

### Step 3: Create the Meeting
**Option A: Google Meet (Via Calendar)**
Use `GOOGLECALENDAR_CUSTOM_CREATE_EVENT` and include the participants as `attendees`. This automatically sends the invite emails.

**Option B: Separate Link Generation (Zoom/Teams)**
Use `ZOOM_CREATE_A_MEETING` or `MICROSOFT_TEAMS_CREATE_USER_ONLINE_MEETING` to generate the meeting link.

### Step 4: Share the Meeting Link (Only if Option B OR explicitly requested)
- **Drafting Email:** Use `GMAIL_CREATE_EMAIL_DRAFT(to="...", subject="...", body="Here is the meeting link: [LINK]")`. **Do not send directly.**
- **Slack:** Use `SLACK_SEND_MESSAGE` to share via Slack.

### Step 5: Confirm to User
Report:
- Meeting scheduled / link created.
- The platform used.
- That the invite link was drafted in an email (if applicable) and is ready for their manual review, or that the link was sent via Slack.
